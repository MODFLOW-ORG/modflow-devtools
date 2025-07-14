"""Convert DFNs to TOML."""

import argparse
from os import PathLike
from pathlib import Path

import tomli_w as tomli
from boltons.iterutils import remap

from modflow_devtools.dfn import Dfn

# mypy: ignore-errors


def convert(indir: PathLike, outdir: PathLike):
    indir = Path(indir).expanduser().absolute()
    outdir = Path(outdir).expanduser().absolute()
    outdir.mkdir(exist_ok=True, parents=True)
    for dfn in Dfn.load_all(indir).values():
        dfn_name = dfn["name"]

        # Determine new filename and parent relationship
        if dfn_name == "sim-nam":
            filename = "sim.toml"
            dfn = dfn.copy()
            dfn["name"] = "sim"
            # No parent - this is root
        elif dfn_name.endswith("-nam"):
            # Model name files: gwf-nam -> gwf.toml, parent = "sim"
            model_type = dfn_name[:-4]  # Remove "-nam"
            filename = f"{model_type}.toml"
            dfn = dfn.copy()
            dfn["name"] = model_type
            dfn["parent"] = "sim"
        elif dfn_name.startswith("exg-"):
            # Exchanges: parent = "sim"
            filename = f"{dfn_name}.toml"
            dfn = dfn.copy()
            dfn["parent"] = "sim"
        elif dfn_name.startswith("sln-"):
            # Solutions: parent = "sim"
            filename = f"{dfn_name}.toml"
            dfn = dfn.copy()
            dfn["parent"] = "sim"
        elif dfn_name.startswith("utl-"):
            # Utilities: parent = "sim"
            filename = f"{dfn_name}.toml"
            dfn = dfn.copy()
            dfn["parent"] = "sim"
        elif "-" in dfn_name:
            # Packages: gwf-dis -> parent = "gwf"
            model_type = dfn_name.split("-")[0]
            filename = f"{dfn_name}.toml"
            dfn = dfn.copy()
            dfn["parent"] = model_type
        else:
            # Default case
            filename = f"{dfn_name}.toml"

        with Path.open(outdir / filename, "wb") as f:

            def drop_none_or_empty(path, key, value):
                if value is None or value == "" or value == [] or value == {}:
                    return False
                return True

            tomli.dump(remap(dfn, visit=drop_none_or_empty), f)


if __name__ == "__main__":
    """Convert DFN files to TOML."""

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
    args = parser.parse_args()
    convert(args.indir, args.outdir)
