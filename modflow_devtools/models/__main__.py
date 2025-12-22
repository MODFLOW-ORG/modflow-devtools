"""
CLI for modflow-devtools models functionality.

Usage:
    python -m modflow_devtools.models sync
    python -m modflow_devtools.models info
    python -m modflow_devtools.models list
"""

import argparse
import sys

from .cache import list_cached_registries, load_cached_registry
from .sync import get_sync_status, sync_registry


def cmd_sync(args):
    """Sync command handler."""
    result = sync_registry(
        source=args.source,
        ref=args.ref,
        force=args.force,
        verbose=True,
    )

    print(f"\nSync complete:")
    print(f"  Synced: {len(result.synced)}")
    print(f"  Skipped: {len(result.skipped)}")
    print(f"  Failed: {len(result.failed)}")

    if result.failed:
        print("\nFailed syncs:")
        for source, ref, error in result.failed:
            print(f"  {source}@{ref}: {error}")
        sys.exit(1)


def cmd_info(args):
    """Info command handler."""
    status = get_sync_status()

    print("Registry sync status:\n")
    for source_name, source_status in status.items():
        print(f"{source_name} ({source_status['repo']})")
        print(f"  Configured refs: {', '.join(source_status['configured_refs']) or 'none'}")
        print(f"  Cached refs: {', '.join(source_status['cached_refs']) or 'none'}")
        if source_status['missing_refs']:
            print(f"  Missing refs: {', '.join(source_status['missing_refs'])}")
        print()


def cmd_list(args):
    """List command handler."""
    cached = list_cached_registries()

    if not cached:
        print("No cached registries. Run 'sync' first.")
        return

    print("Available models:\n")
    for source, ref in sorted(cached):
        registry = load_cached_registry(source, ref)
        if registry:
            print(f"{source}@{ref}:")
            models = registry.models
            if models:
                print(f"  Models: {len(models)}")
                if args.verbose:
                    for model_name in sorted(models.keys())[:10]:  # Show first 10
                        print(f"    - {model_name}")
                    if len(models) > 10:
                        print(f"    ... and {len(models) - 10} more")
            else:
                print("  No models")

            examples = registry.examples
            if examples:
                print(f"  Examples: {len(examples)}")
                if args.verbose:
                    for example_name in sorted(examples.keys())[:5]:  # Show first 5
                        print(f"    - {example_name}")
                    if len(examples) > 5:
                        print(f"    ... and {len(examples) - 5} more")
            print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m modflow_devtools.models",
        description="MODFLOW model registry management",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Synchronize registries")
    sync_parser.add_argument(
        "--source",
        "-s",
        help="Specific source to sync (default: all sources)",
    )
    sync_parser.add_argument(
        "--ref",
        "-r",
        help="Specific ref to sync (default: all configured refs)",
    )
    sync_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if cached",
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Show registry sync status")

    # List command
    list_parser = subparsers.add_parser("list", help="List available models")
    list_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show model names",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "sync":
            cmd_sync(args)
        elif args.command == "info":
            cmd_info(args)
        elif args.command == "list":
            cmd_list(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
