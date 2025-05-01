import argparse

import modflow_devtools.models as models

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make a registry of models.")
    parser.add_argument("path")
    parser.add_argument(
        "--append",
        "-a",
        action="store_true",
        help="Append instead of overwriting.",
    )
    parser.add_argument(
        "--prefix", "-p", type=str, help="Prefix for models.", default=""
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
    args = parser.parse_args()
    if not args.append:
        models.DEFAULT_REGISTRY = models.PoochRegistry(
            base_url=args.url, env=models._DEFAULT_ENV
        )
    models.DEFAULT_REGISTRY.index(
        path=args.path,
        url=args.url,
        prefix=args.prefix,
        namefile=args.namefile,
    )
