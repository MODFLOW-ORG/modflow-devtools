"""
Command-line interface for the Version API.

Commands:
    get     Show the current version from version.txt
    set     Set the version in version.txt, meson.build, and pixi.toml
"""

import argparse
import sys
from pathlib import Path

from . import get_version, set_version


def cmd_get(args):
    """Get command handler."""
    root = Path(args.root) if args.root else Path.cwd()
    try:
        print(get_version(root))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_set(args):
    """Set command handler."""
    root = Path(args.root) if args.root else Path.cwd()
    file = (root / args.file) if args.file else None
    try:
        set_version(
            version=args.version,
            root=root,
            dry_run=args.dry_run,
            file=file,
            pattern=args.pattern,
            fmt=args.format,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mf version",
        description="Manage project versions",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # get command
    get_parser = subparsers.add_parser("get", help="Show the current version")
    get_parser.add_argument(
        "--root",
        help="Project root directory (default: current working directory)",
    )

    # set command
    set_parser = subparsers.add_parser("set", help="Set the version")
    set_parser.add_argument("version", help="Version string (PEP 440)")
    set_parser.add_argument(
        "--root",
        help="Project root directory (default: current working directory)",
    )
    set_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying any files",
    )
    set_parser.add_argument(
        "--file",
        help="Additional file to update (relative to --root)",
    )
    set_parser.add_argument(
        "--pattern",
        help=(
            "Regex with one capture group matching the current version string "
            "(required with --file)"
        ),
    )
    set_parser.add_argument(
        "--format",
        dest="format",
        help=(
            "Format string for the replacement with a {version} placeholder (required with --file)"
        ),
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "set":
        file_args = [args.file, args.pattern, args.format]
        if any(file_args) and not all(file_args):
            parser.error("--file, --pattern, and --format must all be provided together")

    if args.command == "get":
        cmd_get(args)
    elif args.command == "set":
        cmd_set(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
