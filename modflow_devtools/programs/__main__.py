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
import sys

from . import (
    _DEFAULT_CACHE,
    ProgramSourceConfig,
    _try_best_effort_sync,
    install_program,
    list_installed,
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
                    # Show all programs in verbose mode
                    for program_name, metadata in sorted(programs.items()):
                        dist_names = (
                            ", ".join(d.name for d in metadata.dists) if metadata.dists else "none"
                        )
                        print(f"    - {program_name} ({ref}) [{dist_names}]")
            else:
                print("  No programs")
            print()


def cmd_install(args):
    """Install command handler."""
    # Attempt auto-sync before installation (unless disabled)
    if not os.environ.get("MODFLOW_DEVTOOLS_NO_AUTO_SYNC"):
        _try_best_effort_sync()

    try:
        paths = install_program(
            program=args.program,
            version=args.version,
            bindir=args.bindir,
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
        help="Installation directory (default: auto-select)",
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
