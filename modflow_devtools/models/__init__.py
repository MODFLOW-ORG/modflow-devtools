import hashlib
import os
import urllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from os import PathLike
from pathlib import Path
from shutil import copy
from typing import ClassVar, Literal

import pooch
import tomli
import tomli_w
from boltons.iterutils import remap
from filelock import FileLock
from pooch import Pooch
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

import modflow_devtools
from modflow_devtools.download import fetch_url
from modflow_devtools.misc import drop_none_or_empty, get_model_paths

_CACHE_ROOT = Path(pooch.os_cache("modflow-devtools"))
"""
Root cache directory

Uses Pooch's os_cache() for platform-appropriate location:
- Linux: ~/.cache/modflow-devtools
- macOS: ~/Library/Caches/modflow-devtools
- Windows: ~\\AppData\\Local\\modflow-devtools\\Cache
"""

_DEFAULT_REGISTRY_FILE_NAME = "registry.toml"
"""The default registry file name"""

_EXCLUDED_PATTERNS = [".DS_Store", "compare"]
"""Filename patterns to exclude from registry (substring match)"""

_OUTPUT_FILE_EXTENSIONS = [
    ".lst",  # list file
    ".hds",  # head file
    ".hed",  # head file
    ".cbb",  # budget file
    ".cbc",  # budget file
    ".bud",  # budget file
    ".ddn",  # drawdown file
    ".ucn",  # concentration file
    ".obs",  # observation file
    ".glo",  # global listing file
]
"""Output file extensions to exclude from model input registry"""


def _should_exclude_file(path: Path) -> bool:
    """
    Check if a file should be excluded from the registry.

    Excludes files matching patterns in _EXCLUDED_PATTERNS (substring match)
    or with extensions in _OUTPUT_FILE_EXTENSIONS.

    Parameters
    ----------
    path : Path
        File path to check

    Returns
    -------
    bool
        True if file should be excluded, False otherwise
    """
    # Check filename patterns (substring match)
    if any(pattern in path.name for pattern in _EXCLUDED_PATTERNS):
        return True

    # Check output file extensions (exact suffix match)
    if path.suffix.lower() in _OUTPUT_FILE_EXTENSIONS:
        return True

    return False


class ModelInputFile(BaseModel):
    """
    A single file entry in the registry. Can be local or remote.

    Implements dict-like access for backwards compatibility:
    file_entry["hash"], file_entry["path"], file_entry["url"]
    """

    url: str | None = Field(None, description="URL (for remote files)")
    path: Path | None = Field(None, description="Local file path (original or cached)")
    hash: str | None = Field(None, description="SHA256 hash of the file")

    @field_serializer("path")
    def serialize_path(self, p: Path | None, _info):
        """Serialize Path to string (POSIX format)."""
        return str(p) if p is not None else None

    @model_validator(mode="after")
    def check_location(self):
        """Ensure at least one of url or path is provided."""
        if not self.url and not self.path:
            raise ValueError("FileEntry must have either url or path")
        return self

    # Backwards compatibility: dict-like access
    def __getitem__(self, key: str):
        """Allow dict-like access for backwards compatibility."""
        if key == "url":
            return self.url
        elif key == "path":
            return self.path
        elif key == "hash":
            return self.hash
        raise KeyError(key)

    def get(self, key: str, default=None):
        """Allow dict-like .get() for backwards compatibility."""
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self):
        """Return available keys for backwards compatibility."""
        return ["url", "path", "hash"]

    def values(self):
        """Return values for backwards compatibility."""
        return [self.url, self.path, self.hash]

    def items(self):
        """Return items for backwards compatibility."""
        return [("url", self.url), ("path", self.path), ("hash", self.hash)]


class ModelRegistry(BaseModel):
    """
    Base class for model registries.

    Defines the common structure for both local and remote registries.
    """

    schema_version: str | None = Field(None, description="Registry schema version")
    generated_at: datetime | None = Field(None, description="Timestamp when registry was generated")
    devtools_version: str | None = Field(
        None, description="Version of modflow-devtools used to generate"
    )
    files: dict[str, ModelInputFile] = Field(
        default_factory=dict, description="Map of file names to file entries"
    )
    models: dict[str, list[str]] = Field(
        default_factory=dict, description="Map of model names to file lists"
    )
    examples: dict[str, list[str]] = Field(
        default_factory=dict, description="Map of example names to model lists"
    )

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    @field_serializer("generated_at")
    def serialize_datetime(self, dt: datetime | None, _info):
        """Serialize datetime to ISO format string."""
        return dt.isoformat() if dt is not None else None

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy a model's input files to the given workspace.

        Subclasses must override this method to provide actual implementation.

        Parameters
        ----------
        workspace : str | PathLike
            Destination workspace directory
        model_name : str
            Name of the model to copy
        verbose : bool
            Print progress messages

        Returns
        -------
        Path | None
            Path to the workspace, or None if model not found

        Raises
        ------
        NotImplementedError
            If called on base Registry class (must use subclass)
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement copy_to(). "
            "Use LocalRegistry or PoochRegistry instead."
        )

    def to_pooch_registry(self) -> dict[str, str | None]:
        """Convert to format expected by Pooch.registry (filename -> hash)."""
        return {name: entry.hash for name, entry in self.files.items()}

    def to_pooch_urls(self) -> dict[str, str]:
        """Convert to format expected by Pooch.urls (filename -> url)."""
        return {name: entry.url for name, entry in self.files.items() if entry.url is not None}


@dataclass
class ModelCache:
    root: Path

    def model_cache_dir(self) -> Path:
        """Model cache directory"""
        return self.root / "models"

    def get_registry_cache_dir(self, source: str, ref: str) -> Path:
        """
        Get the cache directory for a specific source and ref.

        Parameters
        ----------
        source : str
            Source name (e.g., 'modflow6-testmodels' or 'mf6/test').
            May contain slashes which will create nested directories.
        ref : str
            Git ref (branch, tag, or commit hash)
        """
        return self.root / "registries" / source / ref

    def save(self, registry: ModelRegistry, source: str, ref: str) -> Path:
        """
        Cache a registry file.

        Parameters
        ----------
        registry : Registry
            Registry to cache
        source : str
            Source name
        ref : str
            Git ref

        Returns
        -------
        Path
            Path to cached registry file
        """
        cache_dir = self.get_registry_cache_dir(source, ref)
        cache_dir.mkdir(parents=True, exist_ok=True)

        registry_file = cache_dir / _DEFAULT_REGISTRY_FILE_NAME

        # Convert registry to dict and clean None/empty values before serializing to TOML
        registry_dict = registry.model_dump(mode="json", by_alias=True, exclude_none=True)
        registry_dict = remap(registry_dict, visit=drop_none_or_empty)

        with registry_file.open("wb") as f:
            tomli_w.dump(registry_dict, f)

        return registry_file

    def load(self, source: str, ref: str) -> ModelRegistry | None:
        """
        Load a cached registry if it exists.

        Parameters
        ----------
        source : str
            Source name
        ref : str
            Git ref

        Returns
        -------
        Registry | None
            Cached registry if found, None otherwise
        """
        registry_file = self.get_registry_cache_dir(source, ref) / _DEFAULT_REGISTRY_FILE_NAME
        if not registry_file.exists():
            return None

        with registry_file.open("rb") as f:
            return ModelRegistry(**tomli.load(f))

    def has(self, source: str, ref: str) -> bool:
        """
        Check if a registry is cached.

        Parameters
        ----------
        source : str
            Source name
        ref : str
            Git ref

        Returns
        -------
        bool
            True if registry is cached, False otherwise
        """
        registry_file = self.get_registry_cache_dir(source, ref) / _DEFAULT_REGISTRY_FILE_NAME
        return registry_file.exists()

    def clear(self, source: str | None = None, ref: str | None = None) -> None:
        """
        Clear cached registries.

        Parameters
        ----------
        source : str | None
            If provided, only clear this source. If None, clear all sources.
        ref : str | None
            If provided (with source), only clear this ref. If None, clear all refs.

        Examples
        --------
        Clear everything:
            clear_registry_cache()

        Clear a specific source:
            clear_registry_cache(source="modflow6-testmodels")

        Clear a specific source/ref:
            clear_registry_cache(source="modflow6-testmodels", ref="develop")
        """
        import shutil
        import time

        def _rmtree_with_retry(path, max_retries=5, delay=0.5):
            """Remove tree with retry logic for Windows file handle delays."""
            for attempt in range(max_retries):
                try:
                    shutil.rmtree(path)
                    return
                except PermissionError:
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                    else:
                        raise

        if source and ref:
            # Clear specific source/ref
            cache_dir = self.get_registry_cache_dir(source, ref)
            if cache_dir.exists():
                _rmtree_with_retry(cache_dir)
        elif source:
            # Clear all refs for a source
            source_dir = self.root / "registries" / source
            if source_dir.exists():
                _rmtree_with_retry(source_dir)
        else:
            # Clear all registries
            registries_dir = self.root / "registries"
            if registries_dir.exists():
                _rmtree_with_retry(registries_dir)

    def list(self) -> list[tuple[str, str]]:
        """
        List all cached registries.

        Returns
        -------
        list[tuple[str, str]]
            List of (source, ref) tuples for cached registries
        """
        registries_dir = self.root / "registries"
        if not registries_dir.exists():
            return []

        cached = []
        for registry_file in registries_dir.rglob(_DEFAULT_REGISTRY_FILE_NAME):
            # Extract source and ref from path
            # e.g., registries/mf6/test/registry/registry.toml
            # → parts = ['mf6', 'test', 'registry', 'registry.toml']
            parts = registry_file.relative_to(registries_dir).parts
            if len(parts) >= 2:
                ref = parts[-2]  # 'registry' (second-to-last)
                source = "/".join(parts[:-2])  # 'mf6/test' (everything before ref)
                cached.append((source, ref))

        return cached


_DEFAULT_CACHE = ModelCache(root=_CACHE_ROOT)
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "models.toml"


def get_user_config_path() -> Path:
    """
    Get the path to the user model configuration file.

    Returns the platform-appropriate user config location:
    - Linux/macOS: $XDG_CONFIG_HOME/modflow-devtools/models.toml
                   (defaults to ~/.config/modflow-devtools/models.toml)
    - Windows: %APPDATA%/modflow-devtools/models.toml

    Returns
    -------
    Path
        Path to user bootstrap config file
    """
    if os.name == "nt":  # Windows
        config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:  # Unix-like (Linux, macOS, etc.)
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return config_dir / "modflow-devtools" / "models.toml"


RegistryMode = Literal["release_asset", "version_controlled"]


class ModelRegistryDiscoveryError(Exception):
    """Raised when registry discovery fails."""

    pass


@dataclass
class DiscoveredModelRegistry:
    """Result of registry discovery."""

    registry: ModelRegistry
    mode: RegistryMode
    source: str
    ref: str
    url: str


class ModelSourceRepo(BaseModel):
    """A single source model repository in the bootstrap file."""

    @dataclass
    class SyncResult:
        """Result of a sync operation."""

        synced: list[tuple[str, str]] = field(default_factory=list)  # [(source, ref), ...]
        skipped: list[tuple[str, str]] = field(default_factory=list)  # [(ref, reason), ...]
        failed: list[tuple[str, str]] = field(default_factory=list)  # [(ref, error), ...]

    @dataclass
    class SyncStatus:
        """Model source repo sync status."""

        repo: str
        configured_refs: list[str]
        cached_refs: list[str]
        missing_refs: list[str]

    repo: str = Field(..., description="Repository in format 'owner/name'")
    name: str = Field(
        ..., description="Name for model addressing (injected from key if not explicit)"
    )
    refs: list[str] = Field(
        default_factory=list,
        description="Default refs to sync (branches, tags, or commit hashes)",
    )
    registry_path: str = Field(
        default=".registry",
        description="Path to registry directory in repository",
    )

    @field_validator("repo")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        """Validate repo format is 'owner/name'."""
        if "/" not in v:
            raise ValueError(f"repo must be in format 'owner/name', got: {v}")
        parts = v.split("/")
        if len(parts) != 2:
            raise ValueError(f"repo must be in format 'owner/name', got: {v}")
        owner, name = parts
        if not owner or not name:
            raise ValueError(f"repo owner and name cannot be empty, got: {v}")
        return v

    def discover(
        self,
        ref: str,
    ) -> DiscoveredModelRegistry:
        """
        Discover a registry for the given source and ref.

        Implements the discovery procedure:
        1. Look for a matching release tag (registry as release asset)
        2. Fall back to version-controlled registry (in .registry/ directory)

        Parameters
        ----------
        source : BootstrapSource
            Source metadata from bootstrap file (must have name populated)
        ref : str
            Git ref (tag, branch, or commit hash)

        Returns
        -------
        DiscoveredRegistry
            The discovered registry with metadata

        Raises
        ------
        RegistryDiscoveryError
            If registry cannot be discovered
        """
        org, repo_name = self.repo.split("/")
        registry_path = self.registry_path

        # Step 1: Try release assets
        release_url = f"https://github.com/{org}/{repo_name}/releases/download/{ref}/models.toml"
        try:
            registry_data = fetch_url(release_url)
            registry = ModelRegistry(**tomli.loads(registry_data))
            return DiscoveredModelRegistry(
                registry=registry,
                mode="release_asset",
                source=self.name,
                ref=ref,
                url=release_url,
            )
        except urllib.error.HTTPError as e:
            if e.code != 404:
                # Some other error - re-raise
                raise ModelRegistryDiscoveryError(
                    f"Error fetching registry from release assets for '{self.name}@{ref}': {e}"
                )
            # 404 means no release with this tag, fall through to version-controlled

        # Step 2: Try version-controlled registry
        vc_url = (
            f"https://raw.githubusercontent.com/{org}/{repo_name}/{ref}/{registry_path}/models.toml"
        )
        try:
            registry_data = fetch_url(vc_url)
            registry = ModelRegistry(**tomli.loads(registry_data))
            return DiscoveredModelRegistry(
                registry=registry,
                mode="version_controlled",
                source=self.name,
                ref=ref,
                url=vc_url,
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ModelRegistryDiscoveryError(
                    f"Registry file 'models.toml' not found "
                    f"in {registry_path} for '{self.name}@{ref}'"
                )
            else:
                raise ModelRegistryDiscoveryError(
                    f"Error fetching registry from repository for '{self.name}@{ref}': {e}"
                )
        except Exception as e:
            raise ModelRegistryDiscoveryError(
                f"Registry discovery failed for '{self.name}@{ref}': {e}"
            )

    def sync(
        self,
        ref: str | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> SyncResult:
        """
        Sync this source to local cache.

        Parameters
        ----------
        ref : str | None
            Specific ref to sync. If None, syncs all configured refs.
        force : bool
            Force re-download even if cached
        verbose : bool
            Print progress messages

        Returns
        -------
        SyncResult
            Results of the sync operation
        """

        source_name = self.name
        refs = [ref] if ref else self.refs

        if not refs:
            if verbose:
                print(f"No refs configured for source '{source_name}', aborting")
            return ModelSourceRepo.SyncResult()

        result = ModelSourceRepo.SyncResult()

        for ref in refs:
            if not force and _DEFAULT_CACHE.has(source_name, ref):
                if verbose:
                    print(f"Registry {source_name}@{ref} already cached, skipping")
                result.skipped.append((ref, "already cached"))
                continue

            try:
                if verbose:
                    print(f"Discovering registry {source_name}@{ref}...")

                discovered = self.discover(ref=ref)
                if verbose:
                    print(f"  Caching registry found via {discovered.mode} at {discovered.url}...")

                _DEFAULT_CACHE.save(discovered.registry, source_name, ref)
                if verbose:
                    print(f"  [+] Synced {source_name}@{ref}")

                result.synced.append((source_name, ref))

            except ModelRegistryDiscoveryError as e:
                print(f"  [-] Failed to sync {source_name}@{ref}: {e}")
                result.failed.append((ref, str(e)))
            except Exception as e:
                print(f"  [-] Unexpected error syncing {source_name}@{ref}: {e}")
                result.failed.append((ref, str(e)))

        return result

    def is_synced(self, ref: str) -> bool:
        """
        Check if a specific ref is synced.

        Parameters
        ----------
        ref : str
            Git ref to check

        Returns
        -------
        bool
            True if ref is cached, False otherwise
        """
        return _DEFAULT_CACHE.has(self.name, ref)

    def list_synced_refs(self) -> list[str]:
        """
        List all synced refs for this source.

        Returns
        -------
        list[str]
            List of synced refs
        """
        cached = _DEFAULT_CACHE.list()
        return [ref for source, ref in cached if source == self.name]


class ModelSourceConfig(BaseModel):
    """Model source configuration file structure."""

    sources: dict[str, ModelSourceRepo] = Field(
        ..., description="Map of source names to source metadata"
    )

    @classmethod
    def load(
        cls,
        bootstrap_path: str | PathLike | None = None,
        user_config_path: str | PathLike | None = None,
    ) -> "ModelSourceConfig":
        """
        Load model source configuration.

        Parameters
        ----------
        bootstrap_path : str | PathLike | None
            Path to bootstrap config file. If None, uses bundled default.
            If provided, ONLY this file is loaded (no user config overlay unless specified).
        user_config_path : str | PathLike | None
            Path to user config file to overlay on top of bootstrap.
            If None and bootstrap_path is None, attempts to load from default user config location.

        Returns
        -------
        ModelSourceConfig
            Loaded and merged configuration
        """
        # Load base config
        if bootstrap_path is not None:
            # Explicit bootstrap path - only load this file
            with Path(bootstrap_path).open("rb") as f:
                cfg = tomli.load(f)
        else:
            # Use bundled default
            with _DEFAULT_CONFIG_PATH.open("rb") as f:
                cfg = tomli.load(f)

            # If no explicit bootstrap path, try to load user config overlay
            if user_config_path is None:
                user_config_path = get_user_config_path()

        # Overlay user config if specified or found
        if user_config_path is not None:
            user_path = Path(user_config_path)
            if user_path.exists():
                with user_path.open("rb") as f:
                    user_cfg = tomli.load(f)
                    # Merge user config sources into base config
                    if "sources" in user_cfg:
                        if "sources" not in cfg:
                            cfg["sources"] = {}
                        cfg["sources"] = cfg["sources"] | user_cfg["sources"]

        # inject source names if not explicitly provided
        for name, src in cfg.get("sources", {}).items():
            if "name" not in src:
                src["name"] = name

        return cls(**cfg)

    @classmethod
    def merge(cls, base: "ModelSourceConfig", overlay: "ModelSourceConfig") -> "ModelSourceConfig":
        """
        Merge two configurations, with overlay taking precedence.

        Parameters
        ----------
        base : ModelSourceConfig
            Base configuration
        overlay : ModelSourceConfig
            Configuration to overlay on top of base

        Returns
        -------
        ModelSourceConfig
            Merged configuration
        """
        merged_sources = base.sources.copy()
        merged_sources.update(overlay.sources)
        return cls(sources=merged_sources)

    @property
    def status(self) -> dict[str, ModelSourceRepo.SyncStatus]:
        """
        Sync status for all configured model source repositories.

        Returns
        -------
        dict
            Dictionary mapping source names to sync status info
        """
        cached_registries = set(_DEFAULT_CACHE.list())

        status = {}
        for source in self.sources.values():
            name = source.name
            refs = source.refs if source.refs else []

            cached: list[str] = []
            missing: list[str] = []

            for ref in refs:
                if (name, ref) in cached_registries:
                    cached.append(ref)
                else:
                    missing.append(ref)

            status[name] = ModelSourceRepo.SyncStatus(
                repo=source.repo,
                configured_refs=refs,
                cached_refs=cached,
                missing_refs=missing,
            )

        return status

    def sync(
        self,
        source: str | ModelSourceRepo | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> dict[str, ModelSourceRepo.SyncResult]:
        """
        Synchronize registry files from model source(s).

        Parameters
        ----------
        source : str | BootstrapSource | None
            Specific source to sync. Can be a source name (string) to look up in bootstrap,
            or a BootstrapSource object directly. If None, syncs all sources from bootstrap.
        force : bool
            Force re-download even if cached
        verbose : bool
            Print progress messages

        Returns
        -------
        dict of SyncResult
            Results of the sync operation

        """

        if source:
            if isinstance(source, ModelSourceRepo):
                if source.name not in self.sources:
                    raise ValueError(f"Source '{source.name}' not found in bootstrap")
                sources = [source]
            elif isinstance(source, str):
                if (src := self.sources.get(source, None)) is None:
                    raise ValueError(f"Source '{source}' not found in bootstrap")
                sources = [src]
        else:
            sources = list(self.sources.values())

        return {src.name: src.sync(force=force, verbose=verbose) for src in sources}


# Best-effort sync flag (to avoid multiple sync attempts)
_SYNC_ATTEMPTED = False


def _model_sort_key(k) -> int:
    if "gwf" in k:
        return 0
    return 1


def _sha256(path: Path) -> str:
    """
    Compute the SHA256 hash of the given file.
    Reference: https://stackoverflow.com/a/44873382/6514033
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with path.open("rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


class LocalRegistry(ModelRegistry):
    """
    A registry of models in one or more local directories.

    *Not* persistent &mdash; lives only in memory, unlike `PoochRegistry`.

    Indexing a directory recursively scans it for models (located by the
    presence of a namefile) and registers corresponding input files.
    """

    exclude: ClassVar = _EXCLUDED_PATTERNS  # For backwards compatibility

    # Non-Pydantic instance variable for tracking indexed paths
    _paths: set[Path]

    def __init__(self) -> None:
        # Initialize Pydantic parent with empty data (no metadata for local registries)
        super().__init__(
            schema_version=None,
            generated_at=None,
            devtools_version=None,
            files={},
            models={},
            examples={},
        )
        # Initialize non-Pydantic tracking variable
        self._paths = set()

    def index(
        self,
        path: str | PathLike,
        prefix: str | None = None,
        namefile: str = "mfsim.nam",
        excluded: list[str] | None = None,
        model_name_prefix: str = "",
    ):
        """
        Add models found under the given path to the registry.

        Call this once or more to prepare a registry. If called on the same
        `path` again, the models will be reloaded &mdash; thus this method
        is idempotent and may be used to reload the registry e.g. if model
        files have changed since the registry was created.

        The `path` may consist of model subdirectories at arbitrary depth.
        Model subdirectories are identified by the presence of a namefile
        matching `namefile_pattern`. Model subdirectories may be filtered
        inclusively by `prefix` or exclusively by `excluded`

        A `model_name_prefix` may be specified to avoid collisions with
        models indexed from other directories. This prefix will be added
        to the model name, which is derived from the relative path of the
        model subdirectory under `path`.
        """

        path = Path(path).expanduser().resolve().absolute()
        if not path.is_dir():
            raise NotADirectoryError(f"Directory path not found: {path}")
        self._paths.add(path)

        model_paths = get_model_paths(path, prefix=prefix, namefile=namefile, excluded=excluded)
        for model_path in model_paths:
            model_path = model_path.expanduser().resolve().absolute()
            rel_path = model_path.relative_to(path)
            parts = (
                [model_name_prefix, *list(rel_path.parts)]
                if model_name_prefix
                else list(rel_path.parts)
            )
            model_name = "/".join(parts)
            self.models[model_name] = []
            if len(rel_path.parts) > 1:
                name = rel_path.parts[0]
                if name not in self.examples:
                    self.examples[name] = []
                self.examples[name].append(model_name)
            for p in model_path.rglob("*"):
                if not p.is_file() or _should_exclude_file(p):
                    continue
                relpath = p.expanduser().absolute().relative_to(path)
                name = "/".join(relpath.parts)
                # Create FileEntry with local path
                self.files[name] = ModelInputFile(path=p, url=None, hash=None)
                self.models[model_name].append(name)

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy the model's input files to the given workspace.
        The workspace will be created if it does not exist.
        """

        if not any(file_names := self.models.get(model_name, [])):
            return None

        # Get actual file paths from FileEntry objects
        file_paths = [p for name in file_names if (p := self.files[name].path) is not None]

        # create the workspace if needed
        workspace = Path(workspace).expanduser().absolute()
        if verbose:
            print(f"Creating workspace {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        # copy the files. some might be in nested folders,
        # but the first is guaranteed not to be, so use it
        # to determine relative path in the new workspace.
        base = file_paths[0].parent
        for file_path in file_paths:
            if verbose:
                print(f"Copying {file_path} to workspace")
            dest = workspace / file_path.relative_to(base)
            dest.parent.mkdir(parents=True, exist_ok=True)
            copy(file_path, dest)
        return workspace

    @property
    def paths(self) -> set[Path]:
        """Set of paths that have been indexed."""
        return self._paths


class PoochRegistry(ModelRegistry):
    """
    A registry of models living in one or more GitHub repositories, accessible via
    URLs. The registry uses Pooch to fetch models from the remote(s) where needed.

    On import, the registry is loaded from a database distributed with the package.
    This database consists of TOML files containing file info as expected by Pooch,
    a map grouping files by model name, and a map grouping model names by example.
    Creating this database is a developer task. It should be checked into version
    control and updated whenever models are added to, removed from, or edited in
    the repositories referenced by the registry.

    **Note**: since the registry must change whenever the remote branch does, it
    should be aimed only at stable branches.
    """

    anchor: ClassVar = f"{modflow_devtools.__name__}.registry"
    registry_file_name: ClassVar = "registry.toml"
    models_file_name: ClassVar = "models.toml"
    examples_file_name: ClassVar = "examples.toml"

    # Non-Pydantic instance variables
    _registry_path: Path
    _registry_file_path: Path
    _models_file_path: Path
    _examples_file_path: Path
    _path: Path
    _pooch: Pooch
    _fetchers: dict
    _urls: dict

    def __init__(
        self,
        path: str | PathLike | None = None,
        base_url: str | None = None,
        env: str | None = None,
        retries: int = 3,
    ):
        # Initialize Pydantic parent with empty data (will be populated by _load())
        super().__init__(
            schema_version=None,
            generated_at=None,
            devtools_version=None,
            files={},
            models={},
            examples={},
        )

        # Initialize non-Pydantic instance variables
        self._registry_path = Path(__file__).parent.parent / "registry"
        self._registry_path.mkdir(parents=True, exist_ok=True)
        self._registry_file_path = self._registry_path / PoochRegistry.registry_file_name
        self._models_file_path = self._registry_path / PoochRegistry.models_file_name
        self._examples_file_path = self._registry_path / PoochRegistry.examples_file_name
        self._path = (
            Path(path).expanduser().absolute()
            if path
            else pooch.os_cache(modflow_devtools.__name__.replace("_", "-"))
        )
        self._pooch = pooch.create(
            path=self._path,
            base_url=base_url,
            version=modflow_devtools.__version__,
            env=env,
            retry_if_failed=retries,
        )
        self._fetchers = {}
        self._urls = {}
        self._load()

    def _fetcher(self, model_name, file_names) -> Callable:
        def _fetch_files():
            return [Path(self.pooch.fetch(fname)) for fname in file_names]

        def _fetch_zip(zip_name):
            with FileLock(f"{zip_name}.lock"):
                return [
                    Path(f)
                    for f in self.pooch.fetch(
                        zip_name, processor=pooch.Unzip(members=self.models[model_name])
                    )
                ]

        urls = [self.pooch.registry[fname] for fname in file_names]
        if not any(url for url in urls) or set(urls) == {
            f"{_DEFAULT_BASE_URL}/{_DEFAULT_ZIP_NAME}"
        }:
            fetch = partial(_fetch_zip, zip_name=_DEFAULT_ZIP_NAME)
        else:
            fetch = _fetch_files  # type: ignore
        fetch.__name__ = model_name  # type: ignore
        return fetch

    def _load(self):
        """
        Load registry data from cache.

        Raises an error if no cached registries are found.
        Run 'python -m modflow_devtools.models sync' to populate the cache.
        """
        # Try to load from cache
        loaded_from_cache = self._try_load_from_cache()

        if not loaded_from_cache:
            raise RuntimeError(
                "No model registries found in cache. "
                "Run 'python -m modflow_devtools.models sync' to download registries, "
                "or use ModelSourceConfig.load().sync() programmatically."
            )

    def _try_load_from_cache(self) -> bool:
        """
        Try to load registry from cache.

        Returns True if successful, False otherwise.
        """
        try:
            cached = _DEFAULT_CACHE.list()
            if not cached:
                return False

            # Merge all cached registries into Pydantic fields
            for source, ref in cached:
                registry = _DEFAULT_CACHE.load(source, ref)
                if registry:
                    # Merge files - create FileEntry with both url and cached path
                    for fname, file_entry in registry.files.items():
                        self.files[fname] = ModelInputFile(
                            url=file_entry.url,
                            path=self.pooch.path / fname,
                            hash=file_entry.hash,
                        )

                    # Merge models and examples
                    self.models.update(registry.models)
                    self.examples.update(registry.examples)

                    # Store metadata from first registry
                    if not self.schema_version and registry.schema_version:
                        self.schema_version = registry.schema_version
                        self.generated_at = registry.generated_at
                        self.devtools_version = registry.devtools_version

            if not self.files:
                return False

            # Configure Pooch
            self._urls = {name: entry.url for name, entry in self.files.items() if entry.url}
            self.pooch.registry = {name: entry.hash for name, entry in self.files.items()}
            self.pooch.urls = self._urls

            # Set up fetchers
            self._fetchers = {}
            for model_name, file_list in self.models.items():
                self._fetchers[model_name] = self._fetcher(model_name, file_list)

            return True

        except Exception:
            return False

    def index(
        self,
        path: str | PathLike,
        url: str,
        prefix: str = "",
        namefile: str = "mfsim.nam",
        output_path: str | PathLike | None = None,
    ):
        """
        Add models in the given path to the registry.
        Call this once or more to prepare a registry.

        This function is *not* idempotent. It should
        be called with different arguments each time.

        The `path` must be the root of, or a folder
        within, a local clone of the repository. The
        branch checked out must match the URL branch.

         The `path` may contain model subdirectories
        at arbitrary depth. Model input subdirectories
        are identified by the presence of a namefile
        matching the provided pattern. A prefix may be
        specified for model names to avoid collisions.

        The `url` must be a remote repository which
        contains models. The registry will be fixed
        to the state of the repository at the given
        URL at the current time.

        Parameters
        ----------
        path : str | PathLike
            Path to the directory containing the models.
        url : str
            Base URL for the models.
        prefix : str
            Prefix to add to model names.
        namefile : str
            Namefile pattern to look for in the model directories.
        output_path : str | PathLike | None
            Path to output directory. If None, uses default registry path.
        """
        path = Path(path).expanduser().resolve().absolute()
        if not path.is_dir():
            raise NotADirectoryError(f"Path {path} is not a directory.")

        # Determine output directory
        if output_path is not None:
            output_dir = Path(output_path).expanduser().resolve().absolute()
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = self._registry_path

        files: dict[str, dict[str, str | None]] = {}
        models: dict[str, list[str]] = {}
        examples: dict[str, list[str]] = {}
        is_zip = url.endswith((".zip", ".tar")) if url else False

        model_paths = get_model_paths(path, namefile=namefile)
        for model_path in model_paths:
            model_path = model_path.expanduser().resolve().absolute()
            rel_path = model_path.relative_to(path)
            parts = [prefix, *list(rel_path.parts)] if prefix else list(rel_path.parts)
            model_name = "/".join(parts)
            models[model_name] = []
            if is_zip:
                name = rel_path.parts[0]
                if name not in examples:
                    examples[name] = []
                examples[name].append(model_name)
            for p in model_path.rglob("*"):
                if not p.is_file() or _should_exclude_file(p):
                    continue
                relpath = p.expanduser().resolve().absolute().relative_to(path)
                name = "/".join(relpath.parts)

                # Compute hash (None for zip-based registries)
                hash = None if is_zip else _sha256(p)

                # For zip-based registries, all files share the zip URL
                # For version-controlled, construct per-file URL from base + path
                file_url = url if is_zip else f"{url}/{name}"
                files[name] = {"url": file_url, "hash": hash}
                models[model_name].append(name)

        for example_name in examples.keys():
            examples[example_name] = sorted(examples[example_name], key=_model_sort_key)

        registry_file = output_dir / "models.toml"

        # Read existing registry if it exists (to support multiple index() calls)
        existing_files = {}
        existing_models = {}
        existing_examples = {}
        if registry_file.exists():
            with registry_file.open("rb") as f:
                existing_data = tomli.load(f)
                existing_files = existing_data.get("files", {})
                existing_models = existing_data.get("models", {})
                existing_examples = existing_data.get("examples", {})

        # Merge with new data
        existing_files.update(files)
        existing_models.update(models)
        existing_examples.update(examples)

        registry_data = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "devtools_version": modflow_devtools.__version__,
            "files": remap(dict(sorted(existing_files.items())), visit=drop_none_or_empty),
            "models": dict(sorted(existing_models.items())),
            "examples": dict(sorted(existing_examples.items())),
        }

        with registry_file.open("wb") as f:
            tomli_w.dump(registry_data, f)

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy the model's input files to the given workspace.
        The workspace will be created if it does not exist.
        """

        if (fetch := self._fetchers.get(model_name, None)) is None:
            raise ValueError(f"Model '{model_name}' not in registry")
        if not any(files := fetch()):
            return None
        # create the workspace if needed
        workspace = Path(workspace).expanduser().resolve().absolute()
        if verbose:
            print(f"Creating workspace {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        # copy the files. some might be in nested folders,
        # but the first is guaranteed not to be, so use it
        # to determine relative path in the new workspace.
        base = Path(files[0]).parent
        for file in files:
            if verbose:
                print(f"Copying {file} to workspace")
            path = workspace / file.relative_to(base)
            path.parent.mkdir(parents=True, exist_ok=True)
            copy(file, workspace / file.relative_to(base))
        return workspace

    @property
    def pooch(self) -> Pooch:
        """The registry's Pooch instance."""
        return self._pooch

    @property
    def path(self) -> Path:
        return self.pooch.path


_DEFAULT_ENV = "MFMODELS_PATH"
_DEFAULT_BASE_URL = "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current"
_DEFAULT_ZIP_NAME = "mf6examples.zip"


def _try_best_effort_sync():
    """
    Attempt to sync registries on first import.

    This is a best-effort operation - if it fails (network issues,
    misconfiguration, etc.), we silently continue. The user will get
    a clear error message if they try to use the registry without
    having synced successfully.
    """
    global _SYNC_ATTEMPTED

    if _SYNC_ATTEMPTED:
        return

    _SYNC_ATTEMPTED = True

    try:
        # Try to sync default refs (don't be verbose, don't fail on errors)
        config = ModelSourceConfig.load()
        config.sync(verbose=False)
    except Exception:
        # Silently fail - user will get clear error when trying to use registry
        pass


# Try to sync on first import (unless disabled)
if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
    _try_best_effort_sync()

# Lazy initialization of default registry
_default_registry_cache = None


def get_default_registry():
    """
    Get or create the default model registry (lazy initialization).

    This allows the module to import successfully even if the cache
    is empty, with a clear error message on first use.

    Returns
    -------
    PoochRegistry
        The default model registry
    """
    global _default_registry_cache
    if _default_registry_cache is None:
        _default_registry_cache = PoochRegistry(base_url=_DEFAULT_BASE_URL, env=_DEFAULT_ENV)
    return _default_registry_cache


def get_examples() -> dict[str, list[str]]:
    """
    Get a map of example names to models in the example.
    """
    return get_default_registry().examples


def get_models() -> dict[str, list[str]]:
    """Get a map of model names to input files."""
    return get_default_registry().models


def get_files() -> dict[str, ModelInputFile]:
    """
    Get a map of file names to URLs. Note that this mapping
    contains no information on which files belong to which
    models. For that information, use `get_models()`.
    """
    return get_default_registry().files


def copy_to(workspace: str | PathLike, model_name: str, verbose: bool = False) -> Path | None:
    """
    Copy the model's input files to the given workspace.
    The workspace will be created if it does not exist.
    """
    return get_default_registry().copy_to(workspace, model_name, verbose=verbose)


def __getattr__(name: str):
    """
    Lazy module attribute access for backwards compatibility.

    Provides DEFAULT_REGISTRY as a lazily-initialized module attribute.
    """
    if name == "DEFAULT_REGISTRY":
        return get_default_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
