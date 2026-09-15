"""
Root CLI for modflow-devtools.

Usage:
    mf sync
    mf dfns sync
    mf dfns info
    mf dfns list
    mf dfns clean
    mf models sync
    mf models info
    mf models list
    mf models copy <model> <workspace>
    mf models cp <model> <workspace>  # cp is an alias for copy
    mf programs install <program>
    mf programs uninstall <program>
    mf programs list
"""

import argparse
import sys


def _sync_all():
    """Sync all registries (dfns, models). The Programs API has no registry to sync -
    it installs directly from GitHub releases and tracks installs in a local ledger."""
    print("Syncing all registries...")
    print()

    # Sync DFNs
    print("=== DFNs ===")
    try:
        from modflow_devtools.dfns.registry import sync_dfns

        registries = sync_dfns()
        for registry in registries:
            meta = registry.registry_meta
            print(f"  {registry.ref}: {len(meta.files)} files")
        print(f"Synced {len(registries)} DFN registry(ies)")
    except Exception as e:
        print(f"Error syncing DFNs: {e}")
    print()

    # Sync Models
    print("=== Models ===")
    try:
        from modflow_devtools.models import ModelSourceConfig

        config = ModelSourceConfig.load()
        config.sync()
        print("Models synced successfully")
    except Exception as e:
        print(f"Error syncing models: {e}")
    print()

    print("All registries synced!")


def main():
    """Main entry point for the mf CLI."""
    parser = argparse.ArgumentParser(
        prog="mf",
        description="MODFLOW development tools",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # Sync subcommand (syncs all APIs)
    subparsers.add_parser("sync", help="Sync all registries (dfns, models)")

    # DFNs subcommand
    subparsers.add_parser("dfns", help="Manage MODFLOW 6 definition files")

    # Models subcommand
    subparsers.add_parser("models", help="Manage MODFLOW model registries")

    # Programs subcommand
    subparsers.add_parser("programs", help="Install and track MODFLOW program executables")

    # Parse only the first level to determine which submodule to invoke
    args, remaining = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    # Dispatch to the appropriate module CLI with remaining args
    if args.subcommand == "sync":
        _sync_all()
    elif args.subcommand == "dfns":
        from modflow_devtools.dfns.__main__ import main as dfns_main

        sys.argv = ["mf dfns", *remaining]
        sys.exit(dfns_main())
    elif args.subcommand == "models":
        from modflow_devtools.models.__main__ import main as models_main

        # Replace sys.argv to make it look like we called the submodule directly
        sys.argv = ["mf models", *remaining]
        models_main()
    elif args.subcommand == "programs":
        import warnings

        # Suppress experimental warning for official CLI
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*modflow_devtools.programs.*experimental.*")
            from modflow_devtools.programs.__main__ import main as programs_main

        sys.argv = ["mf programs", *remaining]
        programs_main()


if __name__ == "__main__":
    main()
