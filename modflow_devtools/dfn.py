"""
MODFLOW 6 definition file tools. Includes types for field
and component specification, a parser for the original
DFN format as well as for TOML definition files, and
a function to fetch DFNs from the MF6 repository.
"""

import shutil
import tempfile
from ast import literal_eval
from collections.abc import Mapping
from itertools import groupby
from os import PathLike
from pathlib import Path
from typing import (
    Any,
    Literal,
    Optional,
    TypedDict,
)
from warnings import warn

import tomli
from boltons.dictutils import OMD
from boltons.iterutils import remap

from modflow_devtools.download import download_and_unzip
from modflow_devtools.misc import try_literal_eval


def try_parse_bool(value: Any) -> Any:
    """
    Try to parse a boolean from a string as represented
    in a DFN file, otherwise return the value unaltered.
    """
    if isinstance(value, str):
        value = value.lower()
        if value in ["true", "false"]:
            return value == "true"
    return value


def field_attr_sort_key(item) -> int:
    """
    Sort key for input field attributes. The order is:
    -1. block
    0. name
    1. type
    2. shape
    3. default
    4. reader
    5. optional
    6. longname
    7. description
    """

    k, _ = item
    if k == "block":
        return -1
    if k == "name":
        return 0
    if k == "type":
        return 1
    if k == "shape":
        return 2
    if k == "default":
        return 3
    if k == "reader":
        return 4
    if k == "optional":
        return 5
    if k == "longname":
        return 6
    if k == "description":
        return 7
    return 8


def block_sort_key(item) -> int:
    k, _ = item
    if k == "options":
        return 0
    elif k == "dimensions":
        return 1
    elif k == "griddata":
        return 2
    elif k == "packagedata":
        return 3
    elif "period" in k:
        return 4
    else:
        return 5


FormatVersion = Literal[1, 2]
"""DFN format version number."""


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


Dfns = dict[str, "Dfn"]
Fields = dict[str, "Field"]
Block = Fields
Blocks = dict[str, Block]


def get_blocks(dfn: "Dfn") -> Blocks:
    """
    Extract blocks from an input definition.
    """

    def _is_block(item: tuple[str, Any]) -> bool:
        k, v = item
        return k not in Dfn.__annotations__

    return dict(
        sorted(
            {k: v for k, v in dfn.items() if _is_block((k, v))}.items(),  # type: ignore
            key=block_sort_key,
        )
    )


def get_fields(dfn: "Dfn") -> Fields:
    """
    Extract a flat dictionary of fields from an input definition.
    Only top-level fields are included, i.e. subfields of records
    or recarrays are not included.
    """
    fields = {}
    for block in get_blocks(dfn).values():
        for field in block.values():
            if field["name"] in fields:
                warn(f"Duplicate field name {field['name']} in {dfn['name']}")
            fields[field["name"]] = field
    return fields


class Field(TypedDict):
    """A field specification."""

    name: str
    type: FieldType
    shape: Any | None
    block: str | None
    default: Any | None
    children: Optional["Fields"]
    description: str | None
    reader: Reader


class Ref(TypedDict):
    """
    A foreign-key-like reference between a file input variable
    in a referring input component and another input component
    referenced by it. Previously known as a "subpackage".

    A `Dfn` with a nonempty `ref` can be referred to by other
    component definitions, via a filepath variable which acts
    as a foreign key. If such a variable is detected when any
    component is loaded, the component's `__init__` method is
    modified, such that the variable named `val`, residing in
    the referenced component, replaces the variable with name
    `key` in the referencing component, i.e., the foreign key
    filepath variable, This forces a referencing component to
    accept a subcomponent's data directly, as if it were just
    a variable, rather than indirectly, with the subcomponent
    loaded up from a file identified by the filepath variable.
    """

    key: str
    val: str
    abbr: str
    param: str
    parent: str
    description: str | None


class Sln(TypedDict):
    """
    A solution package specification.
    """

    abbr: str
    pattern: str


class Dfn(TypedDict):
    """
    MODFLOW 6 input definition. An input definition
    specifies a component in an MF6 simulation, e.g.
    a model or package. A component contains input
    variables, and may contain other metadata such
    as foreign key references to other components
    (i.e. subpackages), package-specific metadata
    (e.g. for solutions), advanced package status,
    and whether the component is a multi-package.

    An input definition must have a name. Other top-
    level keys are blocks, which must be mappings of
    `str` to `Field`, and metadata, of which only a
    limited set of keys are allowed. Block names and
    metadata keys may not overlap.
    """

    name: str
    advanced: bool
    multi: bool
    parent: str | None
    ref: Ref | None
    sln: Sln | None

    @staticmethod  # type: ignore[misc]
    def _load_v1_flat(f, common: dict | None = None) -> tuple[Mapping, list[str]]:
        field = {}
        flat = []
        meta = []
        common = common or {}

        for line in f:
            # remove whitespace/etc from the line
            line = line.strip()

            # record context name and flopy metadata
            # attributes, skip all other comment lines
            if line.startswith("#"):
                _, sep, tail = line.partition("flopy")
                if sep == "flopy":
                    if (
                        "multi-package" in tail
                        or "solution_package" in tail
                        or "subpackage" in tail
                        or "parent" in tail
                    ):
                        meta.append(tail.strip())
                _, sep, tail = line.partition("package-type")
                if sep == "package-type":
                    meta.append(f"package-type {tail.strip()}")
                continue

            # if we hit a newline and the parameter dict
            # is nonempty, we've reached the end of its
            # block of attributes
            if not any(line):
                if any(field):
                    flat.append((field["name"], field))
                    field = {}
                continue

            # split the attribute's key and value and
            # store it in the parameter dictionary
            key, _, value = line.partition(" ")
            if key == "default_value":
                key = "default"
            field[key] = value

            # make substitutions from common variable definitions,
            # remove backslashes, TODO: generate/insert citations.
            descr = field.get("description", None)
            if descr:
                descr = descr.replace("\\", "").replace("``", "'").replace("''", "'")
                _, replace, tail = descr.strip().partition("REPLACE")
                if replace:
                    key, _, subs = tail.strip().partition(" ")
                    subs = literal_eval(subs)
                    cmmn = common.get(key, None)
                    if cmmn is None:
                        warn(f"Can't substitute description text, common variable not found: {key}")
                    else:
                        descr = cmmn.get("description", "")
                        if any(subs):
                            descr = descr.replace("\\", "").replace("{#1}", subs["{#1}"])
                field["description"] = descr

        # add the final parameter
        if any(field):
            flat.append((field["name"], field))

        # the point of the OMD is to losslessly handle duplicate variable names
        return OMD(flat), meta

    @classmethod  # type: ignore[misc]
    def _load_v1(cls, f, name, **kwargs) -> "Dfn":
        """
        Temporary load routine for the v1 DFN format.
        """

        flat, meta = Dfn._load_v1_flat(f, **kwargs)

        def _convert_recarray_block(block: Block, block_name: str) -> Block:
            """
            Convert a recarray block to individual arrays, one per column.

            Extract recarray fields and create separate array variables. For period
            blocks, give each an appropriate grid- or time-aligned shape (nper, nnodes).
            For other blocks, uses the declared dimensions directly.
            """

            fields = list(block.values())
            if fields[0]["type"] == "recarray":
                assert len(fields) == 1
                recarray_field = fields[0]
                recarray_name = recarray_field["name"]
                item = next(iter(recarray_field["children"].values()))
                columns = item["children"]

                # Get the original recarray shape to determine base dimensions
                recarray_shape = recarray_field.get("shape")
                if recarray_shape:
                    # Parse shape like "(nexg)" or "(maxbound)"
                    base_dims = recarray_shape[1:-1].split(",")
                    base_dims = [dim.strip() for dim in base_dims if dim.strip()]
                else:
                    base_dims = []
            else:
                recarray_name = None
                columns = block
                base_dims = []

            # Remove the original recarray field
            block.pop(recarray_name, None)

            # Handle cellid specially - it indicates spatial indexing
            cellid = columns.pop("cellid", None)

            for col_name, column in columns.items():
                col_copy = column.copy()
                old_dims = col_copy.get("shape")
                if old_dims:
                    old_dims = old_dims[1:-1].split(",")
                    old_dims = [dim.strip() for dim in old_dims if dim.strip()]
                else:
                    old_dims = []

                # Determine new dimensions based on block type
                if block_name == "period":
                    # Period blocks get time + spatial dimensions
                    new_dims = ["nper"]
                    if cellid:
                        new_dims.append("nnodes")
                    # Add any additional dimensions, excluding maxbound
                    if old_dims:
                        new_dims.extend([dim for dim in old_dims if dim != "maxbound"])
                else:
                    # Non-period blocks use declared dimensions
                    new_dims = []
                    if base_dims:
                        # Use the dimensions from the recarray shape
                        # Only drop maxbound if there are other meaningful dimensions
                        filtered_base_dims = [
                            dim for dim in base_dims if dim != "maxbound"
                        ]
                        if filtered_base_dims:
                            new_dims.extend(filtered_base_dims)
                        else:
                            # Keep maxbound if no other dimensions are available
                            new_dims.extend(base_dims)
                    # Add any column-specific dimensions
                    if old_dims:
                        filtered_old_dims = [
                            dim for dim in old_dims if dim != "maxbound"
                        ]
                        if filtered_old_dims:
                            new_dims.extend(filtered_old_dims)
                        else:
                            # Keep maxbound if no other dimensions are available
                            new_dims.extend(old_dims)

                if new_dims:
                    col_copy["shape"] = f"({', '.join(new_dims)})"
                else:
                    # Scalar field
                    col_copy["shape"] = None

                block[col_name] = col_copy

            return block

        def _convert_field(var: dict[str, Any]) -> Field:
            """
            Convert an input field specification from its representation
            in a v1 format definition file to the v2 (structured) format.

            Notes
            -----
            If the field does not have a `default` attribute, it will
            default to `False` if it is a keyword, otherwise to `None`.

            A filepath field whose name functions as a foreign key
            for a separate context will be given a reference to it.
            """

            def _load(field) -> Field:
                field = field.copy()

                # parse booleans from strings. everything else can
                # stay a string except default values, which we'll
                # try to parse as arbitrary literals below, and at
                # some point types, once we introduce type hinting
                field = {k: try_parse_bool(v) for k, v in field.items()}

                _name = field.pop("name")
                _type = field.pop("type", None)
                shape = field.pop("shape", None)
                shape = None if shape == "" else shape
                block = field.pop("block", None)
                default = field.pop("default", None)
                default = try_literal_eval(default) if _type != "string" else default
                description = field.pop("description", "")
                reader = field.pop("reader", "urword")

                def _item() -> Field:
                    """Load list item."""

                    item_names = _type.split()[1:]
                    item_types = [
                        v["type"]
                        for v in flat.values(multi=True)
                        if v["name"] in item_names and v.get("in_record", False)
                    ]
                    n_item_names = len(item_names)
                    if n_item_names < 1:
                        raise ValueError(f"Missing list definition: {_type}")

                    # explicit record
                    if n_item_names == 1 and (
                        item_types[0].startswith("record") or item_types[0].startswith("keystring")
                    ):
                        return _convert_field(next(iter(flat.getlist(item_names[0]))))

                    # implicit simple record (no children)
                    if all(t in _SCALAR_TYPES for t in item_types):
                        return Field(
                            name=_name,
                            type="record",
                            block=block,
                            children=_fields(),
                            description=description.replace(
                                "is the list of", "is the record of"
                            ),
                            reader=reader,
                            **field,
                        )

                    # implicit complex record (has children)
                    fields = {
                        v["name"]: _convert_field(v)
                        for v in flat.values(multi=True)
                        if v["name"] in item_names and v.get("in_record", False)
                    }
                    first = next(iter(fields.values()))
                    single = len(fields) == 1
                    item_type = "keystring" if single and "keystring" in first["type"] else "record"
                    return Field(
                        name=first["name"] if single else _name,
                        type=item_type,
                        block=block,
                        children=first["children"] if single else fields,
                        description=description.replace(
                            "is the list of", f"is the {item_type} of"
                        ),
                        reader=reader,
                        **field,
                    )

                def _choices() -> Fields:
                    """Load keystring (union) choices."""
                    names = _type.split()[1:]
                    return {
                        v["name"]: _convert_field(v)
                        for v in flat.values(multi=True)
                        if v["name"] in names and v.get("in_record", False)
                    }

                def _fields() -> Fields:
                    """Load record fields."""
                    names = _type.split()[1:]
                    fields = {}
                    for name in names:
                        v = flat.get(name, None)
                        if not v or not v.get("in_record", False) or v["type"].startswith("record"):
                            continue
                        fields[name] = _convert_field(v)
                    return fields

                var_ = Field(
                    name=_name,
                    shape=shape,
                    block=block,
                    description=description,
                    default=default,
                    reader=reader,
                    **field,
                )

                if _type.startswith("recarray"):
                    item = _item()
                    var_["children"] = {item["name"]: item}
                    var_["type"] = "recarray"

                elif _type.startswith("keystring"):
                    var_["children"] = _choices()
                    var_["type"] = "keystring"

                elif _type.startswith("record"):
                    var_["children"] = _fields()
                    var_["type"] = "record"

                # for now, we can tell a var is an array if its type
                # is scalar and it has a shape. once we have proper
                # typing, this can be read off the type itself.
                elif shape is not None and _type not in _SCALAR_TYPES:
                    raise TypeError(f"Unsupported array type: {_type}")

                else:
                    var_["type"] = _type

                return var_

            return dict(sorted(_load(var).items(), key=field_attr_sort_key))

        # load top-level fields. any nested
        # fields will be loaded recursively
        fields = {
            field["name"]: _convert_field(field)
            for field in flat.values(multi=True)
            if not field.get("in_record", False)
        }

        # group variables by block
        blocks = {
            block_name: {v["name"]: v for v in block}
            for block_name, block in groupby(fields.values(), lambda v: v["block"])
        }

        # extract distinct arrays from recarray-style definitions in all blocks
        for block_name, block in blocks.items():
            # Check if this block contains any recarray fields
            has_recarray = any(field["type"] == "recarray" for field in block.values())
            if has_recarray:
                blocks[block_name] = _convert_recarray_block(block, block_name)

        # remove unneeded variable attributes
        def remove_attrs(path, key, value):
            if key in ["in_record", "tagged", "preserve_case"]:
                return False
            return True

        blocks = remap(blocks, visit=remove_attrs)

        def _advanced() -> bool | None:
            return any("package-type advanced" in m for m in meta)

        def _multi() -> bool:
            return any("multi-package" in m for m in meta)

        def _sln() -> Sln | None:
            sln = next(
                iter(m for m in meta if isinstance(m, str) and m.startswith("solution_package")),
                None,
            )
            if sln:
                abbr, pattern = sln.split()[1:]
                return Sln(abbr=abbr, pattern=pattern)
            return None

        def _sub() -> Ref | None:
            def _parent():
                line = next(
                    iter(m for m in meta if isinstance(m, str) and m.startswith("parent")),
                    None,
                )
                if not line:
                    return None
                split = line.split()
                return split[1]

            def _rest():
                line = next(
                    iter(m for m in meta if isinstance(m, str) and m.startswith("subpac")),
                    None,
                )
                if not line:
                    return None
                _, key, abbr, param, val = line.split()
                matches = [v for v in fields.values() if v["name"] == val]
                if not any(matches):
                    descr = None
                else:
                    if len(matches) > 1:
                        warn(f"Multiple matches for referenced variable {val}")
                    match = matches[0]
                    descr = match["description"]

                return {
                    "key": key,
                    "val": val,
                    "abbr": abbr,
                    "param": param,
                    "description": descr,
                }

            parent = _parent()
            rest = _rest()
            if parent and rest:
                return Ref(parent=parent, **rest)
            return None

        return cls(
            name=name,
            advanced=_advanced(),
            multi=_multi(),
            sln=_sln(),
            ref=_sub(),
            **blocks,
        )

    @classmethod  # type: ignore[misc]
    def _load_v2(cls, f, name) -> "Dfn":
        data = tomli.load(f)
        if name and name != data.get("name", None):
            raise ValueError(f"Name mismatch, expected {name}")
        return cls(**data)

    @classmethod  # type: ignore[misc]
    def load(
        cls,
        f,
        name: str | None = None,
        version: FormatVersion = 1,
        **kwargs,
    ) -> "Dfn":
        """
        Load a component definition from a definition file.
        """

        if version == 1:
            return cls._load_v1(f, name, **kwargs)
        elif version == 2:
            return cls._load_v2(f, name)
        else:
            raise ValueError(f"Unsupported version, expected one of {version.__args__}")

    @staticmethod  # type: ignore[misc]
    def _load_all_v1(dfndir: PathLike) -> Dfns:
        paths: list[Path] = [p for p in dfndir.glob("*.dfn") if p.stem not in ["common", "flopy"]]

        # load common variables
        common_path: Path | None = dfndir / "common.dfn"
        if not common_path.is_file():
            common = None
        else:
            with common_path.open() as f:
                common, _ = Dfn._load_v1_flat(f)

        # load definitions
        dfns: Dfns = {}
        for path in paths:
            with path.open() as f:
                dfn = Dfn.load(f, name=path.stem, common=common)
                dfns[path.stem] = dfn

        return dfns

    @staticmethod  # type: ignore[misc]
    def _load_all_v2(dfndir: PathLike) -> Dfns:
        paths: list[Path] = [p for p in dfndir.glob("*.toml") if p.stem not in ["common", "flopy"]]
        dfns: Dfns = {}
        for path in paths:
            with path.open(mode="rb") as f:
                dfn = Dfn.load(f, name=path.stem, version=2)
                dfns[path.stem] = dfn

        return dfns

    @staticmethod  # type: ignore[misc]
    def load_all(dfndir: PathLike, version: FormatVersion = 1) -> Dfns:
        """Load all component definitions from the given directory."""
        if version == 1:
            return Dfn._load_all_v1(dfndir)
        elif version == 2:
            return Dfn._load_all_v2(dfndir)
        else:
            raise ValueError(f"Unsupported version, expected one of {version.__args__}")

    @staticmethod  # type: ignore[misc]
    def load_tree(dfndir: PathLike, version: FormatVersion = 2) -> dict:
        """Load all definitions and return as hierarchical tree."""
        dfns = Dfn.load_all(dfndir, version)
        return infer_tree(dfns)


def infer_tree(dfns: dict[str, Dfn]) -> dict:
    """Infer the component hierarchy from definitions.

    Enforces single root requirement - must be exactly one component
    with no parent, and it must be named 'sim'.
    """
    roots = [name for name, dfn in dfns.items() if not dfn.get("parent")]

    if len(roots) != 1:
        raise ValueError(
            f"Expected exactly one root component, found {len(roots)}: {roots}"
        )

    root_name = roots[0]
    if root_name != "sim":
        raise ValueError(f"Root component must be named 'sim', found '{root_name}'")

    def add_children(node_name: str) -> dict[str, Any]:
        node = dict(dfns[node_name])
        children = [
            name for name, dfn in dfns.items() if dfn.get("parent") == node_name
        ]
        for child in children:
            node[child] = add_children(child)
        return node

    return {root_name: add_children(root_name)}


def get_dfns(owner: str, repo: str, ref: str, outdir: str | PathLike, verbose: bool = False):
    """Fetch definition files from the MODFLOW 6 repository."""
    url = f"https://github.com/{owner}/{repo}/archive/{ref}.zip"
    if verbose:
        print(f"Downloading MODFLOW 6 repository from {url}")
    with tempfile.TemporaryDirectory() as tmp:
        dl_path = download_and_unzip(url, Path(tmp), verbose=verbose)
        contents = list(dl_path.glob("modflow6-*"))
        proj_path = next(iter(contents), None)
        if not proj_path:
            raise ValueError(f"Missing proj dir in {dl_path}, found {contents}")
        if verbose:
            print("Copying dfns from download dir to output dir")
        shutil.copytree(proj_path / "doc" / "mf6io" / "mf6ivar" / "dfn", outdir, dirs_exist_ok=True)
