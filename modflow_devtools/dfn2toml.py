"""Convert DFNs to TOML."""

import argparse
from dataclasses import asdict
from os import PathLike
from pathlib import Path

import tomli_w as tomli
from boltons.iterutils import remap

from modflow_devtools.dfn import load_flat, map, to_flat, to_tree
from modflow_devtools.dfn.schema.block import block_sort_key
from modflow_devtools.misc import drop_none_or_empty

# mypy: ignore-errors


def convert(indir: PathLike, outdir: PathLike, schema_version: str = "2") -> None:
    indir = Path(indir).expanduser().absolute()
    outdir = Path(outdir).expanduser().absolute()
    outdir.mkdir(exist_ok=True, parents=True)

    dfns = {
        name: map(dfn, schema_version=schema_version)
        for name, dfn in load_flat(indir).items()
    }
    tree = to_tree(dfns)
    flat = to_flat(tree)
    for dfn_name, dfn in flat.items():
        with Path.open(outdir / f"{dfn_name}.toml", "wb") as f:
            # TODO if we start using c/attrs, swap out
            # all this for a custom unstructuring hook
            dfn_dict = asdict(dfn)
            dfn_dict["schema_version"] = str(dfn_dict["schema_version"])
            if dfn_dict.get("blocks"):
                blocks = dfn_dict.pop("blocks")
                for block_name, block_fields in blocks.items():
                    if block_name not in dfn_dict:
                        dfn_dict[block_name] = {}
                    for field_name, field_data in block_fields.items():
                        dfn_dict[block_name][field_name] = field_data

            tomli.dump(
                dict(
                    sorted(
                        remap(dfn_dict, visit=drop_none_or_empty).items(),
                        key=block_sort_key,
                    )
                ),
                f,
            )


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
