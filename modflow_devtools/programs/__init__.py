"""
Programs API - Dynamic program registry and installation management.

This module provides utilities for discovering, synchronizing, and managing
MODFLOW-related programs. It follows the same design patterns as the Models API
with a consolidated object-oriented implementation.

Key classes:
    - ProgramCache: Manages local caching of registries
    - ProgramSourceRepo: Represents a program source repository
    - ProgramSourceConfig: Configuration container from bootstrap file
    - ProgramRegistry: Pydantic model for registry structure
    - DiscoveredProgramRegistry: Discovery result with metadata

Example usage:
    >>> from modflow_devtools.programs import ProgramSourceConfig
    >>> config = ProgramSourceConfig.load()
    >>> source = config.sources["modflow6"]
    >>> result = source.sync(ref="6.6.3", verbose=True)
    >>> # Use _DEFAULT_CACHE to access cached registries
"""

import hashlib
import platform as pl
import shutil
from collections.abc import Callable
import os
from dataclasses import dataclass, field
from datetime import datetime
from os import PathLike
from pathlib import Path

import pooch
import requests  # type: ignore[import-untyped]
import tomli
import tomli_w
from filelock import FileLock
from pydantic import BaseModel, Field, field_serializer

_CACHE_ROOT = Path(pooch.os_cache("modflow-devtools"))
"""Root cache directory (platform-appropriate location via Pooch)"""

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "programs.toml"
"""Path to bundled bootstrap configuration"""


def get_user_config_path() -> Path | None:
    """
    Get the platform-appropriate user config file path.

    Returns
    -------
    Path | None
        Path to user config file, or None if default location not writable
    """
    import os
    import platform

    system = platform.system()
    if system == "Windows":
        base = Path.home() / "AppData" / "Roaming"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Linux/Unix - respect XDG_CONFIG_HOME
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"

    config_dir = base / "modflow-devtools"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "programs.toml"


class ProgramRegistryDiscoveryError(Exception):
    """Raised when program registry discovery fails."""

    pass


class ProgramBinary(BaseModel):
    """Platform-specific binary information."""

    asset: str = Field(..., description="Release asset filename")
    hash: str | None = Field(None, description="SHA256 hash")
    exe: str = Field(..., description="Executable path within archive")

    model_config = {"arbitrary_types_allowed": True}


class ProgramMetadata(BaseModel):
    """Program metadata in registry."""

    version: str = Field(..., description="Program version")
    description: str | None = Field(None, description="Program description")
    repo: str = Field(..., description="Source repository (owner/name)")
    license: str | None = Field(None, description="License identifier")
    binaries: dict[str, ProgramBinary] = Field(
        default_factory=dict, description="Platform-specific binaries (linux/mac/win64)"
    )

    model_config = {"arbitrary_types_allowed": True}


class ProgramRegistry(BaseModel):
    """Program registry data model."""

    schema_version: str | None = Field(None, description="Registry schema version")
    generated_at: datetime | None = Field(None, description="Generation timestamp")
    devtools_version: str | None = Field(None, description="modflow-devtools version")
    programs: dict[str, ProgramMetadata] = Field(
        default_factory=dict, description="Map of program names to metadata"
    )

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    @field_serializer("generated_at")
    def serialize_datetime(self, dt: datetime | None, _info):
        """Serialize datetime to ISO format."""
        return dt.isoformat() if dt is not None else None


@dataclass
class DiscoveredProgramRegistry:
    """Result of program registry discovery."""

    source: str
    """Source name"""

    ref: str
    """Git ref (release tag)"""

    url: str
    """URL where registry was discovered"""

    registry: ProgramRegistry
    """Parsed registry"""


class ProgramCache:
    """Manages local caching of program registries."""

    def __init__(self, root: Path | None = None):
        """
        Initialize cache manager.

        Parameters
        ----------
        root : Path, optional
            Cache root directory. If None, uses platform-appropriate default.
        """
        self.root = root if root is not None else _CACHE_ROOT / "programs"
        self.registries_dir = self.root / "registries"

    def get_registry_cache_dir(self, source: str, ref: str) -> Path:
        """Get cache directory for a specific source/ref combination."""
        return self.registries_dir / source / ref

    def save(self, registry: ProgramRegistry, source: str, ref: str) -> Path:
        """
        Save registry to cache.

        Parameters
        ----------
        registry : ProgramRegistry
            Registry to save
        source : str
            Source name
        ref : str
            Git ref

        Returns
        -------
        Path
            Path to saved registry file
        """
        cache_dir = self.get_registry_cache_dir(source, ref)
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = cache_dir / "programs.toml"
        lock_file = cache_dir / ".lock"

        with FileLock(str(lock_file)):
            with cache_file.open("wb") as f:
                data = registry.model_dump(mode="python", exclude_none=True)
                # Convert datetime to ISO string if present
                if "generated_at" in data and isinstance(
                    data["generated_at"], datetime
                ):
                    data["generated_at"] = data["generated_at"].isoformat()
                tomli_w.dump(data, f)

        return cache_file

    def load(self, source: str, ref: str) -> ProgramRegistry | None:
        """
        Load registry from cache.

        Parameters
        ----------
        source : str
            Source name
        ref : str
            Git ref

        Returns
        -------
        ProgramRegistry | None
            Cached registry, or None if not found
        """
        cache_file = self.get_registry_cache_dir(source, ref) / "programs.toml"
        if not cache_file.exists():
            return None

        with cache_file.open("rb") as f:
            data = tomli.load(f)
            return ProgramRegistry(**data)

    def has(self, source: str, ref: str) -> bool:
        """Check if registry is cached."""
        cache_file = self.get_registry_cache_dir(source, ref) / "programs.toml"
        return cache_file.exists()

    def list(self) -> list[tuple[str, str]]:
        """
        List all cached registries.

        Returns
        -------
        list[tuple[str, str]]
            List of (source, ref) tuples
        """
        if not self.registries_dir.exists():
            return []

        cached = []
        for source_dir in self.registries_dir.iterdir():
            if not source_dir.is_dir():
                continue
            for ref_dir in source_dir.iterdir():
                if not ref_dir.is_dir():
                    continue
                registry_file = ref_dir / "programs.toml"
                if registry_file.exists():
                    cached.append((source_dir.name, ref_dir.name))

        return cached

    def clear(self):
        """Clear all cached registries."""
        if self.registries_dir.exists():
            shutil.rmtree(self.registries_dir)


_DEFAULT_CACHE = ProgramCache()
"""Default program cache instance"""


class ProgramSourceRepo(BaseModel):
    """A single program source repository."""

    repo: str = Field(..., description="Repository (owner/name)")
    name: str | None = Field(None, description="Source name override")
    refs: list[str] = Field(default_factory=list, description="Release tags to sync")

    model_config = {"arbitrary_types_allowed": True}

    @dataclass
    class SyncResult:
        """Result of a sync operation."""

        synced: list[tuple[str, str]] = field(
            default_factory=list
        )  # [(source, ref), ...]
        skipped: list[tuple[str, str]] = field(
            default_factory=list
        )  # [(ref, reason), ...]
        failed: list[tuple[str, str]] = field(
            default_factory=list
        )  # [(ref, error), ...]

    @dataclass
    class SyncStatus:
        """Sync status for a source."""

        repo: str
        configured_refs: list[str]
        cached_refs: list[str]
        missing_refs: list[str]

    def discover(self, ref: str) -> DiscoveredProgramRegistry:
        """
        Discover program registry for a specific ref.

        Parameters
        ----------
        ref : str
            Release tag

        Returns
        -------
        DiscoveredProgramRegistry
            Discovered registry with metadata

        Raises
        ------
        ProgramRegistryDiscoveryError
            If registry discovery fails
        """
        # Programs API only supports release asset mode
        url = f"https://github.com/{self.repo}/releases/download/{ref}/programs.toml"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ProgramRegistryDiscoveryError(f"Failed to fetch registry from {url}: {e}") from e

        try:
            data = tomli.loads(response.text)
            registry = ProgramRegistry(**data)
        except Exception as e:
            raise ProgramRegistryDiscoveryError(f"Failed to parse registry from {url}: {e}") from e

        return DiscoveredProgramRegistry(
            source=self.name or self.repo.split("/")[1],
            ref=ref,
            url=url,
            registry=registry,
        )

    def sync(
        self,
        ref: str | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> "ProgramSourceRepo.SyncResult":
        """
        Sync program registry to local cache.

        Parameters
        ----------
        ref : str, optional
            Specific ref to sync. If None, syncs all configured refs.
        force : bool
            Force re-download even if cached
        verbose : bool
            Print progress messages

        Returns
        -------
        SyncResult
            Results of sync operation
        """
        source_name = self.name or self.repo.split("/")[1]
        refs = [ref] if ref else self.refs

        if not refs:
            if verbose:
                print(f"No refs configured for source '{source_name}', aborting")
            return ProgramSourceRepo.SyncResult()

        result = ProgramSourceRepo.SyncResult()

        for ref in refs:
            # Check if already cached
            if not force and _DEFAULT_CACHE.has(source_name, ref):
                if verbose:
                    print(f"  [-] Skipping {source_name}@{ref} (already cached)")
                result.skipped.append((ref, "already cached"))
                continue

            try:
                if verbose:
                    print(f"Discovering registry {source_name}@{ref}...")

                discovered = self.discover(ref=ref)
                if verbose:
                    print(f"  Caching registry from {discovered.url}...")

                _DEFAULT_CACHE.save(discovered.registry, source_name, ref)
                if verbose:
                    print(f"  [+] Synced {source_name}@{ref}")

                result.synced.append((source_name, ref))

            except ProgramRegistryDiscoveryError as e:
                print(f"  [-] Failed to sync {source_name}@{ref}: {e}")
                result.failed.append((ref, str(e)))
            except Exception as e:
                print(f"  [-] Unexpected error syncing {source_name}@{ref}: {e}")
                result.failed.append((ref, str(e)))

        return result

    def is_synced(self, ref: str) -> bool:
        """Check if a specific ref is synced."""
        source_name = self.name or self.repo.split("/")[1]
        return _DEFAULT_CACHE.has(source_name, ref)

    def list_synced_refs(self) -> list[str]:
        """List all synced refs for this source."""
        source_name = self.name or self.repo.split("/")[1]
        cached = _DEFAULT_CACHE.list()
        return [ref for source, ref in cached if source == source_name]


class ProgramSourceConfig(BaseModel):
    """Configuration for program sources."""

    sources: dict[str, ProgramSourceRepo] = Field(
        default_factory=dict, description="Map of source names to source configs"
    )

    model_config = {"arbitrary_types_allowed": True}

    @property
    def status(self) -> dict[str, ProgramSourceRepo.SyncStatus]:
        """Get sync status for all sources."""
        cached_registries = set(_DEFAULT_CACHE.list())

        status = {}
        for source in self.sources.values():
            name = source.name or source.repo.split("/")[1]
            refs = source.refs if source.refs else []

            cached: list[str] = []
            missing: list[str] = []

            for ref in refs:
                if (name, ref) in cached_registries:
                    cached.append(ref)
                else:
                    missing.append(ref)

            status[name] = ProgramSourceRepo.SyncStatus(
                repo=source.repo,
                configured_refs=refs,
                cached_refs=cached,
                missing_refs=missing,
            )

        return status

    def sync(
        self,
        source: str | ProgramSourceRepo | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> dict[str, ProgramSourceRepo.SyncResult]:
        """
        Sync registries to cache.

        Parameters
        ----------
        source : str | ProgramSourceRepo | None
            Specific source to sync. If None, syncs all sources.
        force : bool
            Force re-download even if cached
        verbose : bool
            Print progress messages

        Returns
        -------
        dict[str, SyncResult]
            Map of source names to sync results
        """
        if source:
            if isinstance(source, ProgramSourceRepo):
                if (source.name or source.repo.split("/")[1]) not in [
                    s.name or s.repo.split("/")[1] for s in self.sources.values()
                ]:
                    raise ValueError("Source not found in bootstrap")
                sources = [source]
            elif isinstance(source, str):
                if (src := self.sources.get(source, None)) is None:
                    raise ValueError(f"Source '{source}' not found in bootstrap")
                sources = [src]
        else:
            sources = list(self.sources.values())

        return {
            (src.name or src.repo.split("/")[1]): src.sync(force=force, verbose=verbose)
            for src in sources
        }

    @classmethod
    def load(
        cls,
        bootstrap_path: str | PathLike | None = None,
        user_config_path: str | PathLike | None = None,
    ) -> "ProgramSourceConfig":
        """
        Load program source configuration.

        Parameters
        ----------
        bootstrap_path : str | PathLike | None
            Path to bootstrap config. If None, uses bundled default.
        user_config_path : str | PathLike | None
            Path to user config overlay. If None and bootstrap_path is None,
            attempts to load from default user config location.

        Returns
        -------
        ProgramSourceConfig
            Loaded configuration
        """
        # Load base config
        if bootstrap_path is not None:
            with Path(bootstrap_path).open("rb") as f:
                cfg = tomli.load(f)
        else:
            with _DEFAULT_CONFIG_PATH.open("rb") as f:
                cfg = tomli.load(f)

            # Try user config if no explicit bootstrap
            if user_config_path is None:
                user_config_path = get_user_config_path()

        # Overlay user config
        if user_config_path is not None:
            user_path = Path(user_config_path)
            if user_path.exists():
                with user_path.open("rb") as f:
                    user_cfg = tomli.load(f)
                    if "sources" in user_cfg:
                        if "sources" not in cfg:
                            cfg["sources"] = {}
                        cfg["sources"] = cfg["sources"] | user_cfg["sources"]

        # Inject source names
        for name, src in cfg.get("sources", {}).items():
            if "name" not in src:
                src["name"] = name

        return cls(**cfg)

    @classmethod
    def merge(
        cls, base: "ProgramSourceConfig", overlay: "ProgramSourceConfig"
    ) -> "ProgramSourceConfig":
        """Merge two configurations."""
        merged_sources = base.sources.copy()
        merged_sources.update(overlay.sources)
        return cls(sources=merged_sources)


def _try_best_effort_sync():
    """Attempt to sync registries on first import (best-effort, fails silently)."""
    global _SYNC_ATTEMPTED

    if _SYNC_ATTEMPTED:
        return

    _SYNC_ATTEMPTED = True

    try:
        config = ProgramSourceConfig.load()
        config.sync(verbose=False)
    except Exception:
        # Silently fail - user will get error when trying to use registry
        pass


_SYNC_ATTEMPTED = False
"""Track whether auto-sync has been attempted"""

# Attempt best-effort sync on import (unless disabled)
if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
    _try_best_effort_sync()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "_DEFAULT_CACHE",
    "DiscoveredProgramRegistry",
    "ProgramBinary",
    "ProgramCache",
    "ProgramMetadata",
    "ProgramRegistry",
    "ProgramRegistryDiscoveryError",
    "ProgramSourceConfig",
    "ProgramSourceRepo",
    "get_user_config_path",
]
