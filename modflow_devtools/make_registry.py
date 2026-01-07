import argparse
from pathlib import Path

import modflow_devtools.models as models

_REPOS_PATH = Path(__file__).parents[2]
_DEFAULT_REGISTRY_OPTIONS = [
    {
        "path": _REPOS_PATH / "modflow6-examples" / "examples",
        "url": "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip",
        "model-name-prefix": "mf6/example",
    },
    {
        "path": _REPOS_PATH / "modflow6-testmodels" / "mf6",
        "url": "https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6",
        "model-name-prefix": "mf6/test",
    },
    {
        "path": _REPOS_PATH / "modflow6-largetestmodels",
        "url": "https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master",
        "model-name-prefix": "mf6/large",
    },
    {
        "path": _REPOS_PATH / "modflow6-testmodels" / "mf5to6",
        "url": "https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf5to6",
        "model-name-prefix": "mf2005",
        "namefile": "*.nam",
    },
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Make a registry of models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Version-controlled models (e.g., testmodels)
  # Path in repo auto-detected from directory structure!
  # If path contains 'modflow6-testmodels/mf6', uses 'mf6' in URL
  python -m modflow_devtools.make_registry \\
    --path /path/to/modflow6-testmodels/mf6 \\
    --repo MODFLOW-ORG/modflow6-testmodels \\
    --ref master \\
    --mode version \\
    --name mf6/test \\
    --output .registry

  # Release asset models (e.g., examples)
  python -m modflow_devtools.make_registry \\
    --path /path/to/modflow6-examples/examples \\
    --repo MODFLOW-ORG/modflow6-examples \\
    --ref current \\
    --mode release \\
    --asset-file mf6examples.zip \\
    --name mf6/example \\
    --output .registry
""",
    )
    parser.add_argument(
        "--path",
        "-p",
        required=False,
        default=None,
        type=str,
        help="Path to the model directory.",
    )
    parser.add_argument(
        "--name",
        required=True,
        type=str,
        help=(
            "Model name prefix - must match the 'name' field in "
            "bootstrap sources (e.g., 'mf6/test', 'mf6/example')."
        ),
    )

    # Mode-based URL construction
    parser.add_argument(
        "--mode",
        required=True,
        choices=["version", "release"],
        help=(
            "Publication mode: 'version' (version-controlled files) "
            "or 'release' (release asset zip)."
        ),
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=str,
        help=(
            'Repository in "owner/name" format (e.g., MODFLOW-ORG/modflow6-testmodels).'
        ),
    )
    parser.add_argument(
        "--ref",
        required=True,
        type=str,
        help="Git ref (branch, tag, or commit hash).",
    )
    parser.add_argument(
        "--asset-file",
        type=str,
        help=(
            "Asset filename for 'release' mode (e.g., mf6examples.zip). "
            "Required when mode=release."
        ),
    )

    parser.add_argument(
        "--namefile",
        "-n",
        type=str,
        help="Namefile pattern to look for in the model directories.",
        default="mfsim.nam",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output directory for registry file(s).",
        default=None,
    )
    parser.add_argument(
        "--separate",
        action="store_true",
        help=(
            "Generate separate files (registry.toml, models.toml, examples.toml) "
            "for 1.x compatibility. Default is consolidated."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output.",
    )
    args = parser.parse_args()

    # Validate arguments and construct URL
    if args.mode == "version":
        # Auto-detect path in repo from directory structure
        path_in_repo = ""

        if args.path:
            path_obj = Path(args.path).resolve()
            # Extract repository name from owner/repo format
            repo_name = args.repo.split("/")[1]

            # Look for the repo name in the path
            path_parts = path_obj.parts
            try:
                # Find the index of the repo name in the path
                repo_index = path_parts.index(repo_name)
                # Everything after the repo name is the path in repo
                if repo_index + 1 < len(path_parts):
                    remaining_parts = path_parts[repo_index + 1 :]
                    path_in_repo = "/".join(remaining_parts)
                    if args.verbose:
                        print(
                            f"Detected path in repo: '{path_in_repo}' "
                            "(from directory structure)"
                        )
                else:
                    # Path ends at repo name, so we're at repo root
                    if args.verbose:
                        print("Detected path in repo: '' (repo root)")
            except ValueError:
                # Repo name not found in path - assume repo root
                if args.verbose:
                    print(
                        f"Warning: Repository name '{repo_name}' not found in path, "
                        "using repo root"
                    )

        # Construct raw GitHub URL for version-controlled files
        path_suffix = f"/{path_in_repo}" if path_in_repo else ""
        url = f"https://github.com/{args.repo}/raw/{args.ref}{path_suffix}"
        if args.verbose:
            print("Mode: version (version-controlled)")
            print(f"Constructed URL: {url}")

    elif args.mode == "release":
        # Construct release download URL for release assets
        if not args.asset_file:
            parser.error("--asset-file is required when mode=release")
        url = f"https://github.com/{args.repo}/releases/download/{args.ref}/{args.asset_file}"
        if args.verbose:
            print("Mode: release (release asset)")
            print(f"Constructed URL: {url}")

    if args.path:
        if args.verbose:
            print(f"Adding {args.path} to the registry.")
            if args.output:
                print(f"Output directory: {args.output}")
            print(f"Format: {'separate files' if args.separate else 'consolidated'}")
        models.get_default_registry().index(
            path=args.path,
            url=url,
            prefix=args.name,
            namefile=args.namefile,
            output_path=args.output,
            separate=args.separate,
        )
    else:
        if args.verbose:
            print("No path provided, creating default registry.")
            if args.output:
                print(f"Output directory: {args.output}")
            print(f"Format: {'separate files' if args.separate else 'consolidated'}")
        for options in _DEFAULT_REGISTRY_OPTIONS:
            if args.verbose:
                print(f"Adding {options['path']} to the registry.")
            models.get_default_registry().index(
                path=options["path"],  # type: ignore
                url=options["url"],  # type: ignore
                prefix=options.get("name", options.get("model-name-prefix", "")),  # type: ignore
                namefile=options.get("namefile", "mfsim.nam"),  # type: ignore
                output_path=args.output,
                separate=args.separate,
            )
