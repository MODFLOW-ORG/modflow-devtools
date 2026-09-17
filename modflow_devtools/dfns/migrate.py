"""Migrate MODFLOW 6 DFN files to a new schema version and/or serialization format."""

import argparse
import json
from os import PathLike
from pathlib import Path
from typing import Any, Literal

import pyaml
import tomli_w
from boltons.iterutils import remap
from pydantic import BaseModel

from modflow_devtools.misc import drop_none_or_empty

Format = Literal["yaml", "toml", "json"]

# YAML 1.1 (PyYAML default) serializes booleans as yes/no; override to true/false (YAML 1.2).
pyaml.add_representer(
    bool,
    lambda dumper, v: dumper.represent_scalar("tag:yaml.org,2002:bool", "true" if v else "false"),
)


def _add_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        help="Input file or directory containing DFN files.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output directory.",
    )
    parser.add_argument(
        "--schema-version",
        "-s",
        help="Target schema version.",
    )
    parser.add_argument(
        "--format",
        "-f",
        default="yaml",
        choices=["yaml", "toml", "json"],
        help="Output format (default: yaml).",
    )
    return parser


def _make_parser() -> argparse.ArgumentParser:
    return _add_args(
        argparse.ArgumentParser(
            description="Migrate DFN files' schema version and serialize to YAML, TOML, or JSON.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    )


def _serialize_safe(data: Any, drop_name: bool = True) -> Any:
    """Recursively coerce non-native types to primitives suitable for serialization."""

    if isinstance(data, BaseModel):
        return data.model_dump(
            context={"strip_names": True},
            exclude_none=True,
            exclude_unset=True,
            exclude_defaults=True,
        )
    if isinstance(data, dict):
        result = {k: _serialize_safe(v) for k, v in data.items() if v is not None}
        # strip name from field dict; name is the dict key in the block's fields.
        # this prevents redundancy in the serialized DFN files but requires name
        # to be inferred and attached again to the field at deserialization time.
        if drop_name and "name" in result and "type" in result:
            del result["name"]
        return result
    if isinstance(data, (list, tuple)):
        return [_serialize_safe(v) for v in data]
    if isinstance(data, (str, int, float, bool)) or data is None:
        return data
    return str(data)  # packaging.version.Version → str, etc.


def _scalars_first(data: Any) -> Any:
    """Recursively reorder dict keys so scalar values precede dicts and lists."""
    if isinstance(data, dict):
        scalars = {k: _scalars_first(v) for k, v in data.items() if not isinstance(v, (dict, list))}
        composites = {k: _scalars_first(v) for k, v in data.items() if isinstance(v, (dict, list))}
        return {**scalars, **composites}
    if isinstance(data, list):
        return [_scalars_first(v) for v in data]
    return data


def _write(data: dict, path: Path, fmt: Format) -> None:
    if fmt == "toml":
        with path.open("wb") as f:
            tomli_w.dump(data, f)
    elif fmt == "json":
        with path.open("w") as f:
            json.dump(data, f, indent=2)
    elif fmt == "yaml":
        with path.open("w") as f:
            pyaml.dump(data, f, vspacing=False, sort_keys=False)


def migrate(
    inpath: str | PathLike,
    outdir: str | PathLike,
    schema_version: str,
    fmt: Format = "yaml",
) -> None:
    """Migrate DFN file(s) to a new schema version.

    Parameters
    ----------
    inpath : str or PathLike
        Input file or directory.
    outdir : str or PathLike
        Output directory.
    schema_version : str
        Target schema version.
    fmt : str, optional
        Output format: "yaml", "toml", or "json". Default "yaml".
    """
    inpath = Path(inpath).expanduser().absolute()
    outdir = Path(outdir).expanduser().absolute()
    outdir.mkdir(exist_ok=True, parents=True)

    if schema_version in ["2.0.0.dev0", "2.0.0.dev1"]:
        from modflow_devtools.dfn import Dfn

        if inpath.is_file():
            with inpath.open() as f:
                dfns = {inpath.stem: Dfn.load(f, name=inpath.stem, schema_version=schema_version)}  # type: ignore
        else:
            dfns = Dfn.load_all(inpath, schema_version=schema_version)  # type: ignore
        dfns = {dfn_name: remap(dfn, visit=drop_none_or_empty) for dfn_name, dfn in dfns.items()}
        for dfn_name, dfn in dfns.items():
            _write(
                _scalars_first(_serialize_safe(dfn, drop_name=False)),
                outdir / f"{dfn_name}.{fmt}",
                fmt,
            )
    elif schema_version == "2.0.0.dev2":
        from modflow_devtools.dfn import schema as v1
        from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import to_v2_0_0_dev2

        inpath = Path(inpath).expanduser().absolute()
        common_path = inpath / "common.dfn"
        common = None
        if common_path.is_file():
            with common_path.open() as f:
                common, _ = v1.Dfn.load_dfn(f)  # type: ignore[attr-defined]
        exclude = {"common", "flopy"}
        dfn_paths = [p for p in sorted(inpath.glob("*.dfn")) if p.stem not in exclude]
        for dfn_path in dfn_paths:
            with dfn_path.open() as f:
                fields, meta = v1.Dfn.load_dfn(f, common=common)  # type: ignore[attr-defined]
            dfn = to_v2_0_0_dev2(name=dfn_path.stem, fields=fields, meta=meta)
            _write(_scalars_first(_serialize_safe(dfn)), outdir / f"{dfn_path.stem}.{fmt}", fmt)
    elif schema_version == "2.0.0.dev3":
        from modflow_devtools.dfn import schema as v1
        from modflow_devtools.dfns.migrate_to_v2_0_0_dev3 import to_v2_0_0_dev3

        inpath = Path(inpath).expanduser().absolute()
        common_path = inpath / "common.dfn"
        common = None
        if common_path.is_file():
            with common_path.open() as f:
                common, _ = v1.Dfn.load_dfn(f)  # type: ignore[attr-defined]
        exclude = {"common", "flopy"}
        dfn_paths = [p for p in sorted(inpath.glob("*.dfn")) if p.stem not in exclude]
        for dfn_path in dfn_paths:
            with dfn_path.open() as f:
                fields, meta = v1.Dfn.load_dfn(f, common=common)  # type: ignore[attr-defined]
            dfn = to_v2_0_0_dev3(name=dfn_path.stem, fields=fields, meta=meta)
            _write(_scalars_first(_serialize_safe(dfn)), outdir / f"{dfn_path.stem}.{fmt}", fmt)
    else:
        raise ValueError(
            f"Unsupported schema version {schema_version}, supported "
            "schema versions are: '2.0.0.dev0', '2.0.0.dev1', '2.0.0.dev2', '2.0.0.dev3'"
        )


if __name__ == "__main__":
    parser = _make_parser()
    args = parser.parse_args()
    migrate(
        inpath=args.input,
        outdir=args.output,
        schema_version=args.schema_version,
        fmt=args.format,
    )
