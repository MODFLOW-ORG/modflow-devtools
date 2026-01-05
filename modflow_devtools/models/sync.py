"""
Registry synchronization functionality.
"""

from pathlib import Path

from .cache import cache_registry, is_registry_cached, list_cached_registries
from .discovery import RegistryDiscoveryError, discover_registry, load_bootstrap


class SyncResult:
    """Result of a sync operation."""

    def __init__(self):
        self.synced: list[tuple[str, str]] = []  # (source, ref) pairs
        self.skipped: list[tuple[str, str, str]] = []  # (source, ref, reason)
        self.failed: list[tuple[str, str, str]] = []  # (source, ref, error)

    def __repr__(self) -> str:
        return (
            f"SyncResult(synced={len(self.synced)}, "
            f"skipped={len(self.skipped)}, "
            f"failed={len(self.failed)})"
        )


def sync_registry(
    source: str | None = None,
    ref: str | None = None,
    repo: str | None = None,
    force: bool = False,
    verbose: bool = False,
    bootstrap_path: Path | str | None = None,
) -> SyncResult:
    """
    Synchronize registry files from remote repositories.

    Parameters
    ----------
    source : str | None
        Specific source to sync. If None, syncs all sources from bootstrap.
    ref : str | None
        Specific ref to sync. If None, syncs all refs from bootstrap for the source(s).
    repo : str | None
        Repository in "owner/name" format to override the bootstrap's repo.
        Useful for testing forks. Requires 'source' to be specified.
    force : bool
        Force re-download even if cached
    verbose : bool
        Print progress messages
    bootstrap_path : Path | str | None
        Path to bootstrap file (uses default if None)

    Returns
    -------
    SyncResult
        Results of the sync operation

    Examples
    --------
    Sync all sources, all default refs:
        sync_registry()

    Sync specific source, all refs:
        sync_registry(source="modflow6-testmodels")

    Sync specific source and ref:
        sync_registry(source="modflow6-testmodels", ref="develop")

    Force re-sync:
        sync_registry(force=True)

    Test against a fork:
        sync_registry(
            source="modflow6-testmodels",
            ref="registry",
            repo="wpbonelli/modflow6-testmodels"
        )
    """
    # Validate: repo override requires source to be specified
    if repo and not source:
        raise ValueError("Cannot specify 'repo' without specifying 'source'")

    result = SyncResult()
    bootstrap = load_bootstrap(bootstrap_path)

    # Determine which sources to sync
    if source:
        if source not in bootstrap.sources:
            raise ValueError(f"Source '{source}' not found in bootstrap")
        source_meta = bootstrap.sources[source]

        # Override repo if provided
        if repo:
            source_meta = source_meta.model_copy(update={"repo": repo})

        sources_to_sync = {source: source_meta}
    else:
        sources_to_sync = bootstrap.sources

    # Sync each source/ref combination
    for source_key, source_meta in sources_to_sync.items():
        source_name = source_meta.name

        # Determine which refs to sync
        if ref:
            refs_to_sync = [ref]
        else:
            refs_to_sync = source_meta.refs if source_meta.refs else []

        if not refs_to_sync:
            if verbose:
                print(f"No refs configured for source '{source_key}', skipping")
            continue

        for ref_name in refs_to_sync:
            # Check if already cached
            if not force and is_registry_cached(source_name, ref_name):
                if verbose:
                    print(f"Registry {source_name}@{ref_name} already cached, skipping")
                result.skipped.append((source_name, ref_name, "already cached"))
                continue

            # Discover and cache
            try:
                if verbose:
                    print(f"Discovering registry {source_name}@{ref_name}...")

                discovered = discover_registry(
                    source=source_meta,
                    ref=ref_name,
                )

                if verbose:
                    print(f"  Found via {discovered.mode} at {discovered.url}")
                    print("  Caching...")

                cache_registry(discovered.registry, source_name, ref_name)

                if verbose:
                    print(f"  ✓ Synced {source_name}@{ref_name}")

                result.synced.append((source_name, ref_name))

            except RegistryDiscoveryError as e:
                if verbose:
                    print(f"  ✗ Failed to sync {source_name}@{ref_name}: {e}")
                result.failed.append((source_name, ref_name, str(e)))
            except Exception as e:
                if verbose:
                    print(f"  ✗ Unexpected error syncing {source_name}@{ref_name}: {e}")
                result.failed.append((source_name, ref_name, str(e)))

    return result


def get_sync_status(bootstrap_path: Path | str | None = None) -> dict:
    """
    Get sync status for all configured sources.

    Parameters
    ----------
    bootstrap_path : Path | str | None
        Path to bootstrap file (uses default if None)

    Returns
    -------
    dict
        Dictionary mapping source names to sync status info
    """
    bootstrap = load_bootstrap(bootstrap_path)
    cached_registries = set(list_cached_registries())

    status = {}
    for source_key, source_meta in bootstrap.sources.items():
        source_name = source_meta.name
        refs = source_meta.refs if source_meta.refs else []

        cached_refs: list[str] = []
        missing_refs: list[str] = []

        source_status = {
            "repo": source_meta.repo,
            "configured_refs": refs,
            "cached_refs": cached_refs,
            "missing_refs": missing_refs,
        }

        for ref_name in refs:
            if (source_name, ref_name) in cached_registries:
                cached_refs.append(ref_name)
            else:
                missing_refs.append(ref_name)

        status[source_name] = source_status

    return status
