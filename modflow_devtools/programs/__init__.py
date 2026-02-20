import hashlib
import os
import shutil
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from os import PathLike
from pathlib import Path

import pooch
import requests  # type: ignore[import-untyped]
import tomli
import tomli_w
from filelock import FileLock
from pydantic import BaseModel, Field

# Experimental API warning
warnings.warn(
    "The modflow_devtools.programs API is experimental and may change or be "
    "removed in future versions without following normal deprecation procedures. "
    "Use at your own risk. To suppress this warning, use:\n"
    "  warnings.filterwarnings('ignore', "
    "message='.*modflow_devtools.programs.*experimental.*')",
    FutureWarning,
    stacklevel=2,
)

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


class ProgramDistribution(BaseModel):
    """Distribution-specific information."""

    name: str = Field(
        ..., description="Distribution name (e.g., linux, mac, macarm, win64, win64ext)"
    )
    asset: str = Field(..., description="Release asset filename")
    exe: str | None = Field(
        None, description="Executable path within archive (e.g., mf6.7.0_win64/bin/mf6.exe)"
    )
    hash: str | None = Field(None, description="SHA256 hash")

    model_config = {"arbitrary_types_allowed": True}


class ProgramMetadata(BaseModel):
    """Program metadata in registry."""

    description: str | None = Field(None, description="Program description")
    license: str | None = Field(None, description="License identifier")
    exe: str | None = Field(
        None,
        description="Executable path within archive (e.g., bin/mf6). Defaults to bin/{program}",
    )
    dists: list[ProgramDistribution] = Field(
        default_factory=list, description="Available distributions"
    )

    model_config = {"arbitrary_types_allowed": True}

    def get_exe_path(
        self,
        program_name: str,
        platform: str | None = None,
        asset_name: str | None = None,
        archive_path: Path | None = None,
    ) -> str:
        """
        Get executable path, using default if not specified.

        Parameters
        ----------
        program_name : str
            Name of the program
        platform : str | None
            Platform name (e.g., 'win64'). If Windows platform, adds .exe extension.
        asset_name : str | None
            Asset filename (e.g., 'mf6.6.3_linux.zip'). If provided and program-level exe is used,
            prepends the asset stem (filename without extension) to support nested folder structure.
        archive_path : Path | None
            Path to archive file. If provided and using defaults, will inspect archive to determine
            which default pattern to use (bin/{program} vs {program} at root).

        Returns
        -------
        str
            Executable path within archive
        """
        exe: str | None

        # Check distribution-specific exe path first
        if platform:
            for dist in self.dists:
                if dist.name == platform and dist.exe:
                    exe = dist.exe
                    # Add .exe extension for Windows platforms if not present
                    if platform.startswith("win") and exe and not exe.endswith(".exe"):
                        exe = f"{exe}.exe"
                    assert exe is not None  # Narrowing for mypy
                    return exe

        # If we have the archive, inspect it to determine the correct exe path
        # This handles both nested and flat archive structures
        if archive_path and asset_name:
            from pathlib import Path

            asset_stem = Path(asset_name).stem

            # Try to detect the exe location in the archive
            exe = self._detect_default_exe_in_archive(
                archive_path, asset_stem, program_name, platform
            )
            if exe:
                # Already has the correct path (with or without asset stem prefix)
                return exe

        # Fall back to program-level exe or defaults
        if self.exe:
            exe = self.exe
        else:
            # Default to bin/{program}
            exe = f"bin/{program_name}"

        # Add .exe extension for Windows platforms
        if platform and platform.startswith("win") and not exe.endswith(".exe"):
            exe = f"{exe}.exe"

        # If asset_name provided and we're using program-level exe,
        # prepend asset stem to support nested folder structure
        # (e.g., 'bin/mf6' becomes 'mf6.6.3_linux/bin/mf6' for mf6.6.3_linux.zip)
        if asset_name and not any(
            dist.name == platform and dist.exe for dist in self.dists if platform
        ):
            # Using program-level exe (not dist-specific)
            from pathlib import Path

            asset_stem = Path(asset_name).stem
            exe = f"{asset_stem}/{exe}"

        return exe

    def _detect_default_exe_in_archive(
        self,
        archive_path: Path,
        asset_stem: str,
        program_name: str,
        platform: str | None,
    ) -> str | None:
        """
        Inspect archive to detect which default exe pattern is used.

        Supports both nested ({asset_stem}/path) and flat (path) patterns.
        Returns the full path if found, None otherwise.
        """
        import tarfile
        import zipfile

        # Try to list archive contents
        try:
            if archive_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    members = zf.namelist()
            elif archive_path.suffix.lower() in [".gz", ".tgz"]:
                with tarfile.open(archive_path, "r:gz") as tf:
                    members = tf.getnames()
            elif archive_path.suffix.lower() == ".tar":
                with tarfile.open(archive_path, "r") as tf:
                    members = tf.getnames()
            else:
                return None

            # Normalize member paths
            members_normalized = [m.replace("\\", "/") for m in members]

            # Try common patterns in priority order
            # First try nested patterns (most common), then flat patterns
            for base_pattern in [f"bin/{program_name}", program_name]:
                for ext in ["", ".exe", ".dll", ".so", ".dylib"]:
                    search_pattern = f"{base_pattern}{ext}"

                    # Try nested pattern first (asset_stem/path)
                    nested_pattern = f"{asset_stem}/{search_pattern}"
                    if nested_pattern in members_normalized:
                        return nested_pattern

                    # Try flat pattern (no asset_stem prefix)
                    if search_pattern in members_normalized:
                        return search_pattern

            return None

        except (zipfile.BadZipFile, tarfile.TarError, OSError):
            return None


class ProgramRegistry(BaseModel):
    """Program registry data model."""

    schema_version: str | None = Field(None, description="Registry schema version")
    programs: dict[str, ProgramMetadata] = Field(
        default_factory=dict, description="Map of program names to metadata"
    )

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}


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
        self.archives_dir = self.root / "archives"
        self.binaries_dir = self.root / "binaries"
        self.metadata_dir = self.root / "metadata"

    def get_registry_cache_dir(self, source: str, ref: str) -> Path:
        """Get cache directory for a specific source/ref combination."""
        return self.registries_dir / source / ref

    def get_archive_dir(self, program: str, version: str, platform: str) -> Path:
        """Get cache directory for program archives."""
        return self.archives_dir / program / version / platform

    def get_binary_dir(self, program: str, version: str, platform: str) -> Path:
        """Get cache directory for extracted binaries."""
        return self.binaries_dir / program / version / platform

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
                if "generated_at" in data and isinstance(data["generated_at"], datetime):
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

        synced: list[tuple[str, str]] = field(default_factory=list)  # [(source, ref), ...]
        skipped: list[tuple[str, str]] = field(default_factory=list)  # [(ref, reason), ...]
        failed: list[tuple[str, str]] = field(default_factory=list)  # [(ref, error), ...]

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


# ============================================================================
# Installation System
# ============================================================================


class ProgramInstallationError(Exception):
    """Raised when program installation fails."""

    pass


def get_platform() -> str:
    """
    Detect current platform for binary selection.

    Returns
    -------
    str
        Platform identifier: 'linux', 'mac', or 'win64'

    Raises
    ------
    ProgramInstallationError
        If platform cannot be detected or is unsupported
    """
    import platform
    import sys

    system = platform.system().lower()

    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "mac"
    elif system == "windows":
        # Determine if 32-bit or 64-bit
        is_64bit = sys.maxsize > 2**32
        if is_64bit:
            return "win64"
        else:
            raise ProgramInstallationError(
                "32-bit Windows is not supported. "
                "Only 64-bit Windows (win64) binaries are available."
            )
    else:
        raise ProgramInstallationError(
            f"Unsupported platform: {system}. Supported platforms: linux, mac, win64"
        )


def _compute_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """
    Compute hash of a file.

    Parameters
    ----------
    file_path : Path
        Path to file
    algorithm : str
        Hash algorithm (default: sha256)

    Returns
    -------
    str
        Hex digest of file hash
    """

    hash_obj = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def _verify_hash(file_path: Path, expected_hash: str) -> bool:
    """
    Verify file hash against expected value.

    Parameters
    ----------
    file_path : Path
        Path to file
    expected_hash : str
        Expected hash in format "algorithm:hexdigest" (e.g., "sha256:abc123...")

    Returns
    -------
    bool
        True if hash matches, False otherwise

    Raises
    ------
    ValueError
        If hash format is invalid
    """
    if ":" not in expected_hash:
        raise ValueError(f"Invalid hash format: {expected_hash}. Expected 'algorithm:hexdigest'")

    algorithm, expected_digest = expected_hash.split(":", 1)
    actual_digest = _compute_file_hash(file_path, algorithm)
    return actual_digest.lower() == expected_digest.lower()


def download_archive(
    url: str,
    dest: Path,
    expected_hash: str | None = None,
    force: bool = False,
    verbose: bool = False,
) -> Path:
    """
    Download archive to cache.

    Parameters
    ----------
    url : str
        Download URL
    dest : Path
        Destination file path
    expected_hash : str, optional
        Expected hash in format "algorithm:hexdigest"
    force : bool
        Force re-download even if cached and hash matches
    verbose : bool
        Print progress messages

    Returns
    -------
    Path
        Path to downloaded file

    Raises
    ------
    ProgramInstallationError
        If download fails or hash verification fails
    """
    # Check if already cached
    if dest.exists() and not force:
        if expected_hash is None:
            if verbose:
                print(f"Using cached archive: {dest}")
            return dest

        # Verify hash of cached file
        if _verify_hash(dest, expected_hash):
            if verbose:
                print(f"Using cached archive (hash verified): {dest}")
            return dest
        else:
            if verbose:
                print(f"Cached archive hash mismatch, re-downloading: {dest}")

    # Create parent directory
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Download
    if verbose:
        print(f"Downloading: {url}")

    try:
        # Support GitHub token authentication
        headers = {}
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        # Write to temporary file first
        temp_dest = dest.with_suffix(dest.suffix + ".tmp")
        with temp_dest.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify hash if provided
        if expected_hash is not None:
            if verbose:
                print("Verifying hash...")
            if not _verify_hash(temp_dest, expected_hash):
                temp_dest.unlink()
                raise ProgramInstallationError(
                    f"Downloaded file hash does not match expected hash: {expected_hash}"
                )

        # Move to final location
        temp_dest.replace(dest)

        if verbose:
            print(f"Downloaded to: {dest}")

        return dest

    except requests.exceptions.RequestException as e:
        if dest.exists():
            dest.unlink()
        raise ProgramInstallationError(f"Failed to download {url}: {e}") from e


def extract_executables(
    archive: Path,
    dest_dir: Path,
    exe_path: str,
    verbose: bool = False,
) -> list[Path]:
    """
    Extract executable(s) from archive.

    Parameters
    ----------
    archive : Path
        Path to archive file
    dest_dir : Path
        Destination directory for extraction
    exe_path : str
        Path to executable within archive (e.g., "bin/mf6")
    verbose : bool
        Print progress messages

    Returns
    -------
    list[Path]
        List of extracted executable paths

    Raises
    ------
    ProgramInstallationError
        If extraction fails
    """
    import stat
    import tarfile
    import zipfile

    dest_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Extracting {archive.name} to {dest_dir}...")

    try:
        # Determine archive type and extract
        if archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive, "r") as zf:
                # Extract the entire archive to preserve directory structure
                zf.extractall(dest_dir)
        elif archive.suffix.lower() in [".gz", ".tgz"]:
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(dest_dir)
        elif archive.suffix.lower() == ".tar":
            with tarfile.open(archive, "r") as tf:
                tf.extractall(dest_dir)
        else:
            raise ProgramInstallationError(f"Unsupported archive format: {archive.suffix}")

        # Find the extracted executable
        exe_file = dest_dir / exe_path
        if not exe_file.exists():
            raise ProgramInstallationError(f"Executable not found in archive: {exe_path}")

        # Apply executable permissions on Unix
        if os.name != "nt":  # Unix-like systems
            current_permissions = exe_file.stat().st_mode
            exe_file.chmod(current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        if verbose:
            print(f"Extracted: {exe_file}")

        return [exe_file]

    except (zipfile.BadZipFile, tarfile.TarError) as e:
        raise ProgramInstallationError(f"Failed to extract {archive}: {e}") from e


def get_bindir_options(program: str | None = None) -> list[Path]:
    """
    Get writable installation directories in priority order.

    Adapted from flopy's get-modflow utility.

    Parameters
    ----------
    program : str, optional
        Program name to check for previous installation location

    Returns
    -------
    list[Path]
        List of writable directories in priority order
    """
    import sys
    from pathlib import Path

    candidates = []

    # 1. Previous installation location (if program specified)
    if program:
        metadata = InstallationMetadata(program)
        if metadata.load():
            installations = metadata.list_installations()
            if installations:
                # Use most recent installation bindir
                most_recent = max(installations, key=lambda i: i.installed_at)
                candidates.append(most_recent.bindir)

    # 2. Python's Scripts/bin directory
    if hasattr(sys, "base_prefix"):
        if os.name == "nt":
            candidates.append(Path(sys.base_prefix) / "Scripts")
        else:
            candidates.append(Path(sys.base_prefix) / "bin")

    # 3. User local bin
    if os.name == "nt":
        # Windows: %LOCALAPPDATA%\Microsoft\WindowsApps
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Microsoft" / "WindowsApps")
    else:
        # Unix: ~/.local/bin
        candidates.append(Path.home() / ".local" / "bin")

    # 4. System local bin (Unix only)
    if os.name != "nt":
        candidates.append(Path("/usr/local/bin"))

    # Filter to writable directories
    writable = []
    for path in candidates:
        if not path.exists():
            # Try to create it
            try:
                path.mkdir(parents=True, exist_ok=True)
                writable.append(path)
            except (OSError, PermissionError):
                continue
        else:
            # Check if writable
            if os.access(path, os.W_OK):
                writable.append(path)

    # Remove duplicates while preserving order
    seen = set()
    result = []
    for path in writable:
        if path not in seen:
            seen.add(path)
            result.append(path)

    return result


def get_bindir_shortcut_map(program: str | None = None) -> dict[str, tuple[Path, str]]:
    """
    Get map of installation directory shortcuts to (path, description) tuples.

    Adapted from flopy's get-modflow utility:
    https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py

    Parameters
    ----------
    program : str, optional
        Program name to check for previous installation location

    Returns
    -------
    dict[str, tuple[Path, str]]
        Map of shortcuts (e.g., ':prev', ':python') to (path, description) tuples.
        Only includes shortcuts for directories that exist and are writable.
    """
    import sys
    from pathlib import Path

    options: dict[str, tuple[Path, str]] = {}

    # 1. Previous installation location
    if program:
        metadata = InstallationMetadata(program)
        if metadata.load():
            installations = metadata.list_installations()
            if installations:
                most_recent = max(installations, key=lambda i: i.installed_at)
                prev_path = most_recent.bindir
                if prev_path.exists() and os.access(prev_path, os.W_OK):
                    options[":prev"] = (prev_path, "previously selected bindir")

    # 2. modflow-devtools dedicated directory
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            mfdt_path = Path(local_app_data) / "modflow-devtools" / "bin"
        else:
            mfdt_path = Path.home() / "AppData" / "Local" / "modflow-devtools" / "bin"
    else:
        # Unix: ~/.local/share/modflow-devtools/bin
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            mfdt_path = Path(xdg_data_home) / "modflow-devtools" / "bin"
        else:
            mfdt_path = Path.home() / ".local" / "share" / "modflow-devtools" / "bin"

    # Create if it doesn't exist
    try:
        mfdt_path.mkdir(parents=True, exist_ok=True)
        if os.access(mfdt_path, os.W_OK):
            options[":mf"] = (mfdt_path, "used by modflow-devtools")
    except (OSError, PermissionError):
        pass

    # 3. Python's Scripts/bin directory
    if hasattr(sys, "base_prefix"):
        py_bin = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
        if py_bin.is_dir() and os.access(py_bin, os.W_OK):
            options[":python"] = (py_bin, "used by Python")

    # 4. User local bin
    if os.name == "nt":
        # Windows: %LOCALAPPDATA%\Microsoft\WindowsApps
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            windowsapps_path = Path(local_app_data) / "Microsoft" / "WindowsApps"
            if windowsapps_path.is_dir() and os.access(windowsapps_path, os.W_OK):
                options[":windowsapps"] = (windowsapps_path, "user app path")
    else:
        # Unix: ~/.local/bin
        home_local_bin = Path.home() / ".local" / "bin"
        if home_local_bin.is_dir() and os.access(home_local_bin, os.W_OK):
            options[":home"] = (home_local_bin, "user-specific bindir")

    # 5. System local bin (Unix only)
    if os.name != "nt":
        local_bin = Path("/usr") / "local" / "bin"
        if local_bin.is_dir() and os.access(local_bin, os.W_OK):
            options[":system"] = (local_bin, "system local bindir")

    if not options:
        raise ProgramInstallationError("No writable installation directories found")

    return options


def select_bindir(
    bindir_arg: str,
    program: str | None = None,
) -> Path:
    """
    Parse and resolve bindir argument with support for ':' prefix shortcuts.

    Adapted from flopy's get-modflow utility:
    https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py

    Supports:
    - ':' alone for interactive selection
    - ':prev' for previous installation directory
    - ':mf' for dedicated modflow-devtools directory
    - ':python' for Python's Scripts/bin directory
    - ':home' for ~/.local/bin (Unix) or :windowsapps (Windows)
    - ':system' for /usr/local/bin (Unix only)
    - ':windowsapps' for %LOCALAPPDATA%\\Microsoft\\WindowsApps (Windows only)

    Parameters
    ----------
    bindir_arg : str
        The bindir argument, which may start with ':'
    program : str, optional
        Program name (for :prev lookup)

    Returns
    -------
    Path
        Resolved installation directory path

    Raises
    ------
    ProgramInstallationError
        If shortcut is invalid or selection fails
    """
    # Get available options
    options = get_bindir_shortcut_map(program)

    # Interactive selection (bare ':')
    if bindir_arg == ":":
        # Build numbered menu
        indexed_options = dict(enumerate(options.keys(), 1))

        print("Select a number to choose installation directory:")
        for idx, shortcut in indexed_options.items():
            opt_path, opt_info = options[shortcut]
            print(f"  {idx}: '{opt_path}' -- {opt_info} ('{shortcut}')")

        # Get user input
        max_tries = 3
        for attempt in range(max_tries):
            try:
                res = input("> ")
                choice_idx = int(res)
                if choice_idx not in indexed_options:
                    raise ValueError("Invalid option number")

                selected_shortcut = indexed_options[choice_idx]
                selected_path = options[selected_shortcut][0]
                return selected_path.resolve()

            except (ValueError, KeyError):
                if attempt < max_tries - 1:
                    print("Invalid option, try again")
                else:
                    raise ProgramInstallationError("Invalid option selected, too many attempts")

    # Auto-select mode (e.g., ':python', ':prev')
    else:
        # Find matching shortcuts (support prefix matching)
        bindir_lower = bindir_arg.lower()
        matches = [opt for opt in options if opt.startswith(bindir_lower)]

        if len(matches) == 0:
            available = ", ".join(options.keys())
            raise ProgramInstallationError(
                f"Invalid bindir shortcut '{bindir_arg}'. Available: {available}"
            )
        elif len(matches) > 1:
            raise ProgramInstallationError(
                f"Ambiguous bindir shortcut '{bindir_arg}'. Matches: {', '.join(matches)}"
            )

        # Exactly one match
        selected_path = options[matches[0]][0]
        return selected_path.resolve()

    # This should never be reached but needed for type checking
    raise ProgramInstallationError("Failed to select bindir")


@dataclass
class ProgramInstallation:
    """Represents a program installation."""

    version: str
    """Program version"""

    platform: str
    """Platform identifier"""

    bindir: Path
    """Installation directory"""

    installed_at: datetime
    """Installation timestamp"""

    source: dict[str, str]
    """Source information (repo, tag, asset_url, hash)"""

    executables: list[str]
    """List of installed executable names"""


class InstallationMetadata:
    """Manages installation metadata for a program."""

    def __init__(self, program: str):
        """
        Initialize metadata manager.

        Parameters
        ----------
        program : str
            Program name
        """
        self.program = program
        self.metadata_file = _DEFAULT_CACHE.metadata_dir / f"{program}.json"
        self.installations: list[ProgramInstallation] = []

    def load(self) -> bool:
        """
        Load metadata from file.

        Returns
        -------
        bool
            True if metadata was loaded, False if file doesn't exist
        """
        if not self.metadata_file.exists():
            return False

        try:
            import json

            with self.metadata_file.open("r") as f:
                data = json.load(f)

            self.installations = []
            for inst_data in data.get("installations", []):
                # Parse datetime
                installed_at = datetime.fromisoformat(inst_data["installed_at"])

                # Convert bindir to Path
                bindir = Path(inst_data["bindir"])

                installation = ProgramInstallation(
                    version=inst_data["version"],
                    platform=inst_data["platform"],
                    bindir=bindir,
                    installed_at=installed_at,
                    source=inst_data["source"],
                    executables=inst_data["executables"],
                )
                self.installations.append(installation)

            return True

        except (json.JSONDecodeError, KeyError, ValueError):
            # Corrupted metadata, start fresh
            self.installations = []
            return False

    def save(self) -> None:
        """Save metadata to file."""
        import json

        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "program": self.program,
            "installations": [
                {
                    "version": inst.version,
                    "platform": inst.platform,
                    "bindir": str(inst.bindir),
                    "installed_at": inst.installed_at.isoformat(),
                    "source": inst.source,
                    "executables": inst.executables,
                }
                for inst in self.installations
            ],
        }

        with self.metadata_file.open("w") as f:
            json.dump(data, f, indent=2)

    def add_installation(self, installation: ProgramInstallation) -> None:
        """
        Add or update an installation.

        Parameters
        ----------
        installation : ProgramInstallation
            Installation to add
        """
        # Remove existing installation for same version/bindir if present
        self.installations = [
            inst
            for inst in self.installations
            if not (inst.version == installation.version and inst.bindir == installation.bindir)
        ]

        self.installations.append(installation)
        self.save()

    def remove_installation(self, version: str, bindir: Path) -> None:
        """
        Remove an installation.

        Parameters
        ----------
        version : str
            Program version
        bindir : Path
            Installation directory
        """
        self.installations = [
            inst
            for inst in self.installations
            if not (inst.version == version and inst.bindir == bindir)
        ]
        self.save()

    def list_installations(self) -> list[ProgramInstallation]:
        """
        List all installations.

        Returns
        -------
        list[ProgramInstallation]
            List of installations
        """
        return self.installations.copy()


class ProgramManager:
    """High-level program installation manager."""

    def __init__(self, cache: ProgramCache | None = None):
        """
        Initialize program manager.

        Parameters
        ----------
        cache : ProgramCache, optional
            Cache instance (default: use global cache)
        """
        self.cache = cache if cache is not None else _DEFAULT_CACHE
        self._config: ProgramSourceConfig | None = None

    @property
    def config(self) -> ProgramSourceConfig:
        """Lazily load configuration."""
        if self._config is None:
            self._config = ProgramSourceConfig.load()
        return self._config

    def install(
        self,
        program: str,
        version: str | None = None,
        bindir: str | Path | None = None,
        platform: str | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> list[Path]:
        """
        Install a program binary.

        Parameters
        ----------
        program : str
            Program name
        version : str, optional
            Program version (default: latest configured version)
        bindir : str | Path, optional
            Installation directory (default: auto-select)
        platform : str, optional
            Platform identifier (default: auto-detect)
        force : bool
            Force reinstallation even if already installed
        verbose : bool
            Print progress messages

        Returns
        -------
        list[Path]
            List of installed executable paths

        Raises
        ------
        ProgramInstallationError
            If installation fails
        """
        import shutil
        from datetime import timezone

        # 1. Load config and find program in registries
        config = self.config

        # Search all cached registries for the program
        found_registry: ProgramRegistry | None = None
        found_ref: str | None = None
        found_source: ProgramSourceRepo | None = None

        for source_name, source in config.sources.items():
            for ref in source.refs:
                registry = self.cache.load(source_name, ref)
                if registry and program in registry.programs:
                    # If version specified, check if it matches the ref (release tag)
                    if version is None or ref == version:
                        found_registry = registry
                        found_ref = ref
                        found_source = source
                        break
            if found_registry:
                break

        if not found_registry:
            # Try to sync and search again
            if verbose:
                print(f"Program '{program}' not found in cache, attempting sync...")
            try:
                config.sync(verbose=verbose)

                # Search again
                for source_name, source in config.sources.items():
                    for ref in source.refs:
                        registry = self.cache.load(source_name, ref)
                        if registry and program in registry.programs:
                            # If version specified, check if it matches the ref (release tag)
                            if version is None or ref == version:
                                found_registry = registry
                                found_ref = ref
                                found_source = source
                                break
                    if found_registry:
                        break
            except Exception as e:
                if verbose:
                    print(f"Sync failed: {e}")

        if not found_registry:
            raise ProgramInstallationError(
                f"Program '{program}' not found in any configured registry"
            )

        # 2. Get program metadata
        program_meta = found_registry.programs[program]
        assert found_source is not None  # Guaranteed by found_registry check above
        assert found_ref is not None  # Guaranteed by found_registry check above
        version = found_ref  # Use release tag as version

        if verbose:
            print(f"Installing {program} version {version}...")

        # 3. Detect platform
        if platform is None:
            platform = get_platform()
            if verbose:
                print(f"Detected platform: {platform}")

        # 4. Get distribution metadata
        dist_meta = None
        for dist in program_meta.dists:
            if dist.name == platform:
                dist_meta = dist
                break

        if dist_meta is None:
            available = ", ".join(d.name for d in program_meta.dists)
            raise ProgramInstallationError(
                f"Distribution not available for platform '{platform}'. Available: {available}"
            )

        # 5. Determine bindir
        if bindir is None:
            bindir_options = get_bindir_options(program)
            if not bindir_options:
                raise ProgramInstallationError("No writable installation directories found")
            bindir = bindir_options[0]  # Use first (highest priority)
            if verbose:
                print(f"Selected installation directory: {bindir}")
        else:
            bindir = Path(bindir)
            bindir.mkdir(parents=True, exist_ok=True)

        # 6. Check if already installed
        metadata = InstallationMetadata(program)
        metadata.load()

        # 7. Download archive (if not cached)
        asset_url = f"https://github.com/{found_source.repo}/releases/download/{found_ref}/{dist_meta.asset}"
        archive_dir = self.cache.get_archive_dir(program, version, platform)
        archive_path = archive_dir / dist_meta.asset

        if verbose:
            print(f"Downloading archive from {asset_url}...")

        download_archive(
            url=asset_url,
            dest=archive_path,
            expected_hash=dist_meta.hash,
            force=force,
            verbose=verbose,
        )

        # Get exe path (may inspect archive to detect defaults)
        exe_path = program_meta.get_exe_path(program, platform, dist_meta.asset, archive_path)

        # 8. Extract to binaries cache (if not already extracted)
        binary_dir = self.cache.get_binary_dir(program, version, platform)
        exe_in_cache = binary_dir / exe_path

        if not exe_in_cache.exists() or force:
            if verbose:
                print(f"Extracting to cache: {binary_dir}")

            extract_executables(
                archive=archive_path,
                dest_dir=binary_dir,
                exe_path=exe_path,
                verbose=verbose,
            )

        # 9. Copy executables to bindir
        exe_name = Path(
            exe_path
        ).name  # exe_path already set above with platform-specific extension
        dest_exe = bindir / exe_name

        if verbose:
            print(f"Installing to {dest_exe}...")

        shutil.copy2(exe_in_cache, dest_exe)

        # Apply executable permissions on Unix
        if os.name != "nt":
            import stat

            current_permissions = dest_exe.stat().st_mode
            dest_exe.chmod(current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # 10. Update metadata
        assert found_ref is not None  # Guaranteed by found_registry check above
        source_info: dict[str, str] = {
            "repo": found_source.repo,
            "tag": found_ref,
            "asset_url": asset_url,
            "hash": dist_meta.hash or "",
        }
        installation = ProgramInstallation(
            version=version,
            platform=platform,
            bindir=bindir,
            installed_at=datetime.now(timezone.utc),
            source=source_info,
            executables=[exe_name],
        )

        metadata.add_installation(installation)

        if verbose:
            print(f"Successfully installed {program} {version} to {bindir}")

        # 11. Return installed executable paths
        return [dest_exe]

    def uninstall(
        self,
        program: str,
        version: str | None = None,
        bindir: str | Path | None = None,
        all_versions: bool = False,
        remove_cache: bool = False,
        verbose: bool = False,
    ) -> None:
        """
        Uninstall program executable(s).

        Parameters
        ----------
        program : str
            Program name
        version : str, optional
            Program version (required unless all_versions=True)
        bindir : str | Path, optional
            Installation directory (default: all installations)
        all_versions : bool
            Uninstall all versions from all bindirs
        remove_cache : bool
            Also remove from binaries/archives cache
        verbose : bool
            Print progress messages

        Raises
        ------
        ProgramInstallationError
            If uninstallation fails
        """
        # Load metadata
        metadata = InstallationMetadata(program)
        if not metadata.load():
            if verbose:
                print(f"No installation metadata found for {program}")
            return

        # Determine what to uninstall
        if all_versions:
            to_uninstall = metadata.list_installations()
        else:
            if version is None:
                raise ValueError("Must specify version or use all_versions=True")

            to_uninstall = []
            for inst in metadata.list_installations():
                if inst.version == version:
                    if bindir is None or inst.bindir == Path(bindir):
                        to_uninstall.append(inst)

        if not to_uninstall:
            if verbose:
                print("No installations found to uninstall")
            return

        # Uninstall each
        for inst in to_uninstall:
            if verbose:
                print(f"Uninstalling {program} {inst.version} from {inst.bindir}...")

            # Remove executables from bindir
            for exe_name in inst.executables:
                exe_path = inst.bindir / exe_name
                if exe_path.exists():
                    exe_path.unlink()
                    if verbose:
                        print(f"  Removed {exe_path}")

            # Remove from metadata
            metadata.remove_installation(inst.version, inst.bindir)

        # Optionally remove from cache
        if remove_cache:
            if verbose:
                print(f"Removing {program} from cache...")

            # Remove archives
            archives_base = self.cache.archives_dir / program
            if archives_base.exists():
                import shutil

                shutil.rmtree(archives_base)

            # Remove binaries
            binaries_base = self.cache.binaries_dir / program
            if binaries_base.exists():
                import shutil

                shutil.rmtree(binaries_base)

        if verbose:
            print(f"Successfully uninstalled {program}")

    def list_installed(self, program: str | None = None) -> dict[str, list[ProgramInstallation]]:
        """
        List installed programs.

        Parameters
        ----------
        program : str, optional
            Specific program to list (default: all programs)

        Returns
        -------
        dict[str, list[ProgramInstallation]]
            Map of program names to installations
        """
        result: dict[str, list[ProgramInstallation]] = {}

        # Find all metadata files
        metadata_dir = self.cache.metadata_dir
        if not metadata_dir.exists():
            return result

        for metadata_file in metadata_dir.glob("*.json"):
            program_name = metadata_file.stem

            # Filter if specific program requested
            if program and program_name != program:
                continue

            metadata = InstallationMetadata(program_name)
            if metadata.load():
                installations = metadata.list_installations()
                if installations:
                    result[program_name] = installations

        return result


# ============================================================================
# Default Manager and Convenience Functions
# ============================================================================

_DEFAULT_MANAGER = ProgramManager()
"""Default program manager instance"""


def install_program(
    program: str,
    version: str | None = None,
    bindir: str | Path | None = None,
    platform: str | None = None,
    force: bool = False,
    verbose: bool = False,
) -> list[Path]:
    """
    Install a program binary.

    Convenience wrapper for ProgramManager.install().

    Parameters
    ----------
    program : str
        Program name
    version : str, optional
        Program version (default: latest configured version)
    bindir : str | Path, optional
        Installation directory (default: auto-select)
    platform : str, optional
        Platform identifier (default: auto-detect)
    force : bool
        Force reinstallation even if already installed
    verbose : bool
        Print progress messages

    Returns
    -------
    list[Path]
        List of installed executable paths

    Raises
    ------
    ProgramInstallationError
        If installation fails
    """
    return _DEFAULT_MANAGER.install(
        program=program,
        version=version,
        bindir=bindir,
        platform=platform,
        force=force,
        verbose=verbose,
    )


def uninstall_program(
    program: str,
    version: str | None = None,
    bindir: str | Path | None = None,
    all_versions: bool = False,
    remove_cache: bool = False,
    verbose: bool = False,
) -> None:
    """
    Uninstall program executable(s).

    Convenience wrapper for ProgramManager.uninstall().

    Parameters
    ----------
    program : str
        Program name
    version : str, optional
        Program version (required unless all_versions=True)
    bindir : str | Path, optional
        Installation directory (default: all installations)
    all_versions : bool
        Uninstall all versions from all bindirs
    remove_cache : bool
        Also remove from binaries/archives cache
    verbose : bool
        Print progress messages

    Raises
    ------
    ProgramInstallationError
        If uninstallation fails
    """
    return _DEFAULT_MANAGER.uninstall(
        program=program,
        version=version,
        bindir=bindir,
        all_versions=all_versions,
        remove_cache=remove_cache,
        verbose=verbose,
    )


def list_installed(program: str | None = None) -> dict[str, list[ProgramInstallation]]:
    """
    List installed programs.

    Convenience wrapper for ProgramManager.list_installed().

    Parameters
    ----------
    program : str, optional
        Specific program to list (default: all programs)

    Returns
    -------
    dict[str, list[ProgramInstallation]]
        Map of program names to installations
    """
    return _DEFAULT_MANAGER.list_installed(program=program)


def _try_best_effort_sync():
    """
    Attempt to sync registries (best-effort, fails silently).

    Called by consumer commands before accessing program registries.
    """
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


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "_DEFAULT_CACHE",
    "_DEFAULT_MANAGER",
    "DiscoveredProgramRegistry",
    "InstallationMetadata",
    "ProgramCache",
    "ProgramDistribution",
    "ProgramInstallation",
    "ProgramInstallationError",
    "ProgramManager",
    "ProgramMetadata",
    "ProgramRegistry",
    "ProgramRegistryDiscoveryError",
    "ProgramSourceConfig",
    "ProgramSourceRepo",
    "_try_best_effort_sync",
    "download_archive",
    "extract_executables",
    "get_bindir_options",
    "get_bindir_shortcut_map",
    "get_platform",
    "get_user_config_path",
    "install_program",
    "list_installed",
    "select_bindir",
    "uninstall_program",
]
