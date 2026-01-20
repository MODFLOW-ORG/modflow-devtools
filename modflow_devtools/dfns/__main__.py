"""
Command-line interface for the DFNs API.

Usage:
    python -m modflow_devtools.dfns sync [--ref REF] [--force]
    python -m modflow_devtools.dfns info
    python -m modflow_devtools.dfns list [--ref REF]
    python -m modflow_devtools.dfns clean [--all]
"""

from __future__ import annotations

import argparse
import shutil
import sys

from modflow_devtools.dfns.registry import (
    DfnRegistryDiscoveryError,
    DfnRegistryNotFoundError,
    get_bootstrap_config,
    get_cache_dir,
    get_registry,
    get_sync_status,
    sync_dfns,
)


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync DFN registries from remote sources."""
    source = args.source
    ref = args.ref
    force = args.force

    try:
        if ref:
            print(f"Syncing {source}@{ref}...")
            registries = sync_dfns(source=source, ref=ref, force=force)
        else:
            print(f"Syncing all configured refs for {source}...")
            registries = sync_dfns(source=source, force=force)

        for registry in registries:
            meta = registry.registry_meta
            print(f"  {registry.ref}: {len(meta.files)} files")

        print(f"Synced {len(registries)} registry(ies)")
        return 0

    except DfnRegistryNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except DfnRegistryDiscoveryError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def cmd_info(args: argparse.Namespace) -> int:
    """Show sync status and cache information."""
    source = args.source

    try:
        config = get_bootstrap_config()

        if source not in config.sources:
            print(f"Unknown source: {source}", file=sys.stderr)
            print(f"Available sources: {list(config.sources.keys())}", file=sys.stderr)
            return 1

        source_config = config.sources[source]
        print(f"Source: {source}")
        print(f"  Repository: {source_config.repo}")
        print(f"  DFN path: {source_config.dfn_path}")
        print(f"  Registry path: {source_config.registry_path}")
        print()

        # Show sync status
        status = get_sync_status(source=source)
        print("Configured refs:")
        for ref, synced in status.items():
            status_str = "synced" if synced else "not synced"
            print(f"  {ref}: {status_str}")
        print()

        # Show cache info
        cache_dir = get_cache_dir("dfn")
        if cache_dir.exists():
            # Count cached files
            registries_dir = cache_dir / "registries" / source
            files_dir = cache_dir / "files" / source

            registry_count = 0
            file_count = 0
            total_size = 0

            if registries_dir.exists():
                for p in registries_dir.rglob("*"):
                    if p.is_file():
                        registry_count += 1
                        total_size += p.stat().st_size

            if files_dir.exists():
                for p in files_dir.rglob("*"):
                    if p.is_file():
                        file_count += 1
                        total_size += p.stat().st_size

            print(f"Cache directory: {cache_dir}")
            print(f"  Registries: {registry_count}")
            print(f"  DFN files: {file_count}")
            print(f"  Total size: {_format_size(total_size)}")
        else:
            print("Cache directory: (not created)")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List available components."""
    source = args.source
    ref = args.ref

    try:
        registry = get_registry(source=source, ref=ref, auto_sync=True)
        components = list(registry.spec.keys())

        print(f"Components in {source}@{ref} ({len(components)} total):")
        for component in sorted(components):
            print(f"  {component}")

        return 0

    except DfnRegistryNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Try running 'python -m modflow_devtools.dfn sync' first.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_clean(args: argparse.Namespace) -> int:
    """Clean the cache directory."""
    source = args.source
    clean_all = args.all

    cache_dir = get_cache_dir("dfn")

    if not cache_dir.exists():
        print("Cache directory does not exist.")
        return 0

    if clean_all:
        # Clean entire cache
        print(f"Removing entire cache directory: {cache_dir}")
        shutil.rmtree(cache_dir)
        print("Cache cleaned.")
    else:
        # Clean only the specified source
        registries_dir = cache_dir / "registries" / source
        files_dir = cache_dir / "files" / source

        removed = False
        if registries_dir.exists():
            print(f"Removing registries for {source}: {registries_dir}")
            shutil.rmtree(registries_dir)
            removed = True

        if files_dir.exists():
            print(f"Removing files for {source}: {files_dir}")
            shutil.rmtree(files_dir)
            removed = True

        if removed:
            print(f"Cache cleaned for {source}.")
        else:
            print(f"No cache found for {source}.")

    return 0


def _format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable string."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m modflow_devtools.dfn",
        description="MODFLOW 6 definition file tools",
    )
    parser.add_argument(
        "--source",
        "-s",
        default="modflow6",
        help="Source repository name (default: modflow6)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # sync command
    sync_parser = subparsers.add_parser("sync", help="Sync DFN registries from remote")
    sync_parser.add_argument(
        "--ref",
        "-r",
        help="Specific ref to sync (default: all configured refs)",
    )
    sync_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-sync even if already cached",
    )

    # info command
    subparsers.add_parser("info", help="Show sync status and cache info")

    # list command
    list_parser = subparsers.add_parser("list", help="List available components")
    list_parser.add_argument(
        "--ref",
        "-r",
        default="develop",
        help="Git ref to list components from (default: develop)",
    )

    # clean command
    clean_parser = subparsers.add_parser("clean", help="Clean the cache")
    clean_parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Clean entire cache, not just the specified source",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "sync":
        return cmd_sync(args)
    elif args.command == "info":
        return cmd_info(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "clean":
        return cmd_clean(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
