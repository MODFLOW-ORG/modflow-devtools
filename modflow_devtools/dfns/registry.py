"""
DFN registry infrastructure for discovery, caching, and synchronization.

This module provides:
- Pydantic schemas for registry and bootstrap configuration
- Cache management for registries and DFN files
- Registry classes for local and remote DFN access
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import Version
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import pooch

    from modflow_devtools.dfns import Dfn, DfnSpec

__all__ = [
    "BootstrapConfig",
    "DfnRegistry",
    "DfnRegistryDiscoveryError",
    "DfnRegistryError",
    "DfnRegistryFile",
    "DfnRegistryMeta",
    "DfnRegistryNotFoundError",
    "LocalDfnRegistry",
    "RemoteDfnRegistry",
    "SourceConfig",
    "get_bootstrap_config",
    "get_cache_dir",
    "get_registry",
    "get_sync_status",
    "get_user_config_path",
    "sync_dfns",
]


# =============================================================================
# Pydantic Schemas for Bootstrap Configuration
# =============================================================================


class SourceConfig(BaseModel):
    """Configuration for a DFN source repository."""

    repo: str = Field(description="GitHub repository identifier (owner/name)")
    dfn_path: str = Field(
        default="doc/mf6io/mf6ivar/dfn",
        description="Path within the repository to the DFN files directory",
    )
    registry_path: str = Field(
        default=".registry/dfns.toml",
        description="Path within the repository to the registry metadata file",
    )
    refs: list[str] = Field(
        default_factory=list,
        description="Git refs (branches, tags, commit hashes) to sync by default",
    )


class BootstrapConfig(BaseModel):
    """Bootstrap configuration for DFN sources."""

    sources: dict[str, SourceConfig] = Field(
        default_factory=dict,
        description="Map of source names to their configurations",
    )

    @classmethod
    def load(cls, path: str | PathLike) -> BootstrapConfig:
        """Load bootstrap configuration from a TOML file."""
        import tomli

        path = Path(path)
        if not path.exists():
            return cls()

        with path.open("rb") as f:
            data = tomli.load(f)

        # Convert sources dict to SourceConfig instances
        sources = {}
        for name, config in data.get("sources", {}).items():
            sources[name] = SourceConfig(**config)

        return cls(sources=sources)

    @classmethod
    def merge(cls, base: BootstrapConfig, overlay: BootstrapConfig) -> BootstrapConfig:
        """Merge two bootstrap configs, with overlay taking precedence."""
        merged_sources = dict(base.sources)
        merged_sources.update(overlay.sources)
        return cls(sources=merged_sources)


# =============================================================================
# Pydantic Schemas for Registry Files
# =============================================================================


class DfnRegistryFile(BaseModel):
    """Entry for a single file in the registry."""

    hash: str = Field(description="SHA256 hash of the file (sha256:...)")


class DfnRegistryMeta(BaseModel):
    """
    Registry metadata and file listings.

    This represents the contents of a dfns.toml registry file.
    """

    schema_version: str = Field(
        default="1.0",
        description="Registry schema version",
    )
    generated_at: datetime | None = Field(
        default=None,
        description="When the registry was generated",
    )
    devtools_version: str | None = Field(
        default=None,
        description="Version of modflow-devtools that generated this registry",
    )
    ref: str | None = Field(
        default=None,
        description="Git ref this registry was generated from",
    )
    files: dict[str, DfnRegistryFile] = Field(
        default_factory=dict,
        description="Map of filenames to file metadata",
    )

    @classmethod
    def load(cls, path: str | PathLike) -> DfnRegistryMeta:
        """Load registry metadata from a TOML file."""
        import tomli

        path = Path(path)
        with path.open("rb") as f:
            data = tomli.load(f)

        # Handle nested structure: files section contains filename -> {hash: ...}
        files_data = data.pop("files", {})
        files = {}
        for filename, file_info in files_data.items():
            if isinstance(file_info, dict):
                files[filename] = DfnRegistryFile(**file_info)
            elif isinstance(file_info, str):
                # Support shorthand: filename = "hash"
                files[filename] = DfnRegistryFile(hash=file_info)

        # Handle metadata section if present
        metadata = data.pop("metadata", {})
        ref = metadata.get("ref") or data.pop("ref", None)

        return cls(
            schema_version=data.get("schema_version", "1.0"),
            generated_at=data.get("generated_at"),
            devtools_version=data.get("devtools_version"),
            ref=ref,
            files=files,
        )

    def save(self, path: str | PathLike) -> None:
        """Save registry metadata to a TOML file."""
        import tomli_w

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict = {
            "schema_version": self.schema_version,
        }

        if self.generated_at:
            data["generated_at"] = self.generated_at.isoformat()
        if self.devtools_version:
            data["devtools_version"] = self.devtools_version

        if self.ref:
            data["metadata"] = {"ref": self.ref}

        # Write files section
        data["files"] = {
            filename: {"hash": file_info.hash} for filename, file_info in self.files.items()
        }

        with path.open("wb") as f:
            tomli_w.dump(data, f)


# =============================================================================
# Cache and Configuration Utilities
# =============================================================================


def get_user_config_path(subdir: str = "dfn") -> Path:
    """
    Get the user configuration directory path.

    Parameters
    ----------
    subdir : str
        Subdirectory name (e.g., "dfn", "models", "programs").

    Returns
    -------
    Path
        Path to user config file (e.g., ~/.config/modflow-devtools/dfns.toml).
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base / "modflow-devtools" / f"{subdir}s.toml"


def get_cache_dir(subdir: str = "dfn") -> Path:
    """
    Get the cache directory path.

    Parameters
    ----------
    subdir : str
        Subdirectory name (e.g., "dfn", "models", "programs").

    Returns
    -------
    Path
        Path to cache directory (e.g., ~/.cache/modflow-devtools/dfn/).
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

    return base / "modflow-devtools" / subdir


def get_bootstrap_config() -> BootstrapConfig:
    """
    Load and merge bootstrap configuration.

    Loads the bundled bootstrap file and merges with user config if present.

    Returns
    -------
    BootstrapConfig
        Merged bootstrap configuration.
    """
    # Load bundled bootstrap config
    bundled_path = Path(__file__).parent / "dfns.toml"
    bundled_config = BootstrapConfig.load(bundled_path)

    # Load user config if present
    user_path = get_user_config_path("dfn")
    if user_path.exists():
        user_config = BootstrapConfig.load(user_path)
        return BootstrapConfig.merge(bundled_config, user_config)

    return bundled_config


# =============================================================================
# Registry Classes
# =============================================================================


class DfnRegistry(BaseModel):
    """
    Base class for DFN registries.

    A registry provides access to DFN files and the parsed DfnSpec.
    This is a Pydantic model that can be used directly for data-only use cases.
    """

    model_config = {"arbitrary_types_allowed": True}

    source: str = Field(default="modflow6", description="Source repository name")
    ref: str = Field(default="develop", description="Git ref (branch, tag, or commit hash)")

    _spec: DfnSpec | None = None

    @property
    def spec(self) -> DfnSpec:
        """
        Get the full DFN specification.

        Returns
        -------
        DfnSpec
            The parsed specification with hierarchical structure.
        """
        raise NotImplementedError("Subclasses must implement spec property")

    @property
    def schema_version(self) -> Version:
        """Get the schema version of the specification."""
        return self.spec.schema_version

    @property
    def components(self) -> dict[str, Dfn]:
        """Get all components as a flat dictionary."""
        return dict(self.spec.items())

    def get_dfn(self, component: str) -> Dfn:
        """
        Get a DFN by component name.

        Parameters
        ----------
        component : str
            Component name (e.g., "gwf-chd", "sim-nam").

        Returns
        -------
        Dfn
            The requested component definition.
        """
        return self.spec[component]

    def get_dfn_path(self, component: str) -> Path:
        """
        Get the local file path for a DFN.

        Parameters
        ----------
        component : str
            Component name (e.g., "gwf-chd", "sim-nam").

        Returns
        -------
        Path
            Path to the local DFN file.
        """
        raise NotImplementedError("Subclasses must implement get_dfn_path")


class LocalDfnRegistry(DfnRegistry):
    """
    Registry for local DFN files.

    Use this for working with DFN files on the local filesystem,
    e.g., during development or with a local clone of the MODFLOW 6 repository.
    """

    path: Path = Field(description="Path to directory containing DFN files")

    def model_post_init(self, __context) -> None:
        """Validate and resolve path after initialization."""
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())

    @property
    def spec(self) -> DfnSpec:
        """Load and return the DFN specification from local files."""
        if self._spec is None:
            from modflow_devtools.dfns import DfnSpec

            self._spec = DfnSpec.load(self.path)
        return self._spec

    def get_dfn_path(self, component: str) -> Path:
        """Get the local file path for a DFN component."""
        # Look for both .dfn and .toml extensions
        for ext in [".dfn", ".toml"]:
            p = self.path / f"{component}{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"Component '{component}' not found in {self.path}")


class RemoteDfnRegistry(DfnRegistry):
    """
    Registry for remote DFN files with Pooch-based caching.

    Handles remote registry discovery, caching, and DFN file fetching.
    URLs are constructed dynamically from bootstrap metadata, or can be
    overridden by providing explicit repo/dfn_path/registry_path values.

    Examples
    --------
    >>> # Use bootstrap config
    >>> registry = RemoteDfnRegistry(source="modflow6", ref="6.6.0")
    >>> dfn = registry.get_dfn("gwf-chd")

    >>> # Override repo directly (useful for testing)
    >>> registry = RemoteDfnRegistry(
    ...     source="modflow6",
    ...     ref="registry",
    ...     repo="wpbonelli/modflow6",
    ... )
    """

    # Optional overrides (bypass bootstrap config when provided)
    repo: str | None = Field(
        default=None,
        description="GitHub repository (owner/repo). Overrides bootstrap config.",
    )
    dfn_path: str | None = Field(
        default=None,
        description="Path to DFN files in repo. Overrides bootstrap config.",
    )
    registry_path: str | None = Field(
        default=None,
        description="Path to registry file in repo. Overrides bootstrap config.",
    )

    _registry_meta: DfnRegistryMeta | None = None
    _source_config: SourceConfig | None = None
    _pooch: pooch.Pooch | None = None
    _files_dir: Path | None = None

    def model_post_init(self, __context) -> None:
        """Initialize registry after model creation."""
        self._ensure_source_config()

    def _ensure_source_config(self) -> SourceConfig:
        """Load and cache source configuration from bootstrap or overrides."""
        if self._source_config is None:
            # If repo is provided, construct config from overrides
            if self.repo is not None:
                self._source_config = SourceConfig(
                    repo=self.repo,
                    dfn_path=self.dfn_path or "doc/mf6io/mf6ivar/dfn",
                    registry_path=self.registry_path or ".registry/dfns.toml",
                    refs=[self.ref],
                )
            else:
                # Load from bootstrap config
                config = get_bootstrap_config()
                if self.source not in config.sources:
                    raise ValueError(
                        f"Unknown source '{self.source}'. "
                        f"Available sources: {list(config.sources.keys())}"
                    )
                self._source_config = config.sources[self.source]
        return self._source_config

    def _get_registry_cache_path(self) -> Path:
        """Get path to cached registry file."""
        cache_dir = get_cache_dir("dfn")
        return cache_dir / "registries" / self.source / self.ref / "dfns.toml"

    def _get_files_cache_dir(self) -> Path:
        """Get directory for cached DFN files."""
        cache_dir = get_cache_dir("dfn")
        return cache_dir / "files" / self.source / self.ref

    def _construct_raw_url(self, path: str) -> str:
        """Construct GitHub raw content URL for a file."""
        source_config = self._ensure_source_config()
        return f"https://raw.githubusercontent.com/{source_config.repo}/{self.ref}/{path}"

    def _fetch_registry(self, force: bool = False) -> DfnRegistryMeta:
        """Fetch registry metadata from remote or cache."""
        cache_path = self._get_registry_cache_path()

        # Use cached registry if available and not forcing refresh
        if cache_path.exists() and not force:
            return DfnRegistryMeta.load(cache_path)

        # Fetch from remote
        source_config = self._ensure_source_config()
        registry_url = self._construct_raw_url(source_config.registry_path)

        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(registry_url, timeout=30) as response:
                content = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DfnRegistryNotFoundError(
                    f"Registry not found at {registry_url} for '{self.source}@{self.ref}'. "
                    f"The registry file may not exist for this ref."
                ) from e
            raise DfnRegistryDiscoveryError(
                f"Failed to fetch registry from {registry_url}: {e}"
            ) from e
        except urllib.error.URLError as e:
            raise DfnRegistryDiscoveryError(
                f"Network error fetching registry from {registry_url}: {e}"
            ) from e

        # Parse and cache
        import tomli

        data = tomli.loads(content.decode("utf-8"))

        # Build registry meta from parsed data
        files_data = data.pop("files", {})
        files = {}
        for filename, file_info in files_data.items():
            if isinstance(file_info, dict):
                files[filename] = DfnRegistryFile(**file_info)
            elif isinstance(file_info, str):
                files[filename] = DfnRegistryFile(hash=file_info)

        metadata = data.pop("metadata", {})
        registry_meta = DfnRegistryMeta(
            schema_version=data.get("schema_version", "1.0"),
            generated_at=data.get("generated_at"),
            devtools_version=data.get("devtools_version"),
            ref=metadata.get("ref") or data.get("ref") or self.ref,
            files=files,
        )

        # Cache the registry
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        registry_meta.save(cache_path)

        return registry_meta

    def _ensure_registry_meta(self, force: bool = False) -> DfnRegistryMeta:
        """Ensure registry metadata is loaded."""
        if self._registry_meta is None or force:
            self._registry_meta = self._fetch_registry(force=force)
        return self._registry_meta

    def _setup_pooch(self) -> pooch.Pooch:
        """Set up Pooch for DFN file fetching."""
        if self._pooch is not None:
            return self._pooch

        import pooch

        registry_meta = self._ensure_registry_meta()
        source_config = self._ensure_source_config()

        # Construct base URL for DFN files
        base_url = self._construct_raw_url(source_config.dfn_path) + "/"

        # Build registry dict for Pooch (filename -> hash)
        pooch_registry = {}
        for filename, file_info in registry_meta.files.items():
            # Pooch expects hash without "sha256:" prefix for sha256
            hash_value = file_info.hash
            if hash_value.startswith("sha256:"):
                hash_value = hash_value[7:]
            pooch_registry[filename] = f"sha256:{hash_value}"

        self._files_dir = self._get_files_cache_dir()
        self._pooch = pooch.create(
            path=self._files_dir,
            base_url=base_url,
            registry=pooch_registry,
        )

        return self._pooch

    def sync(self, force: bool = False) -> None:
        """
        Synchronize registry and optionally pre-fetch all DFN files.

        Parameters
        ----------
        force : bool, optional
            If True, re-fetch registry even if cached. Default is False.
        """
        self._ensure_registry_meta(force=force)
        self._setup_pooch()

    @property
    def registry_meta(self) -> DfnRegistryMeta:
        """Get the registry metadata."""
        return self._ensure_registry_meta()

    @property
    def spec(self) -> DfnSpec:
        """Load and return the DFN specification from cached files."""
        if self._spec is None:
            from modflow_devtools.dfns import DfnSpec

            # Ensure all files are fetched
            self._fetch_all_files()

            # Load from cache directory
            self._spec = DfnSpec.load(self._get_files_cache_dir())
        return self._spec

    def _fetch_all_files(self) -> None:
        """Fetch all DFN files to cache."""
        p = self._setup_pooch()
        registry_meta = self._ensure_registry_meta()

        for filename in registry_meta.files:
            # Skip non-DFN files (like spec.toml)
            if filename.endswith(".dfn") or filename.endswith(".toml"):
                p.fetch(filename)

    def get_dfn_path(self, component: str) -> Path:
        """Get the local cached file path for a DFN component."""
        p = self._setup_pooch()
        registry_meta = self._ensure_registry_meta()

        # Look for both .dfn and .toml extensions
        for ext in [".dfn", ".toml"]:
            filename = f"{component}{ext}"
            if filename in registry_meta.files:
                return Path(p.fetch(filename))

        raise FileNotFoundError(
            f"Component '{component}' not found in registry for '{self.source}@{self.ref}'"
        )


# =============================================================================
# Exceptions
# =============================================================================


class DfnRegistryError(Exception):
    """Base exception for DFN registry errors."""

    pass


class DfnRegistryNotFoundError(DfnRegistryError):
    """Registry file not found for the specified ref."""

    pass


class DfnRegistryDiscoveryError(DfnRegistryError):
    """Error during registry discovery."""

    pass


# =============================================================================
# Sync Functions
# =============================================================================


def sync_dfns(
    source: str = "modflow6",
    ref: str | None = None,
    force: bool = False,
) -> list[RemoteDfnRegistry]:
    """
    Synchronize DFN registries from remote sources.

    Parameters
    ----------
    source : str, optional
        Source repository name. Default is "modflow6".
    ref : str, optional
        Specific git ref to sync. If not provided, syncs all configured refs.
    force : bool, optional
        If True, re-fetch registries even if cached. Default is False.

    Returns
    -------
    list[RemoteDfnRegistry]
        List of synced registries.

    Examples
    --------
    >>> # Sync all configured refs
    >>> registries = sync_dfns()

    >>> # Sync specific ref
    >>> registries = sync_dfns(ref="6.6.0")

    >>> # Force re-sync
    >>> registries = sync_dfns(force=True)
    """
    config = get_bootstrap_config()

    if source not in config.sources:
        raise ValueError(
            f"Unknown source '{source}'. Available sources: {list(config.sources.keys())}"
        )

    source_config = config.sources[source]

    # Determine which refs to sync
    refs_to_sync = [ref] if ref else source_config.refs

    registries = []
    for r in refs_to_sync:
        registry = RemoteDfnRegistry(source=source, ref=r)
        registry.sync(force=force)
        registries.append(registry)

    return registries


def get_sync_status(source: str = "modflow6") -> dict[str, bool]:
    """
    Check which refs have cached registries.

    Parameters
    ----------
    source : str, optional
        Source repository name. Default is "modflow6".

    Returns
    -------
    dict[str, bool]
        Map of ref names to whether they have a cached registry.
    """
    config = get_bootstrap_config()

    if source not in config.sources:
        raise ValueError(
            f"Unknown source '{source}'. Available sources: {list(config.sources.keys())}"
        )

    source_config = config.sources[source]
    cache_dir = get_cache_dir("dfn")

    status = {}
    for ref in source_config.refs:
        registry_path = cache_dir / "registries" / source / ref / "dfns.toml"
        status[ref] = registry_path.exists()

    return status


def get_registry(
    source: str = "modflow6",
    ref: str = "develop",
    auto_sync: bool = True,
) -> RemoteDfnRegistry:
    """
    Get a registry for the specified source and ref.

    Parameters
    ----------
    source : str, optional
        Source repository name. Default is "modflow6".
    ref : str, optional
        Git ref (branch, tag, or commit hash). Default is "develop".
    auto_sync : bool, optional
        If True and registry is not cached, automatically sync. Default is True.
        Can be disabled via MODFLOW_DEVTOOLS_NO_AUTO_SYNC environment variable.

    Returns
    -------
    RemoteDfnRegistry
        Registry for the specified source and ref.

    Examples
    --------
    >>> registry = get_registry(ref="6.6.0")
    >>> dfn = registry.get_dfn("gwf-chd")
    """
    # Check for auto-sync opt-out
    if os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC", "").lower() in ("1", "true", "yes"):
        auto_sync = False

    registry = RemoteDfnRegistry(source=source, ref=ref)

    # Check if registry is cached
    cache_path = registry._get_registry_cache_path()
    if not cache_path.exists() and auto_sync:
        registry.sync()

    return registry
