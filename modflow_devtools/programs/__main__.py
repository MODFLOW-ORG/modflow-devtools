"""
Command-line interface for the Programs API.

Commands:
    sync        Synchronize program registries
    info        Show sync status
    list        List available programs
    install     Install a program
    uninstall   Uninstall a program
    history     Show installation history
"""

import argparse
import os
import shutil
import sys

from . import (
    _DEFAULT_CACHE,
    ProgramSourceConfig,
    _try_best_effort_sync,
    install_program,
    list_installed,
    select_bindir,
    uninstall_program,
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


def cmd_info(args):
    """Info command handler."""
    config = ProgramSourceConfig.load()
    status = config.status

    if not status:
        print("No program registries configured")
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

    print("Program registries:\n")

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
                    # Show all programs in verbose mode, in grid layout
                    program_items = []
                    for program_name, metadata in sorted(programs.items()):
                        dist_names = (
                            ", ".join(d.name for d in metadata.dists) if metadata.dists else "none"
                        )
                        program_items.append(f"{program_name} ({ref}) [{dist_names}]")
                    _format_grid(program_items, prefix="    ")
            else:
                print("  No programs")
            print()


def cmd_install(args):
    """Install command handler."""
    # Attempt auto-sync before installation (unless disabled)
    if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
        _try_best_effort_sync()

    # Parse program@version syntax if provided
    if "@" in args.program:
        program, version = args.program.split("@", 1)
    else:
        program = args.program
        version = args.version

    # Handle ':' prefix shortcuts for bindir
    # Adapted from flopy's get-modflow utility
    bindir = args.bindir
    if bindir is not None and isinstance(bindir, str) and bindir.startswith(":"):
        try:
            bindir = select_bindir(bindir, program=program)
        except Exception as e:
            print(f"Installation failed: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        paths = install_program(
            program=program,
            version=version,
            bindir=bindir,
            platform=args.platform,
            force=args.force,
            verbose=True,
        )
        print("\nInstalled executables:")
        for path in paths:
            print(f"  {path}")
    except Exception as e:
        print(f"Installation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_uninstall(args):
    """Uninstall command handler."""
    # Parse program@version format if provided
    if "@" in args.program:
        program, version = args.program.split("@", 1)
    else:
        program = args.program
        version = None

    if not version and not args.all_versions:
        print(
            "Error: Must specify version (program@version) or use --all",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        uninstall_program(
            program=program,
            version=version,
            bindir=args.bindir,
            all_versions=args.all_versions,
            remove_cache=args.remove_cache,
            verbose=True,
        )
    except Exception as e:
        print(f"Uninstallation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args):
    """List installed programs command handler."""
    installed = list_installed(args.program)

    if not installed:
        if args.program:
            print(f"No installations found for {args.program}")
        else:
            print("No programs installed")
        return

    print("Installation history:\n")
    for program_name, installations in sorted(installed.items()):
        print(f"{program_name}:")
        for inst in sorted(installations, key=lambda i: i.version):
            print(f"  {inst.version} in {inst.bindir}")
            if args.verbose:
                print(f"    Platform: {inst.platform}")
                timestamp = inst.installed_at.strftime("%Y-%m-%d %H:%M:%S")
                print(f"    Installed: {timestamp}")
                print(f"    Executables: {', '.join(inst.executables)}")
        print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mf programs",
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
    subparsers.add_parser("info", help="Show sync status")

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

    # Install command
    install_parser = subparsers.add_parser("install", help="Install a program")
    install_parser.add_argument(
        "program",
        help="Program name (optionally with @version)",
    )
    install_parser.add_argument(
        "--version",
        help="Program version (if not specified in program name)",
    )
    install_parser.add_argument(
        "--bindir",
        help=(
            "Installation directory. Can be a path or a shortcut starting with ':'. "
            "Use ':' alone for interactive selection. "
            "Available shortcuts: :prev (previous), :mf (modflow-devtools), :python, "
            ":home (Unix) or :windowsapps (Windows), :system (Unix). "
            "Default: auto-select"
        ),
    )
    install_parser.add_argument(
        "--platform",
        help="Platform identifier (default: auto-detect)",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Force reinstallation",
    )

    # Uninstall command
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a program")
    uninstall_parser.add_argument(
        "program",
        help="Program name (optionally with @version)",
    )
    uninstall_parser.add_argument(
        "--bindir",
        help="Installation directory (default: all)",
    )
    uninstall_parser.add_argument(
        "--all",
        dest="all_versions",
        action="store_true",
        help="Uninstall all versions",
    )
    uninstall_parser.add_argument(
        "--remove-cache",
        action="store_true",
        help="Also remove from cache",
    )

    # History command (list installation history)
    history_parser = subparsers.add_parser("history", help="Show installation history")
    history_parser.add_argument(
        "program",
        nargs="?",
        help="Specific program to list (default: all)",
    )
    history_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed installation information",
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
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "history":
        cmd_history(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
