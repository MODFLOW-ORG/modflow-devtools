"""
Command-line interface for the Programs API.

Commands:
    sync    Synchronize program registries
    info    Show sync status
    list    List available programs
"""

import argparse
import sys

from . import (
    _DEFAULT_CACHE,
    ProgramSourceConfig,
)


def cmd_sync(args):
    """Sync command handler."""
    config = ProgramSourceConfig.load()

    if args.source:
        # Sync specific source
        results = config.sync(source=args.source, force=args.force, verbose=True)
    else:
        # Sync all sources
        results = config.sync(force=args.force, verbose=True)

    # Print summary
    print("\nSync summary:")
    for source_name, result in results.items():
        print(f"\n{source_name}:")
        if result.synced:
            print(f"  Synced: {len(result.synced)} refs")
        if result.skipped:
            print(f"  Skipped: {len(result.skipped)} refs")
        if result.failed:
            print(f"  Failed: {len(result.failed)} refs")


def cmd_info(args):
    """Info command handler."""
    config = ProgramSourceConfig.load()
    status = config.status

    print("Program registry sync status:\n")
    for source_name, source_status in status.items():
        print(f"{source_name} ({source_status.repo})")
        configured_refs = ", ".join(source_status.configured_refs) or "none"
        print(f"  Configured refs: {configured_refs}")
        cached_refs = ", ".join(source_status.cached_refs) or "none"
        print(f"  Cached refs: {cached_refs}")
        if source_status.missing_refs:
            missing_refs = ", ".join(source_status.missing_refs)
            print(f"  Missing refs: {missing_refs}")
        print()


def cmd_list(args):
    """List command handler."""
    cached = _DEFAULT_CACHE.list()

    if not cached:
        print("No cached program registries. Run 'sync' first.")
        return

    # Apply filters
    if args.source or args.ref:
        filtered = []
        for source, ref in cached:
            if args.source and source != args.source:
                continue
            if args.ref and ref != args.ref:
                continue
            filtered.append((source, ref))
        cached = filtered

    if not cached:
        filter_desc = []
        if args.source:
            filter_desc.append(f"source={args.source}")
        if args.ref:
            filter_desc.append(f"ref={args.ref}")
        print(f"No cached registries matching filters: {', '.join(filter_desc)}")
        return

    print("Available programs:\n")
    for source, ref in sorted(cached):
        registry = _DEFAULT_CACHE.load(source, ref)
        if registry:
            print(f"{source}@{ref}:")
            programs = registry.programs
            if programs:
                print(f"  Programs: {len(programs)}")
                if args.verbose:
                    # Show all programs in verbose mode
                    for program_name, metadata in sorted(programs.items()):
                        version = metadata.version
                        platforms = (
                            ", ".join(metadata.binaries.keys()) if metadata.binaries else "none"
                        )
                        print(f"    - {program_name} ({version}) [{platforms}]")
            else:
                print("  No programs")
            print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m modflow_devtools.programs",
        description="Manage MODFLOW program registries",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Synchronize program registries")
    sync_parser.add_argument(
        "--source",
        help="Specific source to sync (default: all sources)",
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if cached",
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Show sync status")

    # List command
    list_parser = subparsers.add_parser("list", help="List available programs")
    list_parser.add_argument(
        "--source",
        help="Filter by source name",
    )
    list_parser.add_argument(
        "--ref",
        help="Filter by ref (release tag)",
    )
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed program information",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handler
    if args.command == "sync":
        cmd_sync(args)
    elif args.command == "info":
        cmd_info(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
