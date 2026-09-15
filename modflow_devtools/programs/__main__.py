"""
Command-line interface for the Programs API.

Commands:
    install     Install program executable(s)
    uninstall   Uninstall a program
    list        List installed programs
"""

import argparse
import sys

from . import (
    DEFAULT_OWNER,
    DEFAULT_REPO,
    KNOWN_REPOS,
    install_program,
    list_installed,
    select_bindir,
    uninstall_program,
)


def cmd_install(args):
    """Install command handler."""
    program = args.program
    version = args.version
    if program and "@" in program:
        program, version = program.split("@", 1)

    bindir = args.bindir
    if bindir is not None and bindir.startswith(":"):
        try:
            bindir = select_bindir(bindir, program=program)
        except Exception as e:
            print(f"Installation failed: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        installations = install_program(
            program=program,
            repo=args.repo,
            owner=args.owner,
            version=version or "latest",
            bindir=bindir,
            platform=args.platform,
            subset=args.subset,
            force=args.force,
            verbose=True,
        )
        print("\nInstalled:")
        for inst in installations:
            for exe in inst.executables:
                print(f"  {exe} {inst.version} -> {inst.bindir / exe}")
    except Exception as e:
        print(f"Installation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_uninstall(args):
    """Uninstall command handler."""
    program = args.program
    version = None
    if "@" in program:
        program, version = program.split("@", 1)

    if not version and not args.all_versions:
        print("Error: Must specify version (program@version) or use --all", file=sys.stderr)
        sys.exit(1)

    try:
        uninstall_program(
            program=program,
            version=version,
            bindir=args.bindir,
            all_versions=args.all_versions,
            delete_files=not args.keep_files,
            verbose=True,
        )
    except Exception as e:
        print(f"Uninstallation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    """List installed programs command handler."""
    installed = list_installed(args.program)

    if not installed:
        if args.program:
            print(f"No installations found for {args.program}")
        else:
            print("No programs installed")
        return

    for program_name, installations in sorted(installed.items()):
        print(f"{program_name}:")
        for inst in sorted(installations, key=lambda i: i.version):
            print(f"  {inst.version} in {inst.bindir}")
            if args.verbose:
                print(f"    Platform: {inst.platform}")
                print(f"    Installed: {inst.installed_at.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    Source: {inst.source}")
                print(f"    Executables: {', '.join(inst.executables)}")
        print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mf programs",
        description="Install and track MODFLOW program executables",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    install_parser = subparsers.add_parser("install", help="Install program executable(s)")
    install_parser.add_argument(
        "program",
        nargs="?",
        help="Program name, optionally with @version. If omitted, installs every "
        "program in the release (or use --subset for several by name).",
    )
    install_parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Source repo under --owner; default is '{DEFAULT_REPO}'. Not restricted to "
        f"{KNOWN_REPOS} - any repo with a GitHub release and a matching platform asset "
        "works, e.g. 'mfnwt', 'gridgen'.",
    )
    install_parser.add_argument(
        "--owner",
        default=DEFAULT_OWNER,
        help=f"GitHub repository owner; default is '{DEFAULT_OWNER}'.",
    )
    install_parser.add_argument("--version", help="Release tag; default is 'latest'.")
    install_parser.add_argument(
        "--bindir",
        help=(
            "Installation directory. Can be a path or a shortcut starting with ':'. "
            "Use ':' alone for interactive selection. Available shortcuts: "
            ":prev, :mf, :python, :home (Unix) or :windowsapps (Windows), :system (Unix). "
            "Default: auto-select."
        ),
    )
    install_parser.add_argument("--platform", help="Ostag override; default is to auto-detect.")
    install_parser.add_argument(
        "--subset",
        help="Comma-separated list of programs to install from a combined release, "
        "e.g. 'mf6,zbud6'.",
    )
    install_parser.add_argument(
        "--force", action="store_true", help="Force re-download of the archive."
    )

    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a program")
    uninstall_parser.add_argument("program", help="Program name, optionally with @version.")
    uninstall_parser.add_argument("--bindir", help="Installation directory (default: all).")
    uninstall_parser.add_argument(
        "--all", dest="all_versions", action="store_true", help="Uninstall all versions."
    )
    uninstall_parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Forget the installation without deleting the executable(s).",
    )

    list_parser = subparsers.add_parser("list", help="List installed programs")
    list_parser.add_argument("program", nargs="?", help="Specific program to list (default: all).")
    list_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show installation details."
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "install":
        cmd_install(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
