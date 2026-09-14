"""
MODFLOW 6 definition file tools. Includes types for field
and component specification, a parser for the original
DFN format as well as for TOML definition files, and
a function to fetch DFNs from the MF6 repository.
"""

from ast import literal_eval
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import (
    Any,
    Literal,
    NotRequired,
    TypedDict,
)
from warnings import warn

from boltons.dictutils import OMD
from boltons.iterutils import remap

from modflow_devtools.misc import drop_none_or_empty

SchemaVersion = Literal["1", "2.0.0.dev0", "2.0.0.dev1"]
"""DFN format version number."""

FormatVersion = SchemaVersion
"""Deprecated alias for SchemaVersion."""


FileFormat = Literal["dfn", "toml", "yaml", "json"]
"""DFN serialization format."""

DfnFormat = FileFormat
"""Deprecated alias for FileFormat."""


FieldType = Literal[
    "keyword",
    "integer",
    "double precision",
    "string",
    "record",
    "recarray",
    "keystring",
]


Reader = Literal[
    "urword",
    "u1ddbl",
    "u2ddbl",
    "readarray",
]


_SCALAR_TYPES = ("keyword", "integer", "double precision", "string")
SCALAR_TYPES = _SCALAR_TYPES


class Field(TypedDict):
    name: str
    type: FieldType
    block: NotRequired[str | None]
    default: NotRequired[Any | None]
    longname: NotRequired[str | None]
    description: NotRequired[str | None]
    optional: NotRequired[bool]
    developmode: NotRequired[bool]
    shape: NotRequired[str | None]
    valid: NotRequired[tuple[str, ...] | None]
    netcdf: NotRequired[bool]
    tagged: NotRequired[bool]
    reader: NotRequired[Reader]
    in_record: NotRequired[bool]
    layered: NotRequired[bool | None]
    preserve_case: NotRequired[bool]
    numeric_index: NotRequired[bool]
    # Whether MF6 requires this block's header to appear in the input file
    # even when it has zero body lines (e.g. an empty required recarray
    # block). Set explicitly on the block's aggregate field -- see
    # Block.write_if_empty in modflow_devtools.dfns.schema for why this
    # can't be derived from `optional` or any other existing attribute.
    write_if_empty: NotRequired[bool]
    # Version strings (e.g. "6.6.0"), not booleans -- `load_dfn` stores every
    # attribute's raw text verbatim (see `field[key] = value` above), and unlike
    # the boolean-flag attributes here, nothing coerces these two via
    # `try_parse_bool` downstream.
    deprecated: NotRequired[str | None]
    removed: NotRequired[str | None]
    mf6internal: NotRequired[str | None]
    block_variable: NotRequired[bool]
    just_data: NotRequired[bool]
    time_series: NotRequired[bool]
    children: NotRequired[Mapping[str, "Field"] | None]
    item: NotRequired["Field"]
    choices: NotRequired[Mapping[str, "Field"]]
    fields: NotRequired[Mapping[str, "Field"]]


Fields = Mapping[str, "Field"]
Blocks = Mapping[str, Fields]


class Ref(TypedDict):
    key: str
    val: str
    abbr: str
    param: str
    parent: str
    description: str | None


class Sln(TypedDict):
    abbr: str
    pattern: str


Dfns = dict[str, "Dfn"]


class Dfn(TypedDict):
    """
    MODFLOW 6 input definition. An input definition
    specifies a component in an MF6 simulation, e.g.
    a model or package.

    Attributes
    ----------
    name : str
        Component name.
    advanced : bool
        Whether this is an advanced package.
    multi : bool
        Whether this is a multi-package.
    ref : Ref | None
        Metadata if this component is a subpackage (child's perspective).
        Populated from: # flopy subpackage <key> <abbr> <param> <val>
    sln : Sln | None
        Solution package metadata.
    fkeys : Dfns | None
        Field-level foreign key references to other components.
        Maps field names to Ref objects. Populated from flopy subpackage
        metadata when specific fields reference other components.
    subcomponents : list[str] | None
        Allowed child component types (schema-level constraint).
        Populated from: # mf6 subpackage <abbr>
        Example: ['UTL-NCF'] means this component can have utl-ncf children.
        Distinct from fkeys, which are field-level references.
    """

    schema_version: str
    name: str
    ftype: NotRequired[str | None]
    parent: NotRequired[str | list[str] | None]
    blocks: NotRequired[Blocks | None]
    children: NotRequired[Dfns | None]
    advanced: NotRequired[bool]
    multi: NotRequired[bool]
    ref: NotRequired[Ref | None]
    sln: NotRequired[Sln | None]
    fkeys: NotRequired[Dfns | None]  # deprecated
    subcomponents: NotRequired[list[str] | None]

    @staticmethod  # type: ignore[misc]
    def load_dfn(f, common: dict | None = None) -> tuple[OMD, list[str]]:
        """
        Parse a DFN file into an ordered multidict of fields and a list of comments.

        Parameters
        ----------
        f : readable file-like
            A file-like object to read the DFN file from.
        common : dict, optional
            A dictionary of common field definitions to use for
            description substitutions, by default None.

        Returns
        -------
        tuple[OMD, list[str]]
            A tuple containing an ordered multi-dict of fields and a list of comments

        Notes
        -----
        A DFN file consists of field definitions (each as a set of attributes) and a
        number of comment lines either a) containing metadata about the component or
        b) delimiting variables into blocks.

        The returned ordered multi-dict (OMD) maps names to dicts of their attributes,
        with duplicate field names allowed. This is important because some DFN files
        have fields with the same name defined multiple times for different purposes
        (e.g., an `auxiliary` options block keyword, and column in the period block).
        """
        field = {}
        fields = []
        comments = []
        common = common or {}

        for line in f:
            # remove whitespace/etc from the line
            line = line.strip()

            # record context name and flopy metadata
            # attributes, skip all other comment lines
            if line.startswith("#"):
                if "---" not in line:
                    comments.append(line)
                continue

            # if we hit a newline and the parameter dict
            # is nonempty, we've reached the end of its
            # block of attributes
            if not any(line):
                if any(field):
                    fields.append((field["name"], field))
                    field = {}
                continue

            # split attribute name and value and store it
            key, _, value = line.partition(" ")
            if key == "default_value":
                key = "default"
            field[key] = value

            # make common description text substitutions, remove backslashes, TODO: insert citations
            descr = field.get("description", None)
            if descr:
                descr = descr.replace("\\", "").replace("``", "'").replace("''", "'")
                _, replace, tail = descr.strip().partition("REPLACE")
                if replace:
                    key, _, subs = tail.strip().partition(" ")
                    subs = literal_eval(subs)
                    cmmn = common.get(key, None)
                    if cmmn is None:
                        warn(f"Can't substitute description text, common field not found: {key}")
                    else:
                        descr = cmmn.get("description", "")
                        if any(subs):
                            descr = descr.replace("\\", "").replace("{#1}", subs["{#1}"])
                field["description"] = descr

        # add the final parameter
        if any(field):
            fields.append((field["name"], field))

        # the point of the OMD is to losslessly handle duplicate variable names
        return OMD(fields), comments

    @staticmethod  # type: ignore[misc]
    def _load_v1_flat(f, common: dict | None = None) -> tuple[OMD, list[str]]:
        """Deprecated alias for load_dfn."""
        warn("'_load_v1_flat' is deprecated, use 'load_dfn' instead", DeprecationWarning)
        return Dfn.load_dfn(f, common=common)

    @classmethod  # type: ignore[misc]
    def load(
        cls,
        f,
        name: str | None = None,
        schema_version: SchemaVersion = "2.0.0.dev0",
        version: SchemaVersion | None = None,
        **kwargs,
    ) -> "Dfn":
        """
        Load a definition file, automatically migrating the schema version by default.
        """

        if version:
            warn(
                "'version' is deprecated, use 'schema_version' instead",
                DeprecationWarning,
            )
            schema_version = version

        refs = kwargs.pop("refs", {})
        fields, meta = cls.load_dfn(f, **kwargs)

        match str(schema_version):
            case "1":
                data = fields
            case "2.0.0.dev0":
                from modflow_devtools.dfn.migrate_to_v2_0_0_dev0 import to_v2_0_0_dev0

                data = to_v2_0_0_dev0(name=name, fields=fields, meta=meta, refs=refs)
                data = remap(data, visit=drop_none_or_empty)
            case "2.0.0.dev1":
                from modflow_devtools.dfn.migrate_to_v2_0_0_dev1 import to_v2_0_0_dev1

                data = to_v2_0_0_dev1(name=name, fields=fields, meta=meta)
                data = remap(data, visit=drop_none_or_empty)
            case _:
                raise ValueError(
                    f"Unsupported schema version '{schema_version!r}' requested, "
                    "supported schema versions are: '1', '2.0.0.dev0', '2.0.0.dev1'"
                )

        return cls(**data)

    @staticmethod  # type: ignore[misc]
    def load_all(
        dfndir: str | PathLike,
        schema_version: str = "2.0.0.dev0",
        version: "int | str | None" = None,
    ) -> Dfns:
        """Load component definitions from a directory."""

        if version is not None:
            warn("'version' is deprecated, use 'schema_version' instead", DeprecationWarning)
            _version_map = {1: "1", 2: "2.0.0.dev0"}
            schema_version = _version_map.get(version, str(version))  # type: ignore[arg-type]

        dfndir = Path(dfndir).expanduser().resolve().absolute()

        exclude = {"common", "flopy"}
        dfn_paths: list[Path] = sorted(p for p in dfndir.glob("*.dfn") if p.stem not in exclude)
        dfns: Dfns = {}

        if not dfn_paths:
            raise ValueError(f"No definition files found in {dfndir}")

        # load common fields
        common_path: Path | None = dfndir / "common.dfn"
        if not common_path.is_file():
            common = None
        else:
            with common_path.open() as f:
                common = Dfn.load(f, schema_version="1")

        match str(schema_version):
            case "1":
                for path in dfn_paths:
                    with path.open() as f:
                        dfns[path.stem] = Dfn.load(
                            f, name=path.stem, schema_version="1", common=common
                        )
            case "2.0.0.dev0":
                # load subpackages first so we can pass
                # their references in to other packages
                subpkgs = {}
                for path in dfn_paths:
                    with path.open() as f:
                        dfn = Dfn.load(
                            f, name=path.stem, common=common, schema_version="2.0.0.dev0"
                        )
                        ref = dfn.get("ref", None)
                        if ref:
                            subpkgs[ref["key"]] = ref

                # load the rest of the definitions
                for path in dfn_paths:
                    with path.open() as f:
                        dfns[path.stem] = Dfn.load(
                            f,
                            name=path.stem,
                            schema_version="2.0.0.dev0",
                            common=common,
                            refs=subpkgs,
                        )
            case "2.0.0.dev1":
                for path in dfn_paths:
                    with path.open() as f:
                        dfns[path.stem] = Dfn.load(
                            f, name=path.stem, schema_version="2.0.0.dev1", common=common
                        )
            case _:
                raise ValueError(
                    f"Unsupported schema version '{schema_version!r}' requested, "
                    "supported schema versions are: '1', '2.0.0.dev0', '2.0.0.dev1'"
                )

        return dfns


def get_fields(dfn: Dfn) -> OMD:
    """Combined map of fields from all blocks (flat, top-level only)."""
    items = []
    for block in (dfn.get("blocks") or {}).values():
        for f in block.values():
            items.append((f["name"], f))
    return OMD(items)
