"""
Registry discovery logic.

This module implements the following registry discovery procedure:
1. Look for a matching release tag (registry as release asset)
2. Fall back to version-controlled registry (in .registry/ directory)
"""

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
    source_name: str,
    ref: str,
    registry_path: str = ".registry",
) -> DiscoveredRegistry:
    """
    Discover a registry for the given source and ref.

    Implements the discovery procedure:
    1. Look for a matching release tag (registry as release asset)
    2. Fall back to version-controlled registry (in .registry/ directory)

    Parameters
    ----------
    source : BootstrapSource
        Source metadata from bootstrap file
    source_name : str
        Name of the source (for addressing models)
    ref : str
        Git ref (tag, branch, or commit hash)
    registry_path : str
        Path to registry directory in repository (default: .registry)

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
            source=source_name,
            ref=ref,
            url=release_url,
        )
    except urllib.error.HTTPError as e:
        if e.code != 404:
            # Some other error - re-raise
            raise RegistryDiscoveryError(
                f"Error fetching registry from release "
                f"assets for '{source_name}@{ref}': {e}"
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
            source=source_name,
            ref=ref,
            url=vc_url,
        )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RegistryDiscoveryError(
                f"Registry file 'registry.toml' not found "
                f"in {registry_path} for '{source_name}@{ref}'"
            )
        else:
            raise RegistryDiscoveryError(
                "Error fetching registry from repository "
                f"for '{source_name}@{ref}': {e}"
            )
    except Exception as e:
        raise RegistryDiscoveryError(
            f"Registry discovery failed for '{source_name}@{ref}': {e}"
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


def load_bootstrap(bootstrap_path: Path | str | None = None) -> Bootstrap:
    """
    Load the bootstrap file.

    Parameters
    ----------
    bootstrap_path : Path | str | None
        Path to bootstrap file. If None, uses default location.

    Returns
    -------
    Bootstrap
        Parsed bootstrap metadata

    Raises
    ------
    FileNotFoundError
        If bootstrap file doesn't exist
    """
    if bootstrap_path is None:
        # Default location
        bootstrap_path = Path(__file__).parent / "bootstrap.toml"
    else:
        bootstrap_path = Path(bootstrap_path)

    if not bootstrap_path.exists():
        raise FileNotFoundError(f"Bootstrap file not found: {bootstrap_path}")

    with bootstrap_path.open("rb") as f:
        data = tomli.load(f)

    return Bootstrap(**data)
