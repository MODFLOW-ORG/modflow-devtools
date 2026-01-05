"""
Registry discovery logic.

This module implements the following registry discovery procedure:
1. Look for a matching release tag (registry as release asset)
2. Fall back to version-controlled registry (in .registry/ directory)
"""

import os
import urllib.request
from pathlib import Path
from typing import Literal

import tomli

from .schema import Bootstrap, BootstrapSource, Registry


class RegistryDiscoveryError(Exception):
    """Raised when registry discovery fails."""

    pass


RegistryMode = Literal["release_asset", "version_controlled"]


class DiscoveredRegistry:
    """Result of registry discovery."""

    def __init__(
        self,
        registry: Registry,
        mode: RegistryMode,
        source: str,
        ref: str,
        url: str,
    ):
        self.registry = registry
        self.mode = mode
        self.source = source
        self.ref = ref
        self.url = url

    def __repr__(self) -> str:
        return (
            f"DiscoveredRegistry(source={self.source}, "
            f"ref={self.ref}, mode={self.mode})"
        )


def discover_registry(
    source: BootstrapSource,
    ref: str,
) -> DiscoveredRegistry:
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
    org, repo_name = source.repo.split("/")
    registry_path = source.registry_path

    # Step 1: Try release assets
    release_url = (
        f"https://github.com/{org}/{repo_name}/releases/download/{ref}/registry.toml"
    )
    try:
        registry_data = _fetch_url(release_url)
        registry = Registry(**tomli.loads(registry_data))
        return DiscoveredRegistry(
            registry=registry,
            mode="release_asset",
            source=source.name,
            ref=ref,
            url=release_url,
        )
    except urllib.error.HTTPError as e:
        if e.code != 404:
            # Some other error - re-raise
            raise RegistryDiscoveryError(
                f"Error fetching registry from release "
                f"assets for '{source.name}@{ref}': {e}"
            )
        # 404 means no release with this tag, fall through to version-controlled

    # Step 2: Try version-controlled registry
    vc_url = f"https://raw.githubusercontent.com/{org}/{repo_name}/{ref}/{registry_path}/registry.toml"
    try:
        registry_data = _fetch_url(vc_url)
        registry = Registry(**tomli.loads(registry_data))
        return DiscoveredRegistry(
            registry=registry,
            mode="version_controlled",
            source=source.name,
            ref=ref,
            url=vc_url,
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RegistryDiscoveryError(
                f"Registry file 'registry.toml' not found "
                f"in {registry_path} for '{source.name}@{ref}'"
            )
        else:
            raise RegistryDiscoveryError(
                "Error fetching registry from repository "
                f"for '{source.name}@{ref}': {e}"
            )
    except Exception as e:
        raise RegistryDiscoveryError(
            f"Registry discovery failed for '{source.name}@{ref}': {e}"
        )


def _fetch_url(url: str, timeout: int = 30) -> str:
    """
    Fetch content from a URL.

    Parameters
    ----------
    url : str
        URL to fetch
    timeout : int
        Timeout in seconds

    Returns
    -------
    str
        Content as string

    Raises
    ------
    urllib.error.HTTPError
        If HTTP request fails
    """
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def get_user_config_path() -> Path:
    """
    Get the path to the user bootstrap configuration file.

    Returns the platform-appropriate user config location:
    - Linux/macOS: $XDG_CONFIG_HOME/modflow-devtools/bootstrap.toml
                   (defaults to ~/.config/modflow-devtools/bootstrap.toml)
    - Windows: %APPDATA%/modflow-devtools/bootstrap.toml

    Returns
    -------
    Path
        Path to user bootstrap config file
    """
    if os.name == "nt":  # Windows
        config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:  # Unix-like (Linux, macOS, etc.)
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    return config_dir / "modflow-devtools" / "bootstrap.toml"


def merge_bootstrap(bundled: Bootstrap, user: Bootstrap) -> Bootstrap:
    """
    Merge user bootstrap config with bundled config.

    User sources override/extend bundled sources. If a source exists in both
    configs, the user version takes precedence completely (no field-level merging).

    Parameters
    ----------
    bundled : Bootstrap
        The bundled bootstrap config
    user : Bootstrap
        The user bootstrap config

    Returns
    -------
    Bootstrap
        Merged bootstrap config with user sources taking precedence
    """
    # Start with bundled sources
    merged_sources = bundled.sources.copy()

    # Override/extend with user sources
    merged_sources.update(user.sources)

    return Bootstrap(sources=merged_sources)


def load_bootstrap(
    bootstrap_path: Path | str | None = None,
    user_config_path: Path | str | None = None,
) -> Bootstrap:
    """
    Load the bootstrap file, with optional user config overlay.

    When bootstrap_path is None (default), loads the bundled bootstrap file
    and merges it with user config if present. User config is loaded from:
    - Linux/macOS: ~/.config/modflow-devtools/bootstrap.toml
    - Windows: %APPDATA%/modflow-devtools/bootstrap.toml

    When an explicit bootstrap_path is provided, only that file is loaded
    (no user config overlay unless user_config_path is also provided).

    Parameters
    ----------
    bootstrap_path : Path | str | None
        Path to bootstrap file. If None, uses default bundled location
        and applies user config overlay if present.
    user_config_path : Path | str | None
        Path to user config file for overlay. If None and bootstrap_path is None,
        uses default user config location. If provided, uses this specific path
        for user config overlay.

    Returns
    -------
    Bootstrap
        Parsed bootstrap metadata (merged with user config if applicable)

    Raises
    ------
    FileNotFoundError
        If bootstrap file doesn't exist
    """
    # Determine if we should apply user config overlay
    # Apply if: (1) using default bootstrap and user config exists, OR
    #           (2) explicit user_config_path provided
    apply_user_config = bootstrap_path is None or user_config_path is not None

    if bootstrap_path is None:
        # Default location - bundled bootstrap
        bootstrap_path = Path(__file__).parent / "bootstrap.toml"
    else:
        bootstrap_path = Path(bootstrap_path)

    if not bootstrap_path.exists():
        raise FileNotFoundError(f"Bootstrap file not found: {bootstrap_path}")

    # Load the primary bootstrap file
    with bootstrap_path.open("rb") as f:
        data = tomli.load(f)

    # Inject source keys as names if not explicitly provided
    if "sources" in data:
        for key, source_data in data["sources"].items():
            if "name" not in source_data:
                source_data["name"] = key

    bundled = Bootstrap(**data)

    # If applying user config overlay, load and merge
    if apply_user_config:
        # Determine user config path
        if user_config_path is None:
            user_config_path = get_user_config_path()
        else:
            user_config_path = Path(user_config_path)

        # Load and merge if exists
        if user_config_path.exists():
            with user_config_path.open("rb") as f:
                user_data = tomli.load(f)

            # Inject source keys as names if not explicitly provided
            if "sources" in user_data:
                for key, source_data in user_data["sources"].items():
                    if "name" not in source_data:
                        source_data["name"] = key

            user = Bootstrap(**user_data)
            return merge_bootstrap(bundled, user)

    return bundled
