"""Convert DFNs to TOML."""

import argparse
import sys
from dataclasses import asdict
from os import PathLike
from pathlib import Path

import tomli_w as tomli
from boltons.iterutils import remap

from modflow_devtools.dfn import Dfn, load, load_flat, map, parse_dfn, to_flat, to_tree
from modflow_devtools.dfn.schema.block import block_sort_key
from modflow_devtools.misc import drop_none_or_empty

# mypy: ignore-errors


def validate(path: str | PathLike) -> bool:
    """Validate DFN file(s) by attempting to parse them."""
    path = Path(path).expanduser().absolute()
    try:
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        if path.is_file():
            if path.name == "common.dfn":
                with path.open() as f:
                    parse_dfn(f)
            else:
                common_path = path.parent / "common.dfn"
                if common_path.exists():
                    with common_path.open() as f:
                        common, _ = parse_dfn(f)
                else:
                    common = {}
                with path.open() as f:
                    load(f, name=path.stem, common=common, format="dfn")
        else:
            load_flat(path)
        return True
    except Exception as e:
        print(f"Validation failed: {e}")
        return False


def convert(inpath: PathLike, outdir: PathLike, schema_version: str = "2") -> None:
    inpath = Path(inpath).expanduser().absolute()
    outdir = Path(outdir).expanduser().absolute()
    outdir.mkdir(exist_ok=True, parents=True)

    if inpath.is_file():
        if inpath.name == "common.dfn":
            raise ValueError("Cannot convert common.dfn as a standalone file")

        common_path = inpath.parent / "common.dfn"
        if common_path.exists():
            with common_path.open() as f:
                from modflow_devtools.dfn import parse_dfn

                common, _ = parse_dfn(f)
        else:
            common = {}

        with inpath.open() as f:
            dfn = load(f, name=inpath.stem, common=common, format="dfn")

        dfn = map(dfn, schema_version=schema_version)
        _convert(outdir / f"{inpath.stem}.toml", dfn)
    else:
        dfns = {
            name: map(dfn, schema_version=schema_version)
            for name, dfn in load_flat(inpath).items()
        }
        tree = to_tree(dfns)
        flat = to_flat(tree)
        for dfn_name, dfn in flat.items():
            _convert(outdir / f"{dfn_name}.toml", dfn)


def _convert(outpath: Path, dfn: Dfn) -> None:
    """Write a DFN object to a TOML file."""
    with Path.open(outpath, "wb") as f:
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
        help="Directory containing DFN files, or a single DFN file.",
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
    parser.add_argument(
        "--validate",
        "-v",
        action="store_true",
        help="Validate DFN files without converting them.",
    )
    args = parser.parse_args()

    if args.validate:
        if not validate(args.indir):
            sys.exit(1)
    else:
        convert(args.indir, args.outdir, args.schema_version)
