"""Convert DFNs to TOML."""

import argparse
from dataclasses import asdict
from os import PathLike
from pathlib import Path

import tomli_w as tomli

from modflow_devtools.dfn import load_all, map

# mypy: ignore-errors


def convert(indir: PathLike, outdir: PathLike, schema_version: str = "2") -> None:
    indir = Path(indir).expanduser().absolute()
    outdir = Path(outdir).expanduser().absolute()
    outdir.mkdir(exist_ok=True, parents=True)
    dfns_in = load_all(indir)
    dfns = {
        name: map(dfn, schema_version=schema_version) for name, dfn in dfns_in.items()
    }
    for dfn_name, dfn in dfns.items():
        with Path.open(outdir / f"{dfn_name}.toml", "wb") as f:
            tomli.dump(asdict(dfn), f)


if __name__ == "__main__":
    """
    Convert DFN files in the original format and schema version (1)
    to TOML files with a new schema version.
    """

    parser = argparse.ArgumentParser(description="Convert DFN files to TOML.")
    parser.add_argument(
        "--indir",
        "-i",
        type=str,
        help="Directory containing DFN files.",
    )
    parser.add_argument(
        "--outdir",
        "-o",
        help="Output directory.",
    )
    parser.add_argument(
        "--schema-version",
        "-s",
        type=str,
        default="2",
        help="Schema version to convert to.",
    )
    args = parser.parse_args()
    convert(args.indir, args.outdir, args.schema_version)
