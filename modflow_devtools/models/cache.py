"""
Registry and model file caching utilities.

This module provides caching functionality, leveraging Pooch where possible.
"""

from pathlib import Path

import pooch
import tomli_w

from .schema import Registry


def get_cache_root() -> Path:
    """
    Get the root cache directory for modflow-devtools.

    Uses Pooch's os_cache() for platform-appropriate location:
    - Linux: ~/.cache/modflow-devtools
    - macOS: ~/Library/Caches/modflow-devtools
    - Windows: ~\\AppData\\Local\\modflow-devtools\\Cache

    Returns
    -------
    Path
        Path to cache root directory
    """
    return Path(pooch.os_cache("modflow-devtools"))


def get_registry_cache_dir(source: str, ref: str) -> Path:
    """
    Get the cache directory for a specific source and ref.

    Parameters
    ----------
    source : str
        Source name (e.g., 'modflow6-testmodels' or 'mf6/test').
        May contain slashes which will create nested directories.
    ref : str
        Git ref (branch, tag, or commit hash)

    Returns
    -------
    Path
        Path to registry cache directory for this source/ref
    """
    return get_cache_root() / "registries" / source / ref


def get_models_cache_dir() -> Path:
    """
    Get the cache directory for model files (managed by Pooch).

    Returns
    -------
    Path
        Path to models cache directory
    """
    return get_cache_root() / "models"


def cache_registry(registry: Registry, source: str, ref: str) -> Path:
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
    cache_dir = get_registry_cache_dir(source, ref)
    cache_dir.mkdir(parents=True, exist_ok=True)

    registry_file = cache_dir / "registry.toml"

    # Convert registry to dict for TOML serialization
    # Use mode='json' to ensure datetime and Path objects are serialized to strings
    registry_dict = registry.model_dump(mode="json", by_alias=True, exclude_none=True)

    with registry_file.open("wb") as f:
        tomli_w.dump(registry_dict, f)

    return registry_file


def load_cached_registry(source: str, ref: str) -> Registry | None:
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
    registry_file = get_registry_cache_dir(source, ref) / "registry.toml"

    if not registry_file.exists():
        return None

    with registry_file.open("rb") as f:
        import tomli

        data = tomli.load(f)

    return Registry(**data)


def is_registry_cached(source: str, ref: str) -> bool:
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
    registry_file = get_registry_cache_dir(source, ref) / "registry.toml"
    return registry_file.exists()


def clear_registry_cache(source: str | None = None, ref: str | None = None) -> None:
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
        cache_dir = get_registry_cache_dir(source, ref)
        if cache_dir.exists():
            _rmtree_with_retry(cache_dir)
    elif source:
        # Clear all refs for a source
        source_dir = get_cache_root() / "registries" / source
        if source_dir.exists():
            _rmtree_with_retry(source_dir)
    else:
        # Clear all registries
        registries_dir = get_cache_root() / "registries"
        if registries_dir.exists():
            _rmtree_with_retry(registries_dir)


def list_cached_registries() -> list[tuple[str, str]]:
    """
    List all cached registries.

    Returns
    -------
    list[tuple[str, str]]
        List of (source, ref) tuples for cached registries
    """
    registries_dir = get_cache_root() / "registries"

    if not registries_dir.exists():
        return []

    cached = []
    # Find all registry.toml files recursively to support nested source names
    for registry_file in registries_dir.rglob("registry.toml"):
        # Extract source and ref from path
        # e.g., registries/mf6/test/registry/registry.toml
        # → parts = ['mf6', 'test', 'registry', 'registry.toml']
        parts = registry_file.relative_to(registries_dir).parts
        if len(parts) >= 2:
            ref = parts[-2]  # 'registry' (second-to-last)
            source = "/".join(parts[:-2])  # 'mf6/test' (everything before ref)
            cached.append((source, ref))

    return cached
