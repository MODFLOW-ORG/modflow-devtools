from ast import literal_eval
from typing import Any
from warnings import warn

from boltons.dictutils import OMD


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
    if k == "default_value":
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


def try_parse_bool(value: Any) -> Any:
    """
    Try to parse a boolean from a string as represented
    in a DFN file, otherwise return the value unaltered.
    1. `"true"` -> `True`
    2. `"false"` -> `False`
    3. anything else -> `value`
    """
    if isinstance(value, str):
        value = value.lower()
        if value in ["true", "false"]:
            return value == "true"
    return value


def try_parse_parent(meta: list[str]) -> str | None:
    """
    Try to parse a component's parent component name from its metadata.
    Return `None` if it has no parent specified.
    """
    line = next(
        iter(m for m in meta if isinstance(m, str) and m.startswith("parent")),
        None,
    )
    if not line:
        return None
    split = line.split()
    return split[1]


def is_advanced_package(meta: list[str]) -> bool:
    """Determine if the component is an advanced package from its metadata."""
    return any("package-type advanced" in m for m in meta)


def is_multi_package(meta: list[str]) -> bool:
    """Determine if the component is a multi-package from its metadata."""
    return any("multi-package" in m for m in meta)


def parse_mf6_subpackages(meta: list[str]) -> list[str]:
    """
    Return MF6 subpackage abbreviations declared via '# mf6 subpackage <abbr>'.

    These declarations specify schema-level composition constraints: which component
    types can be children of this component. For example, '# mf6 subpackage utl-ncf'
    in gwf-dis.dfn means a gwf-dis component can have utl-ncf child components.

    This is distinct from flopy subpackages ('# flopy subpackage <key> <abbr> ...'),
    which define field-level foreign key references where specific fields reference
    other components via file paths.

    Parameters
    ----------
    meta : list[str]
        Metadata lines extracted from DFN file comments.

    Returns
    -------
    list[str]
        List of uppercase component abbreviations (e.g., ['UTL-NCF']).

    See Also
    --------
    Dfn.subcomponents : Stores the result (schema-level constraint).
    Dfn.fkeys : Field-level foreign keys from flopy subpackage declarations.
    """
    result = []
    for m in meta:
        if m.startswith("mf6-subpackage "):
            abbr = m.removeprefix("mf6-subpackage ").strip().upper()
            result.append(abbr)
    return result


def parse_dfn(f, common: dict | None = None) -> tuple[OMD, list[str]]:
    """
    Parse a DFN file into an ordered dict of fields and a list of metadata.

    Parameters
    ----------
    f : readable file-like
        A file-like object to read the DFN file from.
    common : dict, optional
        A dictionary of common variable definitions to use for
        description substitutions, by default None.

    Returns
    -------
    tuple[OMD, list[str]]
        A tuple containing an ordered multi-dict of fields and a list of metadata.

    Notes
    -----
    A DFN file consists of field definitions (each as a set of attributes) and a
    number of comment lines either a) containing metadata about the component or
    b) delimiting variables into blocks. This parser reads the file line-by-line
    and saves component metadata and field attributes, ignoring block delimiters;
    There is a `block` attribute on each field anyway so delimiters are unneeded.

    The returned ordered multi-dict (OMD) maps names to dicts of their attributes,
    with duplicate field names allowed. This is important because some DFN files
    have fields with the same name defined multiple times for different purposes
    (e.g., an `auxiliary` options block keyword, and column in the period block).

    """

    common = common or {}
    field: dict = {}
    fields: list = []
    metadata: list = []

    for line in f:
        # parse metadata line
        if (line := line.strip()).startswith("#"):
            _, sep, tail = line.partition("flopy")
            if sep == "flopy":
                if (
                    "multi-package" in tail
                    or "solution_package" in tail
                    or "subpackage" in tail
                    or "parent" in tail
                ):
                    metadata.append(tail.strip())
            _, sep, tail = line.partition("package-type")
            if sep == "package-type":
                metadata.append(f"package-type {tail.strip()}")
            # Parse mf6 subpackage declarations (schema-level composition constraints).
            # Distinct from flopy subpackage (field-level foreign keys, parsed above).
            _, sep, tail = line.partition("mf6 subpackage")
            if sep == "mf6 subpackage":
                metadata.append(f"mf6-subpackage {tail.strip()}")
            continue

        # if we hit a newline and the field has attributes,
        # we've reached the end of the field. Save it.
        if not any(line):
            if any(field):
                fields.append((field["name"], field))
                field = {}
            continue

        # parse field attribute
        key, _, value = line.partition(" ")
        field[key] = value

        # if this is the description attribute, substitute
        # from common variable definitions if needed. drop
        # backslashes too, TODO: generate/insert citations.
        if key == "description":
            descr = value.replace("\\", "").replace("``", "'").replace("''", "'")
            _, replace, tail = descr.strip().partition("REPLACE")
            if replace:
                key, _, subs = tail.strip().partition(" ")
                subs = literal_eval(subs)
                cmmn = common.get(key, None)
                if cmmn is None:
                    warn(f"Can't substitute description text, common variable not found: {key}")
                else:
                    descr = cmmn["description"]
                    if any(subs):
                        descr = descr.replace("\\", "").replace("{#1}", subs["{#1}"])  # type: ignore
            field["description"] = descr

    # Save the last field if needed.
    if any(field):
        fields.append((field["name"], field))

    return OMD(fields), metadata
