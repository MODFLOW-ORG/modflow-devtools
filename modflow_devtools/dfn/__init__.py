"""
MODFLOW 6 definition file tools.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field, replace
from itertools import groupby
from os import PathLike
from pathlib import Path
from typing import (
    Literal,
    cast,
)

import tomli
from boltons.dictutils import OMD
from boltons.iterutils import remap
from packaging.version import Version

from modflow_devtools.dfn.parse import (
    is_advanced_package,
    is_multi_package,
    parse_dfn,
    try_parse_bool,
    try_parse_parent,
)
from modflow_devtools.dfn.schema.block import Block, Blocks, block_sort_key
from modflow_devtools.dfn.schema.field import Field, Fields
from modflow_devtools.dfn.schema.ref import Ref
from modflow_devtools.dfn.schema.v1 import SCALAR_TYPES as V1_SCALAR_TYPES
from modflow_devtools.dfn.schema.v1 import FieldV1
from modflow_devtools.dfn.schema.v2 import FieldV2
from modflow_devtools.misc import drop_none_or_empty, try_literal_eval

__all__ = [
    # Core data models
    "Block",
    "Blocks",
    "Dfn",
    "Dfns",
    "DfnSpec",
    "Field",
    "FieldV1",
    "FieldV2",
    "Fields",
    "Ref",
    # Registry classes
    "DfnRegistry",
    "DfnRegistryDiscoveryError",
    "DfnRegistryError",
    "DfnRegistryNotFoundError",
    "LocalDfnRegistry",
    "RemoteDfnRegistry",
    # Loading and mapping functions
    "block_sort_key",
    "is_valid",
    "load",
    "load_flat",
    "load_tree",
    "map",
    "to_flat",
    "to_tree",
    # Registry functions
    "get_dfn",
    "get_dfn_path",
    "get_registry",
    "get_sync_status",
    "list_components",
    "sync_dfns",
]


Format = Literal["dfn", "toml"]
"""DFN serialization format."""


Dfns = dict[str, "Dfn"]


@dataclass
class Dfn:
    """
    MODFLOW 6 input component definition.
    """

    schema_version: Version
    name: str
    parent: str | None = None
    advanced: bool = False
    multi: bool = False
    ref: Ref | None = None
    blocks: Blocks | None = None
    children: Dfns | None = None

    @property
    def fields(self) -> Fields:
        """
        A combined map of fields from all blocks.

        Only top-level fields are included, no subfields of composites
        such as records or recarrays.
        """
        fields = []
        for block in (self.blocks or {}).values():
            for field in block.values():
                fields.append((field.name, field))

        # for now return a multidict to support duplicate field names.
        # TODO: change to normal dict after deprecating v1 schema
        return OMD(fields)

    def __post_init__(self):
        if not isinstance(self.schema_version, Version):
            self.schema_version = Version(str(self.schema_version))
        if self.blocks:
            self.blocks = dict(sorted(self.blocks.items(), key=block_sort_key))

    @classmethod
    def from_dict(cls, d: dict, strict: bool = False) -> "Dfn":
        """
        Create a Dfn instance from a dictionary.

        Parameters
        ----------
        d : dict
            Dictionary containing DFN data
        strict : bool, optional
            If True, raise ValueError if dict contains unrecognized keys at the
            top level or in nested field dicts. If False (default), ignore
            unrecognized keys.
        """
        keys = list(cls.__annotations__.keys())
        if strict:
            extra_keys = set(d.keys()) - set(keys)
            if extra_keys:
                raise ValueError(f"Unrecognized keys in DFN data: {extra_keys}")
        data = {k: v for k, v in d.items() if k in keys}
        schema_version = data.get("schema_version", Version("2"))
        field_cls = FieldV1 if schema_version == Version("1") else FieldV2

        def _fields(block_name, block_data):
            fields = {}
            for field_name, field_data in block_data.items():
                if isinstance(field_data, dict):
                    fields[field_name] = field_cls.from_dict(field_data, strict=strict)
                elif isinstance(field_data, field_cls):
                    fields[field_name] = field_data
                else:
                    raise TypeError(
                        f"Invalid field data for {field_name} in block {block_name}: "
                        f"expected dict or Field, got {type(field_data)}"
                    )
            return fields

        if blocks := data.get("blocks"):
            data["schema_version"] = schema_version
            data["blocks"] = {
                block_name: _fields(block_name, block_data)
                for block_name, block_data in blocks.items()
            }

        return cls(**data)


@dataclass
class DfnSpec(Mapping):
    """
    Full MODFLOW 6 input specification with hierarchical structure and flat dict access.

    The specification maintains a single canonical hierarchical representation via
    the `root` property (simulation component with nested children), while also
    providing flat dict-like access to any component by name via the Mapping protocol.

    Parameters
    ----------
    schema_version : Version
        The schema version of the specification (e.g., "1", "1.1", "2").
    root : Dfn
        The root component (simulation) with hierarchical children populated.

    Examples
    --------
    >>> spec = DfnSpec.load("/path/to/dfns")
    >>> spec.schema_version
    Version('2')
    >>> spec.root.name
    'sim-nam'
    >>> spec["gwf-chd"]  # Flat access by component name
    Dfn(name='gwf-chd', ...)
    >>> list(spec.keys())[:3]
    ['sim-nam', 'sim-tdis', 'gwf-nam']
    """

    schema_version: Version
    root: "Dfn"
    _flat: Dfns = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.schema_version, Version):
            self.schema_version = Version(str(self.schema_version))
        # Build flat index if not already populated
        if not self._flat:
            self._flat = to_flat(self.root)

    def __getitem__(self, name: str) -> "Dfn":
        """Get a component by name (flattened lookup)."""
        if name not in self._flat:
            raise KeyError(f"Component '{name}' not found in specification")
        return self._flat[name]

    def __iter__(self) -> Iterator[str]:
        """Iterate over all component names."""
        return iter(self._flat)

    def __len__(self) -> int:
        """Total number of components in the specification."""
        return len(self._flat)

    def __contains__(self, name: object) -> bool:
        """Check if a component exists by name."""
        return name in self._flat

    @classmethod
    def load(
        cls,
        path: str | PathLike,
        schema_version: str | Version | None = None,
    ) -> "DfnSpec":
        """
        Load a specification from a directory of DFN files.

        The specification is always loaded as a hierarchical tree,
        with flat access available via the Mapping protocol.

        Parameters
        ----------
        path : str or PathLike
            Path to directory containing DFN files.
        schema_version : str or Version, optional
            Target schema version. If provided and different from the native
            schema version, DFNs will be mapped to the target version.
            If not provided, uses the native schema version from the files.

        Returns
        -------
        DfnSpec
            The loaded specification with hierarchical structure.

        Examples
        --------
        >>> spec = DfnSpec.load("/path/to/dfns")
        >>> spec.root.name
        'sim-nam'
        >>> spec["gwf-dis"]
        Dfn(name='gwf-dis', ...)
        """
        path = Path(path).expanduser().resolve()

        # Load flat DFNs from directory
        dfns = load_flat(path)

        if not dfns:
            raise ValueError(f"No DFN files found in {path}")

        # Determine native schema version from first DFN
        first_dfn = next(iter(dfns.values()))
        native_version = first_dfn.schema_version

        # Determine target version:
        # - If explicitly specified, use that
        # - If native is v1, default to v2 (since to_tree only works with v2)
        # - Otherwise use native version
        if schema_version:
            target_version = Version(str(schema_version))
        elif native_version == Version("1"):
            target_version = Version("2")
        else:
            target_version = native_version

        if target_version != native_version:
            # Map DFNs to target schema version
            dfns = {name: map(dfn, target_version) for name, dfn in dfns.items()}

        # Build hierarchical tree
        root = to_tree(dfns)

        return cls(
            schema_version=target_version,
            root=root,
        )


class SchemaMap(ABC):
    @abstractmethod
    def map(self, dfn: Dfn) -> Dfn: ...


class MapV1To2(SchemaMap):
    @staticmethod
    def map_period_block(dfn: Dfn, block: Block) -> Block:
        """
        Convert a period block recarray to individual arrays, one per column.

        Extracts recarray fields and creates separate array variables. Gives
        each an appropriate grid- or tdis-aligned shape as opposed to sparse
        list shape in terms of maxbound as previously.
        """

        block = dict(block)
        fields = list(block.values())
        if fields[0].type == "list":
            assert len(fields) == 1
            recarray_name = fields[0].name
            block.pop(recarray_name, None)
            item = next(iter((fields[0].children or {}).values()))
            columns = dict(item.children or {})
        else:
            recarray_name = None
            columns = block

        cellid = columns.pop("cellid", None)
        for col_name, column in columns.items():
            old_dims = column.shape
            if old_dims:
                old_dims = old_dims[1:-1].split(",")  # type: ignore
            new_dims = ["nper"]
            if cellid:
                new_dims.append("nnodes")
            if old_dims:
                new_dims.extend([dim for dim in old_dims if dim != "maxbound"])
            block[col_name] = replace(column, shape=f"({', '.join(new_dims)})")

        return block

    @staticmethod
    def map_field(dfn: Dfn, field: Field) -> Field:
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

        fields = cast(OMD, dfn.fields)

        def _map_field(_field) -> Field:
            field_dict = asdict(_field)
            # parse booleans from strings. everything else can
            # stay a string except default values, which we'll
            # try to parse as arbitrary literals below, and at
            # some point types, once we introduce type hinting
            field_dict = {k: try_parse_bool(v) for k, v in field_dict.items()}
            _name = field_dict.pop("name")
            _type = field_dict.pop("type", None)
            shape = field_dict.pop("shape", None)
            shape = None if shape == "" else shape
            block = field_dict.pop("block", None)
            default = field_dict.pop("default_value", None)
            default = try_literal_eval(default) if _type != "string" else default
            description = field_dict.pop("description", "")

            def _row_field() -> Field:
                """Parse a table's record (row) field"""
                item_names = _type.split()[1:]
                item_types = [
                    f.type
                    for f in fields.values(multi=True)
                    if f.name in item_names and f.in_record
                ]
                n_item_names = len(item_names)
                if n_item_names < 1:
                    raise ValueError(f"Missing list definition: {_type}")

                # explicit record or keystring
                if n_item_names == 1 and (
                    item_types[0].startswith("record") or item_types[0].startswith("keystring")
                ):
                    return MapV1To2.map_field(dfn, next(iter(fields.getlist(item_names[0]))))

                # implicit record with all scalar fields
                if all(t in V1_SCALAR_TYPES for t in item_types):
                    children = _record_fields()
                    return FieldV2.from_dict(
                        {
                            **field_dict,
                            "name": _name,
                            "type": "record",
                            "block": block,
                            "children": children,
                            "description": description.replace(
                                "is the list of", "is the record of"
                            ),
                        }
                    )

                # implicit record with composite fields
                children = {
                    f.name: MapV1To2.map_field(dfn, f)
                    for f in fields.values(multi=True)
                    if f.name in item_names and f.in_record
                }
                first = next(iter(children.values()))
                if not first.type:
                    raise ValueError(f"Missing type for field: {first.name}")
                single = len(children) == 1
                item_type = "keystring" if single and "keystring" in first.type else "record"
                return FieldV2.from_dict(
                    {
                        "name": first.name if single else _name,
                        "type": item_type,
                        "block": block,
                        "children": first.children if single else children,
                        "description": description.replace(
                            "is the list of", f"is the {item_type} of"
                        ),
                        **field_dict,
                    }
                )

            def _union_fields() -> Fields:
                """Parse a union's fields"""
                names = _type.split()[1:]
                return {
                    f.name: MapV1To2.map_field(dfn, f)
                    for f in fields.values(multi=True)
                    if f.name in names and f.in_record
                }

            def _record_fields() -> Fields:
                """Parse a record's fields"""
                names = _type.split()[1:]
                result = {}
                for name in names:
                    matching = [
                        f
                        for f in fields.values(multi=True)
                        if f.name == name and f.in_record and not f.type.startswith("record")
                    ]
                    if matching:
                        result[name] = _map_field(matching[0])
                return result

            _field = FieldV2.from_dict(
                {
                    "name": _name,
                    "shape": shape,
                    "block": block,
                    "description": description,
                    "default": default,
                    **field_dict,
                }
            )

            if _type.startswith("recarray"):
                child = _row_field()
                _field.children = {child.name: child}
                _field.type = "list"

            elif _type.startswith("keystring"):
                _field.children = _union_fields()
                _field.type = "union"

            elif _type.startswith("record"):
                _field.children = _record_fields()
                _field.type = "record"

            # for now, we can tell a var is an array if its type
            # is scalar and it has a shape. once we have proper
            # typing, this can be read off the type itself.
            elif shape is not None and _type not in V1_SCALAR_TYPES:
                raise TypeError(f"Unsupported array type: {_type}")

            else:
                # Map v1 type names to v2 type names
                type_map = {
                    "double precision": "double",
                }
                _field.type = type_map.get(_type, _type)

            return _field

        return _map_field(field)

    @staticmethod
    def map_blocks(dfn: Dfn) -> Blocks:
        fields = {
            field.name: MapV1To2.map_field(dfn, field)
            for field in cast(OMD, dfn.fields).values(multi=True)
            if not field.in_record  # type: ignore
        }
        block_dicts = {
            block_name: {f.name: f for f in block}
            for block_name, block in groupby(fields.values(), lambda f: f.block)
        }
        blocks = {}

        # Handle period blocks specially
        if (period_block := block_dicts.get("period", None)) is not None:
            blocks["period"] = MapV1To2.map_period_block(dfn, period_block)

        for block_name, block_data in block_dicts.items():
            if block_name != "period":
                blocks[block_name] = block_data

        def remove_attrs(path, key, value):
            # remove unneeded variable attributes
            if key in ["in_record", "tagged", "preserve_case"]:
                return False
            return True

        return remap(blocks, visit=remove_attrs)

    def map(self, dfn: Dfn) -> Dfn:
        if dfn.schema_version == (v2 := Version("2")):
            return dfn

        return Dfn(
            name=dfn.name,
            advanced=dfn.advanced,
            multi=dfn.multi,
            ref=dfn.ref,
            blocks=MapV1To2.map_blocks(dfn),
            schema_version=v2,
            parent=dfn.parent,
        )


def map(
    dfn: Dfn,
    schema_version: str | Version = "2",
) -> Dfn:
    """Map a MODFLOW 6 specification to another schema version."""
    if dfn.schema_version == schema_version:
        return dfn
    elif Version(str(schema_version)) == Version("1"):
        raise NotImplementedError("Mapping to schema version 1 is not implemented yet.")
    elif Version(str(schema_version)) == Version("2"):
        return MapV1To2().map(dfn)
    raise ValueError(f"Unsupported schema version: {schema_version}. Expected 1 or 2.")


def load(f, format: str = "dfn", **kwargs) -> Dfn:
    """Load a MODFLOW 6 definition file."""
    if format == "dfn":
        name = kwargs.pop("name")
        fields, meta = parse_dfn(f, **kwargs)
        blocks = {
            block_name: {field["name"]: FieldV1.from_dict(field) for field in block}
            for block_name, block in groupby(fields.values(), lambda field: field["block"])
        }
        return Dfn(
            name=name,
            schema_version=Version("1"),
            parent=try_parse_parent(meta),
            advanced=is_advanced_package(meta),
            multi=is_multi_package(meta),
            blocks=blocks,
        )

    elif format == "toml":
        data = tomli.load(f)

        dfn_fields = {
            "name": data.pop("name", kwargs.pop("name", None)),
            "schema_version": Version(str(data.pop("schema_version", "2"))),
            "parent": data.pop("parent", None),
            "advanced": data.pop("advanced", False),
            "multi": data.pop("multi", False),
            "ref": data.pop("ref", None),
        }

        if (expected_name := kwargs.pop("name", None)) is not None:
            if dfn_fields["name"] != expected_name:
                raise ValueError(f"DFN name mismatch: {expected_name} != {dfn_fields['name']}")

        blocks = {}
        for section_name, section_data in data.items():
            if isinstance(section_data, dict):
                block_fields = {}
                for field_name, field_data in section_data.items():
                    if isinstance(field_data, dict):
                        block_fields[field_name] = FieldV2.from_dict(field_data)
                    else:
                        block_fields[field_name] = field_data
                blocks[section_name] = block_fields  # type: ignore

        dfn_fields["blocks"] = blocks if blocks else None

        return Dfn(**dfn_fields)

    raise ValueError(f"Unsupported format: {format}. Expected 'dfn' or 'toml'.")


def _load_common(f) -> Fields:
    common, _ = parse_dfn(f)
    return common


def load_flat(path: str | PathLike) -> Dfns:
    """
    Load a flat MODFLOW 6 specification from definition files in a directory.

    Returns a dictionary of unlinked DFNs, i.e. without `children` populated.
    Components will have `parent` populated if the schema is v2 but not if v1.
    """
    exclude = ["common", "flopy"]
    path = Path(path).expanduser().resolve()
    dfn_paths = {p.stem: p for p in path.glob("*.dfn") if p.stem not in exclude}
    toml_paths = {p.stem: p for p in path.glob("*.toml") if p.stem not in exclude}
    dfns = {}
    if dfn_paths:
        with (path / "common.dfn").open() as f:
            common = _load_common(f)
        for dfn_name, dfn_path in dfn_paths.items():
            with dfn_path.open() as f:
                dfns[dfn_name] = load(f, name=dfn_name, common=common, format="dfn")
    if toml_paths:
        for toml_name, toml_path in toml_paths.items():
            with toml_path.open("rb") as f:
                dfns[toml_name] = load(f, name=toml_name, format="toml")
    return dfns


def load_tree(path: str | PathLike) -> Dfn:
    """
    Load a structured MODFLOW 6 specification from definition files in a directory.

    A single root component definition (the simulation) is returned. This contains
    child (and grandchild) components for the relevant models and packages.
    """
    return to_tree(load_flat(path))


def to_tree(dfns: Dfns) -> Dfn:
    """
    Infer the MODFLOW 6 input component hierarchy from a flat spec:
    unlinked DFNs, i.e. without `children` populated, only `parent`.

    Returns the root component. There must be exactly one root, i.e.
    component with no `parent`. Composite components have `children`
    populated.

    Assumes DFNs are already in v2 schema, just lacking parent-child
    links; before calling this function, map them first with `map()`.
    """

    def set_parent(dfn):
        dfn = asdict(dfn)
        if (dfn_name := dfn["name"]) == "sim-nam":
            pass
        elif dfn_name.endswith("-nam"):
            dfn["parent"] = "sim-nam"
        elif (
            dfn_name.startswith("exg-")
            or dfn_name.startswith("sln-")
            or dfn_name.startswith("utl-")
        ):
            dfn["parent"] = "sim-nam"
        elif "-" in dfn_name:
            mdl = dfn_name.split("-")[0]
            dfn["parent"] = f"{mdl}-nam"

        return Dfn(**remap(dfn, visit=drop_none_or_empty))

    dfns = {name: set_parent(dfn) for name, dfn in dfns.items()}
    first_dfn = next(iter(dfns.values()), None)
    match schema_version := str(first_dfn.schema_version if first_dfn else Version("1")):
        case "1":
            raise NotImplementedError("Tree inference from v1 schema not implemented")
        case "2":
            if (
                nroots := len(
                    roots := {name: dfn for name, dfn in dfns.items() if dfn.parent is None}
                )
            ) != 1:
                raise ValueError(f"Expected one root component, found {nroots}")

            def _build_tree(node_name: str) -> Dfn:
                node = dfns[node_name]
                children = {name: dfn for name, dfn in dfns.items() if dfn.parent == node_name}
                if any(children):
                    node.children = {name: _build_tree(name) for name in children.keys()}
                return node

            return _build_tree(next(iter(roots.keys())))
        case _:
            raise ValueError(f"Unsupported schema version: {schema_version}. Expected 1 or 2.")


def to_flat(dfn: Dfn) -> Dfns:
    """
    Flatten a MODFLOW 6 input component hierarchy to a flat spec:
    unlinked DFNs, i.e. without `children` populated, only `parent`.

    Returns a dictionary of all components in the specification.
    """

    def _flatten(dfn: Dfn) -> Dfns:
        dfns = {dfn.name: replace(dfn, children=None)}
        for child in (dfn.children or {}).values():
            dfns.update(_flatten(child))
        return dfns

    return _flatten(dfn)


def is_valid(path: str | PathLike, format: str = "dfn", verbose: bool = False) -> bool:
    """Validate DFN file(s)."""
    path = Path(path).expanduser().absolute()
    try:
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        if path.is_file():
            common = {}  # type: ignore
            if (common_path := path.parent / "common.dfn").exists():
                with common_path.open() as f:
                    common, _ = parse_dfn(f)
                if path.name == "common.dfn":
                    return True
            with path.open() as f:
                load(f, name=path.stem, common=common, format=format)
        else:
            load_flat(path)
        return True
    except Exception as e:
        if verbose:
            print(f"Validation failed: {e}")
        return False


# =============================================================================
# Registry imports and convenience functions
# =============================================================================

# Import registry classes and functions (lazy to avoid circular imports)
# These are re-exported for convenience


def _get_registry_module():
    """Lazy import of registry module to avoid circular imports."""
    from modflow_devtools.dfn import registry

    return registry


# Re-export registry classes
def __getattr__(name: str):
    """Lazy attribute access for registry classes."""
    registry_exports = {
        "DfnRegistry",
        "DfnRegistryDiscoveryError",
        "DfnRegistryError",
        "DfnRegistryNotFoundError",
        "LocalDfnRegistry",
        "RemoteDfnRegistry",
        "get_registry",
        "get_sync_status",
        "sync_dfns",
    }
    if name in registry_exports:
        registry = _get_registry_module()
        return getattr(registry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# =============================================================================
# Module-level convenience functions
# =============================================================================


def get_dfn(
    component: str,
    ref: str = "develop",
    source: str = "modflow6",
) -> "Dfn":
    """
    Get a DFN by component name from the registry.

    This is a convenience function that gets the registry and retrieves
    the specified component.

    Parameters
    ----------
    component : str
        Component name (e.g., "gwf-chd", "sim-nam").
    ref : str, optional
        Git ref (branch, tag, or commit hash). Default is "develop".
    source : str, optional
        Source repository name. Default is "modflow6".

    Returns
    -------
    Dfn
        The requested component definition.

    Examples
    --------
    >>> dfn = get_dfn("gwf-chd")
    >>> dfn = get_dfn("gwf-chd", ref="6.6.0")
    """
    registry = _get_registry_module()
    reg = registry.get_registry(source=source, ref=ref)
    return reg.get_dfn(component)


def get_dfn_path(
    component: str,
    ref: str = "develop",
    source: str = "modflow6",
) -> Path:
    """
    Get the local cached file path for a DFN component.

    Parameters
    ----------
    component : str
        Component name (e.g., "gwf-chd", "sim-nam").
    ref : str, optional
        Git ref (branch, tag, or commit hash). Default is "develop".
    source : str, optional
        Source repository name. Default is "modflow6".

    Returns
    -------
    Path
        Path to the local cached DFN file.

    Examples
    --------
    >>> path = get_dfn_path("gwf-chd", ref="6.6.0")
    """
    registry = _get_registry_module()
    reg = registry.get_registry(source=source, ref=ref)
    return reg.get_dfn_path(component)


def list_components(
    ref: str = "develop",
    source: str = "modflow6",
) -> list[str]:
    """
    List available components for a registry.

    Parameters
    ----------
    ref : str, optional
        Git ref (branch, tag, or commit hash). Default is "develop".
    source : str, optional
        Source repository name. Default is "modflow6".

    Returns
    -------
    list[str]
        List of component names available in the registry.

    Examples
    --------
    >>> components = list_components(ref="6.6.0")
    >>> "gwf-chd" in components
    True
    """
    registry = _get_registry_module()
    reg = registry.get_registry(source=source, ref=ref)
    return list(reg.spec.keys())
