"""
DFN tools. Includes a legacy parser as well as TOML,
and a utility to fetch DFNs from the MF6 repository.
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
    Union,
)
from warnings import warn

import tomli
from boltons.dictutils import OMD

from modflow_devtools.download import download_and_unzip


def _try_literal_eval(value: str) -> Any:
    """
    Try to parse a string as a literal. If this fails,
    return the value unaltered.
    """
    try:
        return literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _try_parse_bool(value: Any) -> Any:
    """
    Try to parse a boolean from a string as represented
    in a DFN file, otherwise return the value unaltered.
    """
    if isinstance(value, str):
        value = value.lower()
        if value in ["true", "false"]:
            return value == "true"
    return value


_MF6_SCALARS = {
    "keyword",
    "integer",
    "double precision",
    "string",
}


DfnFmtVersion = Literal[1, 2]
"""DFN format version number."""


Dfns = dict[str, "Dfn"]
Vars = dict[str, "Var"]


class Var(TypedDict):
    """A variable specification."""

    name: str
    type: str
    shape: Optional[Any] = None
    block: Optional[str] = None
    default: Optional[Any] = None
    children: Optional["Vars"] = None
    description: Optional[str] = None


class Sub(TypedDict):
    """
    A subpackage specification.

    A foreign-key-like reference between a file input variable
    in a referring input component and another input component.

    A `Dfn` which declares itself a subpackage can be referred
    to by other definitions, via a filepath variable acting as
    a foreign key. The referring component's `__init__` method
    is modified, the subpackage variable named `val` replacing
    the `key` parameter, such that the referring component can
    accept data for the subpackage directly instead of by file.
    """

    key: str
    val: str
    abbr: str
    param: str
    parent: str
    description: Optional[str]


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
    a model or package, containing input variables.
    """

    name: str
    advanced: bool = False
    multi: bool = False
    sub: Optional[Sub] = None
    sln: Optional[Sln] = None
    blocks: Optional[dict[str, Vars]] = None
    fkeys: Optional[Dfns] = None

    @staticmethod
    def _load_v1_flat(f, common: Optional[dict] = None) -> tuple[Mapping, list[str]]:
        var = {}
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
                if any(var):
                    flat.append((var["name"], var))
                    var = {}
                continue

            # split the attribute's key and value and
            # store it in the parameter dictionary
            key, _, value = line.partition(" ")
            if key == "default_value":
                key = "default"
            var[key] = value

            # make substitutions from common variable definitions,
            # remove backslashes, TODO: generate/insert citations.
            descr = var.get("description", None)
            if descr:
                descr = descr.replace("\\", "").replace("``", "'").replace("''", "'")
                _, replace, tail = descr.strip().partition("REPLACE")
                if replace:
                    key, _, subs = tail.strip().partition(" ")
                    subs = literal_eval(subs)
                    cvar = common.get(key, None)
                    if cvar is None:
                        warn(
                            "Can't substitute description text, "
                            f"common variable not found: {key}"
                        )
                    else:
                        descr = cvar.get("description", "")
                        if any(subs):
                            descr = descr.replace("\\", "").replace(
                                "{#1}", subs["{#1}"]
                            )
                var["description"] = descr

        # add the final parameter
        if any(var):
            flat.append((var["name"], var))

        # the point of the OMD is to losslessly handle duplicate variable names
        return OMD(flat), meta

    @classmethod
    def _load_v1(cls, f, name, **kwargs) -> "Dfn":
        """
        Temporary load routine for the v1 DFN format.
        """

        # if we have any subpackage references
        # we need to watch for foreign key vars
        # (file input vars) and register matches
        refs = kwargs.pop("refs", {})
        fkeys = {}

        # load dfn as flat multidict + str metadata
        flat, meta = Dfn._load_v1_flat(f, **kwargs)

        def _load_variable(var: dict[str, Any]) -> Var:
            """
            Convert an input variable from its original representation
            in a definition file to a structured, Python-friendly form.

            This involves trimming unneeded attributes and setting
            some others.

            Notes
            -----
            If a variable does not have a `default` attribute, it will
            default to `False` if it is a keyword, otherwise to `None`.

            A filepath variable whose name functions as a foreign key
            for a separate context will be given a reference to it.
            """

            var = var.copy()

            # parse booleans from strings. everything else can
            # stay a string except default values, which we'll
            # try to parse as arbitrary literals below, and at
            # some point types, once we introduce type hinting
            var = {k: _try_parse_bool(v) for k, v in var.items()}

            _name = var.pop("name")
            _type = var.pop("type", None)
            shape = var.pop("shape", None)
            shape = None if shape == "" else shape
            block = var.pop("block", None)
            default = var.pop("default", None)
            default = _try_literal_eval(default) if _type != "string" else default
            description = var.pop("description", "")
            ref = refs.get(_name, None)

            # if var is a foreign key, register it
            if ref:
                fkeys[_name] = ref

            def _items() -> Vars:
                """Load a list's items."""

                names = _type.split()[1:]
                types = [
                    v["type"]
                    for v in flat.values(multi=True)
                    if v["name"] in names and v.get("in_record", False)
                ]
                n_names = len(names)
                if n_names < 1:
                    raise ValueError(f"Missing recarray definition: {_type}")

                # list input can have records or unions as rows. lists
                # that have a consistent item type can be considered
                # tabular. lists that can possess multiple item types
                # (unions) are considered irregular. regular lists can
                # be defined with a nested record (explicit) or with a
                # set of fields directly in the recarray (implicit). an
                # irregular list is always defined with a nested union.
                is_explicit = n_names == 1 and (
                    types[0].startswith("record") or types[0].startswith("keystring")
                )

                if is_explicit:
                    child = next(iter(flat.getlist(names[0])))
                    return {names[0]: _load_variable(child)}
                elif all(t in _MF6_SCALARS for t in types):
                    # implicit simple record (all fields are scalars)
                    fields = _fields()
                    return {
                        _name: Var(
                            name=_name,
                            type="record",
                            block=block,
                            fields=fields,
                            description=description.replace(
                                "is the list of", "is the record of"
                            ),
                            **var,
                        )
                    }
                else:
                    # implicit complex record (some fields are records or unions)
                    fields = {
                        v["name"]: _load_variable(v)
                        for v in flat.values(multi=True)
                        if v["name"] in names and v.get("in_record", False)
                    }
                    first = next(iter(fields.values()))
                    single = len(fields) == 1
                    name_ = first["name"] if single else _name
                    child_type = (
                        "union" if single and "keystring" in first["type"] else "record"
                    )
                    return {
                        name_: Var(
                            name=name_,
                            type=child_type,
                            block=block,
                            fields=first["fields"] if single else fields,
                            description=description.replace(
                                "is the list of", f"is the {child_type} of"
                            ),
                            **var,
                        )
                    }

            def _choices() -> Vars:
                """Load a union's choices."""
                names = _type.split()[1:]
                return {
                    v["name"]: _load_variable(v)
                    for v in flat.values(multi=True)
                    if v["name"] in names and v.get("in_record", False)
                }

            def _fields() -> Vars:
                """Load a record's fields."""
                names = _type.split()[1:]
                fields = {}
                for name in names:
                    v = flat.get(name, None)
                    if (
                        not v
                        or not v.get("in_record", False)
                        or v["type"].startswith("record")
                    ):
                        continue
                    fields[name] = v
                return fields

            var_ = Var(
                name=_name,
                shape=shape,
                block=block,
                description=description,
                default=default,
                **var,
            )

            if _type.startswith("recarray"):
                var_["items"] = _items()
                var_["type"] = "list"

            elif _type.startswith("keystring"):
                var_["choices"] = _choices()
                var_["type"] = "union"

            elif _type.startswith("record"):
                var_["fields"] = _fields()
                var_["type"] = "record"

            # for now, we can tell a var is an array if its type
            # is scalar and it has a shape. once we have proper
            # typing, this can be read off the type itself.
            elif shape is not None and _type not in _MF6_SCALARS:
                raise TypeError(f"Unsupported array type: {_type}")

            else:
                var_["type"] = _type

            # if var is a foreign key, return subpkg var instead
            if ref:
                return Var(
                    name=ref["param" if name == ("sim", "nam") else "val"],
                    type=_type,
                    shape=shape,
                    block=block,
                    description=(
                        f"Contains data for the {ref['abbr']} package. Data can be "
                        f"stored in a dictionary containing data for the {ref['abbr']} "
                        "package with variable names as keys and package data as "
                        f"values. Data just for the {ref['val']} variable is also "
                        f"acceptable. See {ref['abbr']} package documentation for more "
                        "information"
                    ),
                    default=None,
                    subpackage=ref,
                    **var,
                )

            return var_

        # load top-level variables. any nested
        # variables will be loaded recursively
        vars_ = {
            var["name"]: _load_variable(var)
            for var in flat.values(multi=True)
            if not var.get("in_record", False)
        }

        # group variables by block
        blocks = {
            name: {v["name"]: v for v in block}
            for name, block in groupby(vars_.values(), lambda v: v["block"])
        }

        def _advanced() -> Optional[bool]:
            return any("package-type advanced" in m for m in meta)

        def _multi() -> bool:
            return any("multi-package" in m for m in meta)

        def _sln() -> Optional[Sln]:
            sln = next(
                iter(
                    m
                    for m in meta
                    if isinstance(m, str) and m.startswith("solution_package")
                ),
                None,
            )
            if sln:
                abbr, pattern = sln.split()[1:]
                return Sln(abbr=abbr, pattern=pattern)
            return None

        def _sub() -> Optional[Sub]:
            def _parent():
                line = next(
                    iter(
                        m for m in meta if isinstance(m, str) and m.startswith("parent")
                    ),
                    None,
                )
                if not line:
                    return None
                split = line.split()
                return split[1]

            def _rest():
                line = next(
                    iter(
                        m for m in meta if isinstance(m, str) and m.startswith("subpac")
                    ),
                    None,
                )
                if not line:
                    return None
                _, key, abbr, param, val = line.split()
                matches = [v for v in vars_.values() if v["name"] == val]
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
                return Sub(parent=parent, **rest)
            return None

        return cls(
            name=name,
            fkeys=fkeys,
            advanced=_advanced(),
            multi=_multi(),
            sln=_sln(),
            sub=_sub(),
            blocks=blocks,
        )

    @classmethod
    def _load_v2(cls, f, name) -> "Dfn":
        data = tomli.load(f)
        if name and name != data.get("name", None):
            raise ValueError(f"Name mismatch, expected {name}")
        return cls(**data)

    @classmethod
    def load(
        cls,
        f,
        name: Optional[str] = None,
        version: DfnFmtVersion = 1,
        **kwargs,
    ) -> "Dfn":
        """
        Load a component definition from a DFN file.
        """

        if version == 1:
            return cls._load_v1(f, name, **kwargs)
        elif version == 2:
            return cls._load_v2(f, name)
        else:
            raise ValueError(f"Unsupported version, expected one of {version.__args__}")

    @staticmethod
    def _load_all_v1(dfndir: PathLike) -> Dfns:
        # find definition files
        paths: list[Path] = [
            p for p in dfndir.glob("*.dfn") if p.stem not in ["common", "flopy"]
        ]

        # load common variables
        common_path: Optional[Path] = dfndir / "common.dfn"
        if not common_path.is_file:
            common = None
        else:
            with common_path.open() as f:
                common, _ = Dfn._load_v1_flat(f)

        # load subpackages
        refs = {}
        for path in paths:
            with path.open() as f:
                dfn = Dfn.load(f, name=path.stem, common=common)
                subpkg = dfn.get("subpackage", None)
                if subpkg:
                    refs[subpkg["key"]] = subpkg

        # load definitions
        dfns: Dfns = {}
        for path in paths:
            with path.open() as f:
                dfn = Dfn.load(f, name=path.stem, common=common, refs=refs)
                dfns[path.stem] = dfn

        return dfns

    @staticmethod
    def _load_all_v2(dfndir: PathLike) -> Dfns:
        # find definition files
        paths: list[Path] = [
            p for p in dfndir.glob("*.toml") if p.stem not in ["common", "flopy"]
        ]

        # load definitions
        dfns: Dfns = {}
        for path in paths:
            with path.open(mode="rb") as f:
                dfn = Dfn.load(f, name=path.stem, version=2)
                dfns[path.stem] = dfn

        return dfns

    @staticmethod
    def load_all(dfndir: PathLike, version: DfnFmtVersion = 1) -> Dfns:
        """Load all component definitions from the given directory."""
        if version == 1:
            return Dfn._load_all_v1(dfndir)
        elif version == 2:
            return Dfn._load_all_v2(dfndir)
        else:
            raise ValueError(f"Unsupported version, expected one of {version.__args__}")


def get_dfns(
    owner: str, repo: str, ref: str, outdir: Union[str, PathLike], verbose: bool = False
):
    """Fetch definition files from the MODFLOW 6 repository."""
    url = f"https://github.com/{owner}/{repo}/archive/{ref}.zip"
    if verbose:
        print(f"Downloading MODFLOW 6 repository from {url}")
    with tempfile.TemporaryDirectory() as tmp:
        dl_path = download_and_unzip(url, tmp, verbose=verbose)
        contents = list(dl_path.glob("modflow6-*"))
        proj_path = next(iter(contents), None)
        if not proj_path:
            raise ValueError(f"Missing proj dir in {dl_path}, found {contents}")
        if verbose:
            print("Copying dfns from download dir to output dir")
        shutil.copytree(
            proj_path / "doc" / "mf6io" / "mf6ivar" / "dfn", outdir, dirs_exist_ok=True
        )
