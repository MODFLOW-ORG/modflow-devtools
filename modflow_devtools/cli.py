"""
Root CLI for modflow-devtools.

Usage:
    mf models sync
    mf models info
    mf models list
    mf programs sync
    mf programs info
    mf programs list
    mf programs install <program>
    mf programs uninstall <program>
    mf programs history
    mf version get
    mf version set <version>
"""

import argparse
import sys


def main():
    """Main entry point for the mf CLI."""
    parser = argparse.ArgumentParser(
        prog="mf",
        description="MODFLOW development tools",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # Models subcommand
    subparsers.add_parser("models", help="Manage MODFLOW model registries")

    # Programs subcommand
    subparsers.add_parser("programs", help="Manage MODFLOW program registries")

    # Version subcommand
    subparsers.add_parser("version", help="Manage project versions")

    # Parse only the first level to determine which submodule to invoke
    args, remaining = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    # Dispatch to the appropriate module CLI with remaining args
    if args.subcommand == "models":
        from modflow_devtools.models.__main__ import main as models_main

        # Replace sys.argv to make it look like we called the submodule directly
        sys.argv = ["mf models", *remaining]
        models_main()
    elif args.subcommand == "programs":
        from modflow_devtools.programs.__main__ import main as programs_main

        sys.argv = ["mf programs", *remaining]
        programs_main()
    elif args.subcommand == "version":
        from modflow_devtools.version.__main__ import main as version_main

        sys.argv = ["mf version", *remaining]
        version_main()


if __name__ == "__main__":
    main()
