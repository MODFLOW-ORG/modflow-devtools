"""
CLI for modflow-devtools models functionality.

Usage:
    python -m modflow_devtools.models sync
    python -m modflow_devtools.models info
    python -m modflow_devtools.models list
"""

import argparse
import sys

from . import (
    _DEFAULT_CACHE,
    ModelSourceConfig,
    sync_registry,
)


def cmd_sync(args):
    """Sync command handler."""
    result = sync_registry(
        source=args.source,
        ref=args.ref,
        repo=getattr(args, "repo", None),
        force=args.force,
        verbose=True,
    )

    print("\nSync complete:")
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
    config = ModelSourceConfig.load()
    status = config.status

    print("Registry sync status:\n")
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
        print("No cached registries. Run 'sync' first.")
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

    print("Available models:\n")
    for source, ref in sorted(cached):
        registry = _DEFAULT_CACHE.load(source, ref)
        if registry:
            print(f"{source}@{ref}:")
            models = registry.models
            if models:
                print(f"  Models: {len(models)}")
                if args.verbose:
                    # Show all models in verbose mode
                    for model_name in sorted(models.keys()):
                        print(f"    - {model_name}")
            else:
                print("  No models")

            examples = registry.examples
            if examples:
                print(f"  Examples: {len(examples)}")
                if args.verbose:
                    # Show all examples in verbose mode
                    for example_name in sorted(examples.keys()):
                        print(f"    - {example_name}")
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
        "--repo",
        help='Override repository in "owner/name" format. Requires --source.',
    )
    sync_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if cached",
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Show registry sync status")  # noqa: F841

    # List command
    list_parser = subparsers.add_parser("list", help="List available models")
    list_parser.add_argument(
        "--source",
        "-s",
        help="Filter by specific source",
    )
    list_parser.add_argument(
        "--ref",
        "-r",
        help="Filter by specific ref",
    )
    list_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all model names (not truncated)",
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
