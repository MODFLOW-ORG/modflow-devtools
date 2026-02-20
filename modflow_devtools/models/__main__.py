"""
CLI for modflow-devtools models functionality.

Usage:
    python -m modflow_devtools.models sync
    python -m modflow_devtools.models info
    python -m modflow_devtools.models list
    python -m modflow_devtools.models clear
"""

import argparse
import os
import shutil
import sys

from . import (
    _DEFAULT_CACHE,
    ModelSourceConfig,
    _try_best_effort_sync,
)


def _format_grid(items, prefix=""):
    """Format items in a grid layout."""
    if not items:
        return

    term_width = shutil.get_terminal_size().columns
    # Account for prefix indentation
    available_width = term_width - len(prefix)

    # Calculate column width - find longest item
    max_item_len = max(len(str(item)) for item in items)
    col_width = min(max_item_len + 2, available_width)

    # Calculate number of columns
    num_cols = max(1, available_width // col_width)

    # Print items in grid
    for i in range(0, len(items), num_cols):
        row_items = items[i : i + num_cols]
        line = prefix + "  ".join(str(item).ljust(col_width) for item in row_items)
        print(line.rstrip())


def cmd_sync(args):
    """Sync command handler."""
    config = ModelSourceConfig.load()

    # If a specific source is provided, sync just that source
    if args.source:
        # Look up source by key or by name field
        source_obj = None
        if args.source in config.sources:
            source_obj = config.sources[args.source]
        else:
            # Try to find by name field
            for src in config.sources.values():
                if src.name == args.source:
                    source_obj = src
                    break

        if source_obj is None:
            # If --repo is provided, create an ad-hoc source
            if args.repo:
                from . import ModelSourceRepo

                source_obj = ModelSourceRepo(
                    repo=args.repo,
                    name=args.source,
                    refs=[args.ref] if args.ref else [],
                )
                result = source_obj.sync(ref=args.ref, force=args.force, verbose=True)
                results = {args.source: result}
            else:
                available = [f"{k} ({v.name})" for k, v in config.sources.items()]
                print(f"Error: Source '{args.source}' not found in config.", file=sys.stderr)
                print("Available sources:", ", ".join(available), file=sys.stderr)
                sys.exit(1)
        else:
            # Sync the configured source
            result = source_obj.sync(ref=args.ref, force=args.force, verbose=True)
            results = {source_obj.name: result}
    else:
        # Sync all configured sources
        results = config.sync(force=args.force, verbose=True)

    # Summarize results
    total_synced = sum(len(r.synced) for r in results.values())
    total_skipped = sum(len(r.skipped) for r in results.values())
    total_failed = sum(len(r.failed) for r in results.values())

    print("\nSync complete:")
    print(f"  Synced: {total_synced}")
    print(f"  Skipped: {total_skipped}")
    print(f"  Failed: {total_failed}")

    if total_failed:
        print("\nFailed syncs:")
        for source_name, result in results.items():
            for ref, error in result.failed:
                print(f"  {source_name}@{ref}: {error}")
        sys.exit(1)


def cmd_info(args):
    """Info command handler."""
    # Attempt auto-sync before showing info (unless disabled)
    if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
        _try_best_effort_sync()

    config = ModelSourceConfig.load()
    status = config.status

    if not status:
        print("No model registries configured")
        return

    # Collect source info
    sources = []
    for source_name, source_status in status.items():
        cached_refs = ", ".join(source_status.cached_refs) or "none"
        missing_refs = ", ".join(source_status.missing_refs) if source_status.missing_refs else None
        sources.append(
            {
                "name": source_name,
                "repo": source_status.repo,
                "cached": cached_refs,
                "missing": missing_refs,
            }
        )

    # Calculate layout
    term_width = shutil.get_terminal_size().columns
    min_col_width = 40
    num_cols = max(1, min(len(sources), term_width // min_col_width))
    col_width = term_width // num_cols - 2

    print("Model registries:\n")

    # Print sources in grid
    for i in range(0, len(sources), num_cols):
        row_sources = sources[i : i + num_cols]

        # Build rows for this group of sources
        rows = []
        max_lines = 0
        for src in row_sources:
            lines = [
                f"{src['name']} ({src['repo']})",
                f"Cached: {src['cached']}",
            ]
            if src["missing"]:
                lines.append(f"Missing: {src['missing']}")
            rows.append(lines)
            max_lines = max(max_lines, len(lines))

        # Print each line across columns
        for line_idx in range(max_lines):
            line_parts = []
            for col_idx, src_lines in enumerate(rows):
                if line_idx < len(src_lines):
                    text = src_lines[line_idx]
                    # Truncate if needed
                    if len(text) > col_width:
                        text = text[: col_width - 3] + "..."
                    line_parts.append(text.ljust(col_width))
                else:
                    line_parts.append(" " * col_width)
            print("  ".join(line_parts))
        print()


def cmd_list(args):
    """List command handler."""
    # Attempt auto-sync before listing (unless disabled)
    if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
        _try_best_effort_sync()

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
                    # Show all models in verbose mode, in grid layout
                    model_names = sorted(models.keys())
                    _format_grid(model_names, prefix="    ")
            else:
                print("  No models")

            examples = registry.examples
            if examples:
                print(f"  Examples: {len(examples)}")
                if args.verbose:
                    # Show all examples in verbose mode, in grid layout
                    example_names = sorted(examples.keys())
                    _format_grid(example_names, prefix="    ")
            print()


def cmd_clear(args):
    """Clear command handler."""
    cached = _DEFAULT_CACHE.list()

    # Determine what will be cleared
    if args.source and args.ref:
        items_to_clear = [(args.source, args.ref)]
        desc = f"{args.source}@{args.ref}"
    elif args.source:
        items_to_clear = [(source, ref) for source, ref in cached if source == args.source]
        desc = f"all refs for source '{args.source}'"
    else:
        items_to_clear = cached
        desc = "all cached registries"

    if not items_to_clear:
        if args.source or args.ref:
            filter_desc = []
            if args.source:
                filter_desc.append(f"source={args.source}")
            if args.ref:
                filter_desc.append(f"ref={args.ref}")
            print(f"No cached registries matching filters: {', '.join(filter_desc)}")
        else:
            print("No cached registries to clear")
        return

    # Show what will be cleared
    print(f"Will clear {desc}:")
    for source, ref in sorted(items_to_clear):
        print(f"  {source}@{ref}")

    # Confirm unless --force
    if not args.force:
        try:
            response = input("\nProceed? [y/N] ").strip().lower()
            if response not in ["y", "yes"]:
                print("Cancelled")
                return
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled")
            return

    # Clear the cache
    _DEFAULT_CACHE.clear(source=args.source, ref=args.ref)

    print(
        f"\nCleared {len(items_to_clear)} cached registr"
        f"{'y' if len(items_to_clear) == 1 else 'ies'}"
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mf models",
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

    # Clear command
    clear_parser = subparsers.add_parser("clear", help="Clear cached registries")
    clear_parser.add_argument(
        "--source",
        "-s",
        help="Clear specific source (default: all sources)",
    )
    clear_parser.add_argument(
        "--ref",
        "-r",
        help="Clear specific ref (requires --source)",
    )
    clear_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip confirmation prompt",
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
        elif args.command == "clear":
            cmd_clear(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
