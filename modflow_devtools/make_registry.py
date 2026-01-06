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
    parser = argparse.ArgumentParser(description="Make a registry of models.")
    parser.add_argument(
        "--path",
        "-p",
        required=False,
        default=None,
        type=str,
        help="Path to the model directory.",
    )
    parser.add_argument(
        "--model-name-prefix",
        type=str,
        help="Prefix for model names.",
        default="",
    )
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        help="Base URL for models.",
        default=models._DEFAULT_BASE_URL,
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
        help=("Output directory for registry file(s). "),
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

    if args.path:
        if args.verbose:
            print(f"Adding {args.path} to the registry.")
            if args.output:
                print(f"Output directory: {args.output}")
            print(f"Format: {'separate files' if args.separate else 'consolidated'}")
        models.DEFAULT_REGISTRY.index(
            path=args.path,
            url=args.url,
            prefix=args.model_name_prefix,
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
            models.DEFAULT_REGISTRY.index(
                path=options["path"],  # type: ignore
                url=options["url"],  # type: ignore
                prefix=options["model-name-prefix"],  # type: ignore
                namefile=options.get("namefile", "mfsim.nam"),  # type: ignore
                output_path=args.output,
                separate=args.separate,
            )
