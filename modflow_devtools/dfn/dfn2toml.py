import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class Shim:
    @staticmethod
    def _attach_children(d: Any):
        if isinstance(d, Mapping):
            if "children" in d:
                for n, c in d["children"].items():
                    d[n] = c
                del d["children"]
            d = {k: Shim._attach_children(v) for k, v in d.items()}
        return d

    @staticmethod
    def _drop_none(d: Any):
        if isinstance(d, Mapping):
            return {k: Shim._drop_none(v) for k, v in d.items() if v is not None}
        else:
            return d

    @staticmethod
    def apply(d: dict) -> dict:
        return Shim._attach_children(Shim._drop_none(d))


if __name__ == "__main__":
    """Convert DFN files to TOML."""

    import tomlkit

    from modflow_devtools.dfn import Dfn

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
    indir = Path(args.indir)
    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True, parents=True)
    for dfn in Dfn.load_all(indir).values():
        with Path.open(outdir / f"{dfn['name']}.toml", "w") as f:
            tomlkit.dump(Shim.apply(dfn), f)
