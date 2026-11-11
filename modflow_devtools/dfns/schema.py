import ast
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from boltons.dictutils import OMD
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    SerializationInfo,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic import (
    Field as PydanticField,
)
from pydantic.json_schema import SkipJsonSchema

CURRENT_SCHEMA_VERSION = "2.0.0.dev3"


class InputFieldBase(BaseModel):
    name: str
    longname: str | None = None
    description: str | None = None
    optional: bool = False
    # The name of a keyword in the component's options block that switches
    # this field on: it is absent unless the keyword is set. Then `optional`
    # says whether it may still be left out (a boundname may be, EVT's `petm0`
    # may not). Unlike a column sized by `shape` (`aux`, a count that may be
    # 0), this decides whether the field is there at all. None if no option
    # decides it.
    when: str | None = None
    default: Any | None = None
    developmode: bool = False
    netcdf: bool = False
    tagged: bool = True
    # Version this field was deprecated/removed as of (e.g. "6.6.0"), or None if
    # neither. MF6 may still parse a deprecated field; a removed one no longer
    # parses at all. Both are excluded from render() unconditionally — never
    # shown as valid current syntax — but kept as data for other consumers (e.g.
    # a linter that wants to warn on deprecated-but-still-accepted input).
    removed: str | None = None
    deprecated: str | None = None

    @field_validator("default", mode="before")
    @classmethod
    def _freeze_default(cls, v: Any) -> Any:
        # TOML/JSON/YAML have no tuples, so a tuple default (e.g. sim-tdis
        # `perioddata`) comes back as a list. Normalize to tuples so a default
        # is the same immutable value whichever format it was loaded from.
        def freeze(x: Any) -> Any:
            return tuple(freeze(i) for i in x) if isinstance(x, list) else x

        return freeze(v)

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        if info.context and info.context.get("strip_names"):
            data.pop("name", None)
        # `type` has a frozen default so exclude_defaults=True drops it; restore it.
        if "type" not in data and "type" in type(self).model_fields:
            data = {"type": getattr(self, "type"), **data}
        return data

    def dump(self, *, strip_names: bool = True, **kwargs) -> dict[str, Any]:
        if strip_names:
            kwargs["context"] = {**(kwargs.get("context") or {}), "strip_names": True}
        return self.model_dump(**kwargs)

    def dump_json(self, *, strip_names: bool = True, **kwargs) -> str:
        if strip_names:
            kwargs["context"] = {**(kwargs.get("context") or {}), "strip_names": True}
        return self.model_dump_json(**kwargs)

    def render(self, *, inline: bool = False) -> str:
        """Render this field as MF6IO-style template text.

        No block indentation is baked in — a multi-line result (a shaped
        ``Array``, a top-level ``Union``) is indented only relative to its
        own first line; callers composing a field's render into a larger
        template (e.g. ``Block``) are responsible for prefixing every line
        with their own indent.

        ``inline=True`` renders the field as a bare token for use inside a
        parent ``Record``/``List`` row rather than owning its own row(s). It
        only changes output for ``Array`` (with ``shape``) and ``Union`` —
        every other field type renders identically either way. ``List`` has
        no inline form and raises if called with ``inline=True``.
        """
        return _render_field(cast("InputField", self), inline=inline)


class _DerivedTagged(InputFieldBase):
    """A field whose `tagged` follows from its type, not declared. A field is
    tagged iff it begins with a keyword: a scalar or array declares whether
    its own name precedes it, but a keyword always begins with itself, and a
    composite begins with whatever its parts begin with (see `_item_tags`).
    Never serialized. A hidden field rather than a property because pydantic
    can't override an inherited field with one, so it's re-derived wherever
    pydantic skips validation (see `model_copy`)."""

    tagged: SkipJsonSchema[bool] = PydanticField(default=False, exclude=True)

    def _derive_tagged(self) -> bool:
        raise NotImplementedError

    @model_validator(mode="after")
    def _set_tagged(self) -> "_DerivedTagged":
        tagged = self._derive_tagged()
        if "tagged" in self.model_fields_set and self.tagged != tagged:
            raise ValueError(
                f"{type(self).__name__} {self.name!r}: tagged={self.tagged!r} contradicts "
                f"its type, which {'begins' if tagged else 'does not begin'} with a keyword"
            )
        object.__setattr__(self, "tagged", tagged)
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False):
        if update and "tagged" in update:
            raise ValueError(
                f"{type(self).__name__} {self.name!r}: tagged is derived, not settable"
            )
        copy = super().model_copy(update=update, deep=deep)
        object.__setattr__(copy, "tagged", copy._derive_tagged())
        return copy


class Keyword(_DerivedTagged):
    type: Literal["keyword"] = PydanticField(default="keyword", frozen=True)
    aliases: list[str] = []

    def _derive_tagged(self) -> bool:
        return True


_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")

# Named rules an fk or a parameter can carry (see `ForeignKey.rule`,
# `Param.rule`): constraints the spec states in prose (`docs/md/dfnspec.md`,
# "Rules") and consumers implement in code, like JSON Schema's `format`.
# Each names a subset of the target that the value must fall in, which no
# path, scope or parameter can say. A consumer that doesn't implement a rule
# skips its check.
RULES: dict[str, str] = {
    "flow_model": (
        "in the flow model a GWF-GWT or GWF-GWE exchange pairs with this "
        "transport model (exg-gwfgwt.f90:124-129); unchecked with flows from "
        "a budget file"
    ),
    "no_advanced_transport": (
        "a flow package with no advanced transport package paired with it, "
        "since SSM then doesn't apply the SPC file it binds (tsp-ssm.f90:195); "
        "with one, the file is unchecked"
    ),
    "mover_enabled": (
        "a package that plays mover_provider or mover_receiver, i.e. whose "
        "mover key sets are switched on by their when (MOVER) "
        "(gwf-mvr.f90:942-971)"
    ),
}


class PrimaryKey(BaseModel):
    """A list item column's key: rows are unique by it. With a `scope`, the
    name of a sibling column, rows are unique by (scope, key) instead, e.g.
    MVR's `pname` within `mname`. Written `pk = true` when unscoped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str | None = None


class ForeignKey(BaseModel):
    """A reference to a `pk` column (or a string array's entries), one of:

    - `path`, `[component.]block.field`. With a `scope`, the name of a
      sibling column, that column qualifies the reference: within a
      component, it matches the target pk's own scope; across components, it
      picks the target component's instance. Written `fk = "<path>"` when
      unscoped.
    - `key`, with a `scope`, `rule` or `param`: a key set (see `KeySet`)
      that the component of the picked instance declares, by name, in its
      `keys`. For an instance whose type is known only at runtime (MVR's
      `id1`). The reserved key `observations` is the instance's observation
      types (see `ComponentBase.observations`), which every component with
      any declares.
    - `param` alone, one or more of this component's parameters (see
      `Param`): the value names the instance one of them is set to (MVR's
      `mname1`: `model1` or `model2`).

    With a `key`, `param` names the parameter whose instance declares the
    key set (SPC's `bndno`: `target`).

    A `rule` (see `RULES`) names a subset of the target the value must fall
    in. It may stand in for a `scope` (SSM's `pname`: `flow_model`) or
    restrict a scoped target further (MVR's `packages.pname`:
    `mover_enabled`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    scope: str | None = None
    key: str | None = None
    rule: str | None = None
    param: str | tuple[str, ...] | None = None

    @field_validator("param", mode="before")
    @classmethod
    def _check_param(cls, v: Any) -> Any:
        if isinstance(v, list | tuple):
            v = tuple(v)
            if not v:
                raise ValueError("an fk's param needs at least one parameter")
            if len(v) == 1:
                v = v[0]
            elif len(set(v)) != len(v):
                raise ValueError(f"fk params {list(v)!r} repeat a parameter")
        for name in (v,) if isinstance(v, str) else v or ():
            if not isinstance(name, str) or not _IDENT_RE.match(name):
                raise ValueError(f"fk param {name!r} must be a parameter name")
        return v

    @property
    def params(self) -> tuple[str, ...]:
        """The parameters `param` names, none or more."""
        if self.param is None:
            return ()
        return (self.param,) if isinstance(self.param, str) else self.param

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = v.split(".")
        if len(parts) not in (2, 3) or not all(parts):
            raise ValueError(
                f"fk path {v!r} must be a hierarchical path ('[component.]block.field')"
            )
        return v

    @field_validator("key")
    @classmethod
    def _check_key(cls, v: str | None) -> str | None:
        if v is not None and not _IDENT_RE.match(v):
            raise ValueError(f"fk key {v!r} must be a key set name")
        return v

    @field_validator("rule")
    @classmethod
    def _check_rule(cls, v: str | None) -> str | None:
        if v is not None and v not in RULES:
            raise ValueError(f"fk rule {v!r} is not one of {sorted(RULES)!r}")
        return v

    @model_validator(mode="after")
    def _check_form(self) -> "ForeignKey":
        if self.path is not None:
            if self.key is not None or self.param is not None:
                raise ValueError("an fk with a path can't have a key or param")
            return self
        if self.key is not None:
            pickers = [a for a in ("scope", "param") if getattr(self, a) is not None]
            if len(pickers) > 1:
                raise ValueError("an fk with a key needs one of scope and param, not both")
            if not pickers and self.rule is None:
                raise ValueError(
                    "an fk with a key needs a scope, param or rule, which picks the instance"
                )
            if self.param is not None and not isinstance(self.param, str):
                raise ValueError("an fk with a key picks its instance by one param")
            return self
        if self.param is None:
            raise ValueError("an fk needs one of path, key and param")
        if self.scope is not None or self.rule is not None:
            raise ValueError("an fk with only a param can't have a scope or rule")
        return self

    @property
    def simple(self) -> bool:
        """Whether it's written `fk = "<path>"`."""
        return self.path is not None and self.scope is None and self.rule is None

    @property
    def component(self) -> str | None:
        """The target component, or None for this one (or for a key, whose
        target is resolved at runtime)."""
        if self.path is None:
            return None
        parts = self.path.split(".")
        return parts[0] if len(parts) == 3 else None

    @property
    def block(self) -> str | None:
        return self.path.split(".")[-2] if self.path is not None else None

    @property
    def field(self) -> str | None:
        return self.path.split(".")[-1] if self.path is not None else None


# Keys load from their TOML shorthand (`pk = true`, `fk = "<path>"`,
# `keys.<name> = "<path>"`) and dump back to it where they can, so they're
# always objects in Python.
def _load_pk(v: Any) -> Any:
    if isinstance(v, bool):
        return PrimaryKey() if v else None
    return v


def _load_fk(v: Any) -> Any:
    return ForeignKey(path=v) if isinstance(v, str) else v


def _dump_pk(key: PrimaryKey) -> Any:
    return True if key.scope is None else key.model_dump(exclude_none=True)


def _dump_fk(key: ForeignKey) -> Any:
    if key.simple:
        return key.path
    data = key.model_dump(exclude_none=True)
    if isinstance(key.param, tuple):
        data["param"] = list(key.param)
    return data


PK = Annotated[
    PrimaryKey | None,
    BeforeValidator(_load_pk, json_schema_input_type=bool | PrimaryKey | None),
    PlainSerializer(_dump_pk, when_used="unless-none"),
]
FK = Annotated[
    ForeignKey | None,
    BeforeValidator(_load_fk, json_schema_input_type=str | ForeignKey | None),
    PlainSerializer(_dump_fk, when_used="unless-none"),
]


class KeySet(BaseModel):
    """A named key set a component declares in `keys`, which an fk elsewhere
    names by `key` (see `ForeignKey`) without knowing the component's type,
    like an interface: MVR's `id1` names a feature of whatever package
    `pname1` names, and each mover-capable package says which. Relationally,
    a supertype table each declaring component adds its rows to.

    `path` is `block.field`, a list's (unscoped) pk or a string array, or a
    bound `<=dim`, any index in `1..dim`. Written as the path alone.

    It may instead be several `block.field` paths, columns of one type: the
    set is their union, and as a supertype table's key, a value is unique
    across them. SSM's `source`: a flow package is named in `sources` or
    `fileinput`, not both (MF6's `isrctype`).

    `when`, as on a field, names a keyword in the component's options block
    that switches the key set on: without it, the component plays no part
    in the role. A package plays the mover roles only with MOVER set.
    Written `{path, when}`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | tuple[str, ...]
    when: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _check_path(cls, v: Any) -> Any:
        if isinstance(v, list | tuple):
            v = tuple(v)
            if not v:
                raise ValueError("a key set needs at least one path")
            if len(v) == 1:
                v = v[0]
            elif len(set(v)) != len(v):
                raise ValueError(f"key set paths {list(v)!r} repeat a path")
        for path in (v,) if isinstance(v, str) else v:
            if not isinstance(path, str):
                raise ValueError(f"key set path {path!r} must be a string")
            if path.startswith("<="):
                if not isinstance(v, str):
                    raise ValueError(
                        f"key set path {path!r}: a bound can't be one of several paths"
                    )
                if _IDENT_RE.match(path[2:]):
                    continue
            else:
                parts = path.split(".")
                if len(parts) == 2 and all(_IDENT_RE.match(p) for p in parts):
                    continue
            raise ValueError(f"key set path {path!r} must be 'block.field' or a bound '<=dim'")
        return v

    @property
    def paths(self) -> tuple[str, ...]:
        """The paths, one or more."""
        return (self.path,) if isinstance(self.path, str) else self.path

    @property
    def bound(self) -> str | None:
        """The dimension a `<=dim` path bounds the index by, or None."""
        if isinstance(self.path, str) and self.path.startswith("<="):
            return self.path[2:]
        return None


# The reserved key set name: an instance's observation types (see
# `ForeignKey`), which no component declares in `keys`.
OBSERVATIONS_KEY = "observations"

_PARAM_SOURCE_RE = re.compile(r"^(?:parent(?:\.[A-Za-z_]\w*)?|row\.[A-Za-z_]\w*)$")


class Param(BaseModel):
    """
    A binding parameter: something a component needs from whatever binds its
    file (see `docs/md/dfnspec.md`, "Parameters"). Declared in the
    component's `params`, and named by an fk's `param`, a cellid's `model`,
    or a `when`.

    - `type`: what the parameter names, a selector as in `parent`.
    - `from`: where its value comes from, one source for every binder, or a
      table of sources keyed by binder. A binder with no entry leaves it
      unset. A source is one of:
      - `parent`: the component that binds this file (OBS's `target`);
      - `row.<column>`: that column of the binding row, following its fk to
        an instance (SPC's `target`, from SSM's `pname`);
      - `parent.<param>`: a parameter of the binder, passed down (an
        exchange's mover's `model1`).
    - `rule`: as on an fk (see `RULES`), a named subset of the target.

    There's no lookup or search: each binder's source is stated.
    Relationally, a parameter is a column on the child's row, with a
    foreign key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str | list[str]
    # `from` in a file, which Python reserves.
    from_: str | dict[str, str] = PydanticField(validation_alias=AliasChoices("from", "from_"))
    rule: str | None = None

    @field_validator("from_")
    @classmethod
    def _check_from(cls, v: str | dict[str, str]) -> str | dict[str, str]:
        if isinstance(v, dict) and not v:
            raise ValueError("a parameter's from table needs at least one binder")
        for source in [v] if isinstance(v, str) else v.values():
            if not _PARAM_SOURCE_RE.match(source):
                raise ValueError(
                    f"parameter source {source!r} must be 'parent', 'parent.<param>' "
                    "or 'row.<column>'"
                )
        return v

    @field_validator("rule")
    @classmethod
    def _check_rule(cls, v: str | None) -> str | None:
        if v is not None and v not in RULES:
            raise ValueError(f"parameter rule {v!r} is not one of {sorted(RULES)!r}")
        return v

    def source_for(self, binder: str) -> str | None:
        """The source under the given binding component, or None if it
        leaves the parameter unset."""
        return self.from_ if isinstance(self.from_, str) else self.from_.get(binder)


def _dump_param(p: Param) -> dict[str, Any]:
    data: dict[str, Any] = {"type": p.type, "from": p.from_}
    if p.rule is not None:
        data["rule"] = p.rule
    return data


ParamT = Annotated[Param, PlainSerializer(_dump_param)]


def _dump_keyset(k: KeySet) -> Any:
    path = k.path if isinstance(k.path, str) else list(k.path)
    return path if k.when is None else {"path": path, "when": k.when}


KeySetT = Annotated[
    KeySet,
    BeforeValidator(
        lambda v: KeySet(path=v) if isinstance(v, str | list | tuple) else v,
        json_schema_input_type=str | list[str] | KeySet,
    ),
    PlainSerializer(_dump_keyset),
]


class String(InputFieldBase):
    type: Literal["string"] = PydanticField(default="string", frozen=True)
    valid: list[str] | None = None
    case_sensitive: bool = False
    time_series: bool = False
    pk: PK = None
    fk: FK = None
    # A dynamic keyword: the value itself is a keyword, one of the `fk`
    # target's keys, so a record it leads is keyword-led (see
    # `_is_dynamic_key`). A role in the input grammar, independent of `fk`,
    # which only says what the value references.
    dynamic: bool = False

    @model_validator(mode="after")
    def _check_dynamic(self) -> "String":
        if not self.dynamic:
            return self
        if self.tagged:
            raise ValueError(
                f"String {self.name!r}: dynamic requires tagged=False (its value is the keyword)"
            )
        if self.fk is None:
            raise ValueError(f"String {self.name!r}: dynamic requires an fk naming its keywords")
        # Its keywords must be known before its line is read, so they can't
        # depend on a scope later on that line, or on a rule.
        if self.fk.scope is not None:
            raise ValueError(f"String {self.name!r}: a dynamic keyword's fk can't be scoped")
        if not self.fk.simple:
            raise ValueError(f"String {self.name!r}: a dynamic keyword's fk must be a plain path")
        return self


# `True`: a 1-based index in the file, 0-based in memory. `"signed"`: the
# magnitude is such an index, and the sign carries a meaning of its own, which
# only the field's description defines (e.g. SFR's `ic`).
Index = bool | Literal["signed"]


def _check_cell_model(v: Any) -> Any:
    if v is not None and not (isinstance(v, str) and _IDENT_RE.match(v)):
        raise ValueError(f"a cellid's model {v!r} must be a parameter name")
    return v


# Which model's grid a cellid refers to: the name of one of the component's
# parameters of type `model` (see `Param`), such as an exchange's `model1`,
# set from `EXGMNAMEA`. `None`, or a parameter left unset where the file is
# bound (GNC's `model1` under a model): the component's own model.
CellModel = Annotated[str | None, AfterValidator(_check_cell_model)]


class Integer(InputFieldBase):
    type: Literal["integer"] = PydanticField(default="integer", frozen=True)
    valid: list[int] | None = None
    time_series: bool = False
    index: Index = False
    pk: PK = None
    fk: FK = None
    # Whether an fk may give 0 for no row (e.g. LAK's `lakeout`, an outlet
    # discharging out of the model). Not `optional`: the 0 is still written.
    allow_zero: bool = False

    @model_validator(mode="after")
    def _check_allow_zero(self) -> "Integer":
        if self.allow_zero and (self.fk is None or self.index is not True):
            raise ValueError(
                f"Integer {self.name!r}: allow_zero requires an fk and index=true "
                "(0 is no row, as no 1-based index is 0)"
            )
        return self


class Double(InputFieldBase):
    type: Literal["double"] = PydanticField(default="double", frozen=True)
    time_series: bool = False


class CellID(InputFieldBase):
    """A grid cell reference: `ncelldim` integers, its components in the grid
    it refers to (layer, row, col for DIS; layer, cell2d for DISV; node for
    DISU). Always 1-based in the file, 0-based in memory. Its width is the
    grid's, so unlike an array it has no shape."""

    type: Literal["cellid"] = PydanticField(default="cellid", frozen=True)
    model: CellModel = None
    # Whether it may refer to no cell, by giving zero for every component
    # (MF6's `allow_zero` in `nodeu_from_cellid`). Not `optional`: the
    # zeros are still written.
    allow_zero: bool = False


class File(InputFieldBase):
    type: Literal["file"] = PydanticField(default="file", frozen=True)
    direction: Literal["in", "out"]
    # Whether a FILEIN/FILEOUT keyword precedes the path. Name-file entries
    # (`TDIS6 <file>`, `GWF6 <file> <name>`) have none.
    mode_keyword: bool = True
    # The component the file is input for: a selector (see `admits`), resolved
    # among this component's children. See `_validate_file_links`.
    component: str | list[str] | None = None
    # A sibling String whose value is the target's ftype token (e.g. `DIS6`),
    # picking one family among the selector's matches. See `Dfns.ftype_family`.
    component_ftype: str | None = None


Scalar = Annotated[
    Keyword | String | Integer | Double | CellID | File,
    PydanticField(discriminator="type"),
]


class Array(InputFieldBase):
    type: Literal["array"] = PydanticField(default="array", frozen=True)
    dtype: Literal["keyword", "integer", "double", "string", "cellid"]
    shape: list[str] = []
    time_series: bool = False
    layered: bool = False
    index: Index = False
    # Integer: each (nonzero) element references a row by `pk`, per grid cell
    # or, in a list item, per entry. String: each entry is a key into the
    # target (e.g. a list of model names). Never scoped: an array has no
    # sibling columns of its own.
    fk: FK = None
    # For dtype="cellid" only: each element is a `CellID` with these.
    model: CellModel = None
    allow_zero: bool = False

    @model_validator(mode="after")
    def _check_index_dtype(self) -> "Array":
        if self.index and self.dtype != "integer":
            raise ValueError(
                f"Array {self.name!r}: index={self.index!r} requires dtype='integer', "
                f"got {self.dtype!r}"
            )
        if self.dtype != "cellid":
            for attr in ("model", "allow_zero"):
                if getattr(self, attr):
                    raise ValueError(
                        f"Array {self.name!r}: {attr} requires dtype='cellid', got {self.dtype!r}"
                    )
        else:
            for attr in ("time_series", "layered", "netcdf"):
                if getattr(self, attr):
                    raise ValueError(
                        f"Array {self.name!r}: {attr} is not valid with dtype='cellid'"
                    )
        if self.fk is not None:
            if self.dtype not in ("integer", "string"):
                raise ValueError(
                    f"Array {self.name!r}: fk requires dtype='integer' or 'string', "
                    f"got {self.dtype!r}"
                )
            if self.fk.scope is not None:
                raise ValueError(f"Array {self.name!r}: an array's fk can't be scoped")
            if not self.fk.simple:
                raise ValueError(f"Array {self.name!r}: an array's fk must be a plain path")
        return self


class Record(_DerivedTagged):
    type: Literal["record"] = PydanticField(default="record", frozen=True)
    fields: "dict[str, Scalar | Array | Record | Union]" = PydanticField(default_factory=dict)

    def _derive_tagged(self) -> bool:
        # Its first field begins with a keyword, or is a dynamic keyword.
        return _item_tags(self) is not None

    @model_validator(mode="after")
    def _check_dynamic_leads(self) -> "Record":
        # A dynamic keyword begins a line; anywhere else it'd be plain data.
        later = [n for n, f in list(self.fields.items())[1:] if _is_dynamic_key(f)]
        if later:
            raise ValueError(
                f"Record {self.name!r}: only the first field may be dynamic, got {later!r}"
            )
        return self

    @property
    def children(self) -> "dict[str, InputField]":
        return self.fields  # type: ignore[return-value]


class Union(_DerivedTagged):
    type: Literal["union"] = PydanticField(default="union", frozen=True)
    arms: "dict[str, Scalar | Array | Record]" = PydanticField(default_factory=dict)

    def _derive_tagged(self) -> bool:
        # Every arm begins with a keyword, which picks the arm.
        return _item_tags(self) is not None

    @property
    def children(self) -> "dict[str, InputField]":
        return self.arms  # type: ignore[return-value]


def _is_dynamic_key(field: "InputField | None") -> bool:
    """Whether `field` is a dynamic keyword: a String marked `dynamic`, whose
    value is one of the keys its `fk` names (e.g. an auxiliary variable's
    name, one of `options.auxiliary`'s entries). Its possible values are known
    keywords once the target has been read, so a record it leads is
    keyword-led. Declared rather than inferred from `fk`, since a leading
    untagged String with an `fk` may just as well be data (e.g. `utl-hpc`'s
    `partitions.mname`, a model name)."""
    return isinstance(field, String) and field.dynamic


def _leads_with_dynamic_key(form: "InputField") -> bool:
    return isinstance(form, Record) and _is_dynamic_key(next(iter(form.fields.values()), None))


def _item_tags(item: "Record | Union") -> list[str] | None:
    """The keyword(s) a list item type begins with, or None if it isn't
    keyword-led. A Record item must be keyword-led in the `_leading_tags`
    sense, or lead with a dynamic key (see `_is_dynamic_key`), whose keywords
    aren't known statically and so contribute none here; so must every arm of
    a Union item, since each arm is a distinct line form the item type allows.
    An empty list thus still means tagged."""
    tags = []
    for form in [item] if isinstance(item, Record) else item.arms.values():
        if _leads_with_dynamic_key(form):
            continue
        if not (form_tags := _leading_tags(form, every_line=True)):
            return None
        tags.extend(form_tags)
    return tags


def _leading_tags(field: "InputField", *, every_line: bool = False) -> list[str]:
    """The keyword(s) a field's line(s) in a block body can begin with. With
    `every_line`, empty unless every line the field allows begins with one
    (a Union with an arm that begins with a value instead doesn't qualify)."""
    match field:
        case Keyword():
            return [field.name, *field.aliases]
        case String() | Integer() | Double() | CellID() | Array() | File():
            return [field.name] if field.tagged else []
        case Record():
            first = next(iter(field.fields.values()), None)
            return _leading_tags(first, every_line=every_line) if first is not None else []
        case Union():
            arm_tags = [_leading_tags(arm, every_line=every_line) for arm in field.arms.values()]
            if every_line and not all(arm_tags):
                return []
            return [t for tags in arm_tags for t in tags]
        case List():
            return field.item_tags


class List(_DerivedTagged):
    type: Literal["list"] = PydanticField(default="list", frozen=True)
    item: "Record | Union"
    shape: list[str] = []

    def _derive_tagged(self) -> bool:
        # Its item begins with a keyword. A tagged list's items can be told
        # apart from the block's other fields, so unlike an untagged list it
        # needn't be the last or only list in its block.
        return self.item.tagged

    @property
    def item_tags(self) -> list[str]:
        """The static keywords this list's item type begins with (empty if
        untagged, or if its keywords are all dynamic; see `_is_dynamic_key`)."""
        return _item_tags(self.item) or []

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        if info.context and info.context.get("strip_names"):
            data.pop("name", None)
            # Unlike other fields, `item` isn't keyed by its name, which can
            # differ from the list's (e.g. gwf-oc `output` / `output_record`),
            # so keep it.
            if isinstance(data.get("item"), dict):
                data["item"] = {"name": self.item.name, **data["item"]}
        if "type" not in data:
            data = {"type": "list", **data}
        return data

    @model_validator(mode="after")
    def _check_shape_length(self) -> "List":
        if len(self.shape) > 1:
            raise ValueError(
                f"List {self.name!r}: shape must have at most one element "
                f"(lists are 1-dimensional), got {self.shape!r}"
            )
        return self

    @property
    def children(self) -> "dict[str, InputField]":
        # item.name duplicates the List's own name, so it's not a useful key here.
        return self.item.children


InputField = Annotated[
    Keyword | String | Integer | Double | CellID | File | Array | Record | Union | List,
    PydanticField(discriminator="type"),
]


Record.model_rebuild()
Union.model_rebuild()
List.model_rebuild()


def _collect_fields(
    fields: "dict[str, InputField]", items: "list[tuple[str, InputField]]", *, recurse: bool
) -> None:
    for name, field in fields.items():
        items.append((name, field))
        if recurse and isinstance(field, (Record, Union, List)):
            _collect_fields(field.children, items, recurse=True)


def _render_shape(field: "Array") -> str:
    # A cellid's components vary fastest, so `ncelldim` comes first.
    shape = ["ncelldim", *field.shape] if field.dtype == "cellid" else field.shape
    return f"({', '.join(shape)})" if shape else ""


def _render_file(field: "File") -> str:
    path = f"<{field.name}>"
    if field.mode_keyword:
        path = f"{'FILEIN' if field.direction == 'in' else 'FILEOUT'} {path}"
    return _tag(field, path)


def _tag(field: "InputField", inner: str) -> str:
    """Prefix `inner` with the field's uppercased name if it's tagged."""
    return f"{field.name.upper()} {inner}" if field.tagged else inner


def _ts_token(token: str, *, time_series: bool) -> str:
    return f"<@{token}@>" if time_series else f"<{token}>"


def _keyed_array(record: "Record") -> "Array | None":
    """The array of a record that's a dynamic key followed by one shaped array
    (see `_is_dynamic_key`), else None. Such a record is a tagged array whose
    tag is the key's value: it spans the key's line plus the array's
    READARRAY control and data lines, rather than one line."""
    if not _leads_with_dynamic_key(record) or len(record.fields) != 2:
        return None
    array = list(record.fields.values())[1]
    return array if isinstance(array, Array) and array.shape else None


def _render_array_body(field: "Array", name_line: str) -> str:
    if field.layered:
        name_line += " [LAYERED]"
    if field.netcdf:
        name_line += " $[NETCDF]$"
    return f"{name_line}\n  <{field.name}{_render_shape(field)}> -- READARRAY"


def _render_rows(item: "Record | Union") -> list[str]:
    if isinstance(item, Record):
        if (array := _keyed_array(item)) is not None:
            key = next(iter(item.fields.values()))
            return [_render_array_body(array, f"<{key.name}>")]
        return [" ".join(_render_field(f, inline=True) for f in item.fields.values())]
    if all(isinstance(arm, Record) for arm in item.arms.values()):
        return [
            f"[{' '.join(_render_field(f, inline=True) for f in arm.fields.values())}]"
            for arm in item.arms.values()
            if isinstance(arm, Record)
        ]
    return [f"<{item.name}>"]


def _render_field(field: "InputField", *, inline: bool = False) -> str:
    """Render a field's own text, relative to its own first line (no block indent).

    Backs ``InputFieldBase.render()`` — see that docstring for the ``inline``
    semantics. Kept as a free function (rather than inlined per-subclass)
    so ``Record``/``Union``/``List`` can recurse over arbitrary child field
    types via a single ``match``.
    """

    def _wrap(token: str) -> str:
        return f"[{token}]" if field.optional or field.when else token

    match field:
        case Keyword():
            return _wrap(field.name.upper())
        case String() | Integer() | Double():
            token = _ts_token(field.name, time_series=field.time_series)
            return _wrap(_tag(field, token))
        case CellID():
            return _wrap(_tag(field, f"<{field.name}(ncelldim)>"))
        case File():
            return _wrap(_render_file(field))
        case Array():
            if inline or not field.shape:
                token = _ts_token(
                    f"{field.name}{_render_shape(field)}", time_series=field.time_series
                )
                return _wrap(_tag(field, token))
            return _wrap(_render_array_body(field, field.name.upper()))
        case Record():
            return _wrap(" ".join(_render_field(f, inline=True) for f in field.fields.values()))
        case Union():
            if inline:
                # Nested union inside a record: collapse to a single placeholder
                return _wrap(f"<{field.name}>")
            lines = []
            for arm in field.arms.values():
                inner = (
                    " ".join(_render_field(f, inline=True) for f in arm.fields.values())
                    if isinstance(arm, Record)
                    else (arm.name.upper() if isinstance(arm, Keyword) else f"<{arm.name}>")
                )
                lines.append(_wrap(inner))
            return "\n".join(lines)
        case List():
            if inline:
                raise ValueError(f"List field {field.name!r} has no inline form")
            rows = _render_rows(field.item)
            if field.tagged and isinstance(field.item, Record):
                # e.g. `[TS6 FILEIN <ts6_filename>]` among other options. (Union
                # rows from `_render_rows` are already individually bracketed.)
                rows = [_wrap(row) for row in rows]
            if len(rows) > 1:
                return "\n".join(rows)
            return f"{rows[0]}\n{rows[0]}\n..."


def _should_render(field: "InputField", *, developmode: bool) -> bool:
    """Whether a field belongs in render() output.

    Removed/deprecated fields are never current syntax, so they're always
    excluded (MF6 no longer parses a removed field at all, and a deprecated one
    is discouraged even where still accepted) — there's no flag to see them in
    render() output, matching mf6io.pdf. Fields flagged `InputField.developmode`
    (which subsumes v1's `dev_`-name convention; see `_map_field` in the
    migration) are internal/undocumented and excluded by default, but callers
    doing internal tooling can opt in via the `developmode` parameter.
    """
    if field.removed is not None or field.deprecated is not None:
        return False
    return developmode or not field.developmode


def _render_block(block: "Block", indent: str = "  ", *, developmode: bool = False) -> str:
    begin = f"BEGIN {block.name.upper()}"
    if block.header is not None:
        begin = f"{begin} {block.header.field.render(inline=True)}"
    lines = [begin]
    for field in block.fields.values():
        if not _should_render(field, developmode=developmode):
            continue
        lines.extend(f"{indent}{line}" for line in field.render().split("\n"))
    lines.append(f"END {block.name.upper()}")
    return "\n".join(lines)


def _names_in_expr(expr: str) -> set[str]:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression {expr!r}: {e}") from e

    excluded_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Function name/path is never a dim ref
            for child in ast.walk(node.func):
                excluded_ids.add(id(child))
            # sum() and len() have domain-specific arguments; exclude those too
            if isinstance(node.func, ast.Name) and node.func.id in ("sum", "len"):
                for arg in node.args:
                    for child in ast.walk(arg):
                        excluded_ids.add(id(child))

    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and id(node) not in excluded_ids
    }


def _validate_sum_call(call: ast.Call, component: "ComponentBase", expr: str) -> None:
    if len(call.args) != 1:
        raise ValueError(f"sum() in derived_dims must have exactly one argument in {expr!r}")
    arg = call.args[0]
    if not isinstance(arg, ast.Attribute):
        raise ValueError(f"sum() argument must be an attribute expression in {expr!r}")

    col_name = arg.attr
    if isinstance(arg.value, ast.Name):
        list_name = arg.value.id
        block_qualifier: str | None = None
    elif isinstance(arg.value, ast.Attribute) and isinstance(arg.value.value, ast.Name):
        block_qualifier = arg.value.value.id
        list_name = arg.value.attr
    else:
        raise ValueError(f"Unrecognised sum() form in {expr!r}")

    found_block: str | None = None
    found_list: List | None = None
    for block_name, block in (component.blocks or {}).items():
        f = block.fields.get(list_name)
        if isinstance(f, List):
            found_block = block_name
            found_list = f
            break

    if found_list is None:
        raise ValueError(f"sum() references unknown list field {list_name!r} in {expr!r}")
    if block_qualifier is not None and block_qualifier != found_block:
        raise ValueError(
            f"sum() block qualifier {block_qualifier!r} does not match "
            f"actual block {found_block!r} in {expr!r}"
        )

    item = found_list.item
    item_fields: dict = item.fields if isinstance(item, Record) else item.arms
    col_field = item_fields.get(col_name)
    if col_field is None:
        raise ValueError(
            f"sum() column {col_name!r} not found in {list_name!r} item fields in {expr!r}"
        )
    if not isinstance(col_field, Integer):
        raise ValueError(
            f"sum() column {col_name!r} is {type(col_field).__name__}, must be Integer in {expr!r}"
        )


def _validate_len_call(call: ast.Call, component: "ComponentBase", expr: str) -> None:
    if len(call.args) != 1:
        raise ValueError(f"len() in dims must have exactly one argument in {expr!r}")
    if not isinstance(call.args[0], ast.Name):
        raise ValueError(f"len() argument must be a field name in {expr!r}")


_Hook = Literal["ar", "mc", "rp", "ad", "fc", "ca", "cq"]


class InputDim(BaseModel):
    """A named dimension resolvable from input fields at DFN-parse time.

    ``value`` specifies the dimension size, directly or indirectly, and can be:
      - ``nlay``: an integer field
      - ``len(auxiliary)``: the runtime length of a self-sizing array field
      - ``nlay * ncol``: the result of an arithmetic expression, e.g. of other dims

    Valid in both input field shapes and memory variable shapes.
    """

    value: str
    scope: Literal["component", "model", "simulation"] = "component"


class RuntimeDim(BaseModel):
    """A named dimension whose value is established by MODFLOW at runtime and
    cannot be derived from DFN input fields.

    ``set_in`` indicates the simulation hook in which the value is first
    established (e.g. ``"ar"`` for dims set during grid allocation, ``"rp"``
    for dims reset each stress period).

    Valid only in memory variable shapes, never in input field shapes, since
    a sequential parser must know an array's size before reading it.
    """

    set_in: _Hook
    scope: Literal["component", "model", "simulation"] = "component"


def _parents_as_set(parent: "str | list[str] | None") -> set[str]:
    if parent is None:
        return set()
    return {parent} if isinstance(parent, str) else set(parent)


def admits(selector: "str | list[str] | None", component: "ComponentBase") -> bool:
    """
    Whether a selector admits a component.

    A selector is a term or a list of terms, as in ``Component.parent`` and
    ``File.component``. A term admits a component if it equals the component's
    name, its type (``"model"``, ``"package"``) or its subtype (``"exchange"``,
    ``"utility"``, ...). ``"*"`` admits every component.
    """
    names = {component.name, getattr(component, "type", None), getattr(component, "subtype", None)}
    return any(t == "*" or t in names for t in _parents_as_set(selector))


def _term_rank(term: str, components: "Mapping[str, ComponentBase]") -> int:
    """How broad a selector term is: a concrete name, then a subtype, then a type."""
    if term in components:
        return 0
    if term in ("model", "package", "simulation"):
        return 2
    return 1


def covering_selector(
    linkers: "list[ComponentBase]", components: "Mapping[str, ComponentBase]"
) -> "str | list[str]":
    """
    The simplest selector that admits every linker: fewest terms first, then
    the narrowest terms (see `_term_rank`). Used to derive a linked
    component's ``parent`` from the components that link to it.
    """
    from itertools import combinations

    if not linkers:
        raise ValueError("No linkers to cover")
    terms = sorted(
        {
            t
            for c in linkers
            for t in (c.name, getattr(c, "subtype", None), getattr(c, "type", None))
            if t is not None
        },
        key=lambda t: (_term_rank(t, components), t),
    )
    for k in range(1, len(terms) + 1):
        covers = [
            combo
            for combo in combinations(terms, k)
            if all(admits(list(combo), c) for c in linkers)
        ]
        if covers:
            best = min(covers, key=lambda combo: sorted(_term_rank(t, components) for t in combo))
            return best[0] if k == 1 else list(best)
    raise AssertionError("unreachable: the linkers' own names always cover them")


def _receives_from(
    requester_parent: "str | list[str] | None",
    provider_parent: "str | list[str] | None",
    requester_name: str | None = None,
) -> bool:
    """
    Return True if the requesting component (requester_parent) can be in the
    same model as the providing component (provider_parent).

    The provider's parent identifies which model it belongs to (a concrete
    ``<type>-nam`` name, e.g. ``"gwf-nam"``).  The requester's parent
    determines whether it can be in that model: an explicit match, or a generic
    type like ``"model"`` or ``"package"`` meaning any model.

    ``requester_name``, if given, additionally makes a model component itself
    (e.g. ``"gwf-nam"``) able to receive from its own child packages: a
    model's own ``parent`` names the simulation, not the model, so without
    this a model could never see a dim its own DIS package declares (e.g.
    the discretization package's ``nodesuser``, referenced by the model's
    own runtime ``nodes`` dim).
    """
    provider_parents = _parents_as_set(provider_parent)
    model_contexts = {p for p in provider_parents if p.endswith("-nam") and p != "sim-nam"}
    if not model_contexts:
        return False

    if requester_name is not None and requester_name in model_contexts:
        return True

    requester_parents = _parents_as_set(requester_parent)
    for rp in requester_parents:
        if rp in ("model", "package", "*"):
            return True
        if rp in model_contexts:
            return True
    return False


def _resolve_derived_dims(component: "ComponentBase", known_dims: set[str]) -> list[str]:
    """
    Validate all dim value expressions and return dim names in topological order.
    Raise ValueError on cycles, unresolvable operands, or invalid field references.
    """
    all_dims = component.dims or {}
    if not all_dims:
        return []

    local_dim_names = set(all_dims.keys())
    deps: dict[str, set[str]] = {}

    for name, dim_def in all_dims.items():
        value = dim_def.value
        try:
            tree = ast.parse(value, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid dims {name!r}: {value!r}: {e}") from e

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "len":
                    _validate_len_call(node, component, value)
                elif node.func.id == "sum":
                    _validate_sum_call(node, component, value)

        if _DIM_RE.fullmatch(value):
            # Bare identifier: an input dim, the Integer field of its own name
            if value != name:
                raise ValueError(
                    f"dims {name!r}: a bare field name must be the dim's own name, got {value!r}"
                )
            field = component.get_fields().get(value)
            if field is None:
                raise ValueError(f"dims {name!r}: field {value!r} not found in component")
            if not isinstance(field, Integer):
                raise ValueError(
                    f"dims {name!r}: field {value!r} is {type(field).__name__}, "
                    f"must be Integer (use len({value}) for array fields)"
                )
            deps[name] = set()
        elif _LEN_CALL_RE.fullmatch(value):
            deps[name] = set()
        else:
            operands = _names_in_expr(value)
            for op in operands:
                if op not in known_dims and op not in local_dim_names:
                    raise ValueError(f"dims {name!r} operand {op!r} is not a known dimension")
            deps[name] = operands & local_dim_names - {name}

    in_degree = dict.fromkeys(local_dim_names, 0)
    dependents: dict[str, set[str]] = {n: set() for n in local_dim_names}
    for name, dep_set in deps.items():
        for dep in dep_set:
            in_degree[name] += 1
            dependents[dep].add(name)

    queue = [n for n, d in in_degree.items() if d == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for dependent in dependents[n]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(local_dim_names):
        cyclic = {n for n, d in in_degree.items() if d > 0}
        raise ValueError(f"Cycle in dims: {cyclic}")

    return order


class _DimExprs:
    """A component's dim value expressions, evaluated (and solved) over input
    field values from ``lookup``; see :func:`dim_value`."""

    def __init__(self, dims: Mapping[str, str] | None, lookup: Callable[[str], Any] | None):
        self.dims = dims or {}
        self.lookup = lookup or (lambda _: None)

    def parse(self, expr: str) -> ast.expr:
        if _BOUND_RE.match(expr):
            raise ValueError(f"{expr!r} is bounded; split off the bound with split_bound")
        try:
            return ast.parse(expr, mode="eval").body
        except SyntaxError as e:
            raise ValueError(f"invalid expression {expr!r}: {e}") from e

    def dim(self, name: str, seen: frozenset[str]) -> "tuple[str, ast.expr] | None":
        """A dim's value expression and its tree, or None for an input."""
        expr = self.dims.get(name, name)
        if expr == name:
            return None
        if name in seen:
            raise ValueError(f"cycle in dims at {name!r}")
        return expr, self.parse(expr)

    def path(self, node: ast.expr, expr: str) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self.path(node.value, expr)}.{node.attr}"
        raise ValueError(f"unsupported argument in {expr!r}: {ast.unparse(node)!r}")

    def evaluate(self, node: ast.expr, seen: frozenset[str], expr: str) -> int | None:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            if (d := self.dim(node.id, seen)) is None:
                v = self.lookup(node.id)
                return None if v is None else int(v)
            return self.evaluate(d[1], seen | {node.id}, d[0])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = self.evaluate(node.operand, seen, expr)
            return None if v is None else -v
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)
        ):
            a, b = self.evaluate(node.left, seen, expr), self.evaluate(node.right, seen, expr)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div) and a % b:
                raise ValueError(f"{a} / {b} is not an integer in {expr!r}")
            return a // b
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("len", "sum")
            and len(node.args) == 1
            and not node.keywords
        ):
            v = self.lookup(self.path(node.args[0], expr))
            if v is None:
                return None
            return len(v) if node.func.id == "len" else int(sum(v))
        raise ValueError(f"unsupported expression in {expr!r}: {ast.unparse(node)!r}")

    def solve(
        self, node: ast.expr, value: int, seen: frozenset[str], expr: str
    ) -> "tuple[str, int] | None":
        if isinstance(node, ast.Name):
            if (d := self.dim(node.id, seen)) is None:
                return (node.id, value) if self.lookup(node.id) is None else None
            return self.solve(d[1], value, seen | {node.id}, d[0])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return self.solve(node.operand, -value, seen, expr)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            a, b = self.evaluate(node.left, seen, expr), self.evaluate(node.right, seen, expr)
            add = isinstance(node.op, ast.Add)
            if a is None and b is not None:
                return self.solve(node.left, value - b if add else value + b, seen, expr)
            if b is None and a is not None:
                return self.solve(node.right, value - a if add else a - value, seen, expr)
        # anything else (len(), sum(), *, /, ...) can't be undone
        return None


def dim_value(
    expr: str,
    dims: Mapping[str, str] | None = None,
    lookup: Callable[[str], Any] | None = None,
    select: Callable[[str, Any], Any] | None = None,
) -> int | None:
    """
    Evaluate a dimension expression: a dim's name or ``value``, or an
    ``Array``/``List`` shape expression (without its bound; see
    :func:`split_bound`).

    ``dims`` maps the component's dim names to their value expressions
    (``{"nodes": "nlay * ncpl", ...}``, as in ``InputDim.value``). ``lookup``
    gets an input field's value by name, or by dotted path for
    ``sum(list.column)`` (an iterable of the column's values), and returns None
    if the field isn't set. To evaluate an inline array's shape, ``lookup``
    should see the fields of the array's row too. Without ``dims`` there are
    no dims; without ``lookup`` no input is set.

    A name that is a dim is evaluated in turn; any other name, like an input
    dim's own name, a field in the row, or a name not in ``dims``, is passed to
    ``lookup``. Expressions may use integer literals, ``+``, ``-``, ``*``,
    ``/`` (exact), ``//``, ``len()`` and ``sum()``.

    A row-level lookup, ``[component.]block.column(fk_field)``, needs
    ``select``: given the path ``"[component.]block.column"`` and the row's
    ``fk_field`` value, it returns that column's value in the referenced row.

    Returns None if an input it depends on isn't set. Raises ValueError for a
    malformed expression, a cycle, or an inexact ``/``.
    """
    exprs = _DimExprs(dims, lookup)
    if m := _LOOKUP_RE.fullmatch(expr):
        component_ref, block_name, col_name, fk_field_name = m.groups()
        if select is None:
            raise ValueError(f"{expr!r} is a row-level lookup, which needs select")
        key = exprs.lookup(fk_field_name)
        if key is None:
            return None
        v = select(".".join(filter(None, (component_ref, block_name, col_name))), key)
        return None if v is None else int(v)
    return exprs.evaluate(exprs.parse(expr), frozenset(), expr)


def dim_input(
    expr: str,
    dims: Mapping[str, str] | None = None,
    lookup: Callable[[str], Any] | None = None,
    *,
    length: int,
) -> tuple[str, int] | None:
    """
    The inverse of :func:`dim_value`: rather than plug inputs into ``expr``,
    find the input to plug in so that ``expr`` gives ``length``, the number of
    values the data has. Returns ``(name, value)``, the input to sync to the
    data, or None if there is none: no unset input, more than one, or one
    that can't be solved for (under ``len()``, ``sum()``, ``*`` or a
    row-level lookup). Then the data can only be checked with ``dim_value``.

    E.g. ``"nseg-1"`` with 3 values gives ``("nseg", 4)``. Other arguments are
    as for ``dim_value``.
    """
    if _LOOKUP_RE.fullmatch(expr):
        return None
    exprs = _DimExprs(dims, lookup)
    return exprs.solve(exprs.parse(expr), length, frozenset(), expr)


class BlockHeader(BaseModel):
    """A repeating block's header field, plus whether a missing occurrence means
    "reuse the prior occurrence's values" (`period`, e.g.). Nested here rather
    than a sibling flag on `Block` so it can't be set without a header.

    An `Integer` header is inherently a sequential key -- both `period`'s
    `iper` and `solutiongroup`'s `group_num` are documented as monotonically
    increasing across occurrences, whether or not they fill forward. It's
    only what a *gap* in that sequence means that varies.

    `update` says what a *present* occurrence means: `"replace"` if it's
    the complete new state, `"merge"` if it updates only what it names and
    everything else keeps its last value. `None` means not stated.
    """

    field: InputField
    fill_forward: bool = False
    update: Literal["replace", "merge"] | None = None

    @model_validator(mode="after")
    def _check_fill_forward_requires_integer(self) -> "BlockHeader":
        if self.fill_forward and not isinstance(self.field, Integer):
            raise ValueError(
                "BlockHeader: fill_forward requires an Integer field; "
                f"got {type(self.field).__name__}"
            )
        return self

    @model_validator(mode="after")
    def _check_update_requires_fill_forward(self) -> "BlockHeader":
        if self.update is not None and not self.fill_forward:
            raise ValueError(
                "BlockHeader: update requires fill_forward; without "
                "carried-forward state there's nothing to replace or merge into"
            )
        return self


def _leads_with_address(item: "InputField") -> bool:
    """Whether a list item's rows say what they update: the leading column is
    an `index` integer or a `cellid`. A union item does if every arm does."""
    if isinstance(item, Union):
        return all(_leads_with_address(arm) for arm in item.arms.values())
    if not isinstance(item, Record):
        return False
    leading = next(iter(item.fields.values()), None)
    return isinstance(leading, CellID) or (isinstance(leading, Integer) and bool(leading.index))


class Block(BaseModel):
    name: str
    fields: dict[str, InputField]
    header: "BlockHeader | None" = None
    # Whether MF6 requires this block's header to appear in the input file even
    # when it has zero body lines. Distinct from (and not derivable from)
    # `optional`: a block can be required (`optional=False`, every field
    # required) yet still only conditionally present at the Fortran level --
    # e.g. gated by a dimension being nonzero, in which case it must be
    # *omitted* entirely when empty rather than written out empty. Which
    # behavior a given required block actually has is a runtime fact only the
    # Fortran source encodes; it cannot be inferred from other DFN attributes
    # (see gwf-lak's TABLES/OUTLETS, which are hand-written and both bypass
    # the generic required-block check regardless of what the DFN says). Set
    # from an explicit `write_if_empty true` tag on the block's own field(s)
    # -- never inferred.
    write_if_empty: bool = False

    @model_validator(mode="after")
    def _check_merge_has_address(self) -> "Block":
        # A merge updates only what the block names, so the block must be able
        # to name something: a field names itself, a list's rows need an address.
        if self.header is None or self.header.update != "merge":
            return self
        if any(
            not isinstance(f, List) or _leads_with_address(f.item) for f in self.fields.values()
        ):
            return self
        raise ValueError(
            f"Block {self.name!r}: update 'merge' requires a non-list field, "
            "or a list whose rows lead with an index integer or a cellid"
        )

    @model_validator(mode="after")
    def _check_field_order(self) -> "Block":
        # Only untagged lists are restricted: they consume all remaining block
        # content. A tagged list's items are keyword-led, so they can sit anywhere.
        fields_list = list(self.fields.items())
        list_indices = [
            i for i, (_, f) in enumerate(fields_list) if isinstance(f, List) and not f.tagged
        ]
        if len(list_indices) > 1:
            names = [fields_list[i][0] for i in list_indices]
            raise ValueError(
                f"Block {self.name!r}: at most one untagged list field is allowed; found: {names!r}"
            )
        if list_indices and list_indices[0] != len(fields_list) - 1:
            after = [n for n, _ in fields_list[list_indices[0] + 1 :]]
            raise ValueError(
                f"Block {self.name!r}: untagged list field must be last (it consumes "
                f"all remaining block content); found fields after it: {after!r}"
            )
        return self

    @model_validator(mode="after")
    def _check_list_tags_unique(self) -> "Block":
        # A tagged list's items are recognized by their leading keyword, so no
        # other field in the block may begin with the same one. A dynamic key's
        # keywords (see `_is_dynamic_key`) are only known at runtime, so its
        # uniqueness can't be checked here.
        owners: dict[str, list[str]] = {}
        for name, f in self.fields.items():
            for tag in _leading_tags(f):
                owners.setdefault(tag, []).append(name)
        for name, f in self.fields.items():
            if not (isinstance(f, List) and f.tagged):
                continue
            for tag in f.item_tags:
                if len(owners[tag]) > 1:
                    raise ValueError(
                        f"Block {self.name!r}: tagged list {name!r} item keyword "
                        f"{tag!r} is ambiguous with fields {owners[tag]!r}"
                    )
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        data.pop("name", None)  # name is the dict key in ComponentBase.blocks
        # Unlike `fields`, `header.field` isn't stored in a name-keyed dict, so its
        # `name` (stripped by InputFieldBase._serialize under strip_names) must be
        # restored here or it can't be recovered on load.
        if self.header is not None and isinstance(data.get("header"), dict):
            header_data = data["header"]
            if isinstance(header_data.get("field"), dict):
                header_data["field"] = {"name": self.header.field.name, **header_data["field"]}
        return data

    def dump(self, *, strip_names: bool = True, **kwargs) -> dict[str, Any]:
        if strip_names:
            kwargs["context"] = {**(kwargs.get("context") or {}), "strip_names": True}
        return self.model_dump(**kwargs)

    def dump_json(self, *, strip_names: bool = True, **kwargs) -> str:
        if strip_names:
            kwargs["context"] = {**(kwargs.get("context") or {}), "strip_names": True}
        return self.model_dump_json(**kwargs)

    @property
    def optional(self) -> bool:
        return all(f.optional for f in self.fields.values())

    @property
    def repeats(self) -> bool:
        """Whether the block may appear multiple times, each labeled by `header`."""
        return self.header is not None

    def render(self, *, developmode: bool = False) -> str:
        return _render_block(self, developmode=developmode)

    def get_fields(self, recurse: bool = False) -> OMD:
        """Fields keyed by name, including `header`; `recurse` descends into children."""
        items: list[tuple[str, InputField]] = []
        _collect_fields(self.fields, items, recurse=recurse)
        if self.header is not None:
            _collect_fields({self.header.field.name: self.header.field}, items, recurse=recurse)
        return OMD(items)


Blocks = Mapping[str, Block]


_MemDtype = Literal["integer", "double", "string", "logical"]


class MemoryVariableBase(BaseModel):
    readonly: bool = False
    set_in: _Hook | list[_Hook] | None = None
    source: str | list[str] | None = None
    description: str | None = None
    budget: str | None = None
    output: bool | None = None
    obs_type: str | None = None


class MemoryScalar(MemoryVariableBase):
    """A scalar (rank-0) runtime memory variable accessible via the MODFLOW API."""

    type: _MemDtype

    @property
    def dtype(self) -> str:
        return self.type


class MemoryArray(MemoryVariableBase):
    """An array (rank >= 1) runtime memory variable accessible via the MODFLOW API."""

    type: Literal["array"] = PydanticField(default="array", frozen=True)
    dtype: _MemDtype
    shape: list[str] = []

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        if "type" not in data:
            data = {"type": "array", **data}
        return data


MemoryVariable = Annotated[
    MemoryScalar | MemoryArray,
    PydanticField(discriminator="type"),
]


ObservationField = Annotated[
    Integer | Double | String | CellID | Array | Record | Union,
    PydanticField(discriminator="type"),
]


class ComponentBase(BaseModel):
    schema_version: str | None = None
    name: str
    parent: str | list[str] | None = None
    # The token naming this component's file type in name files and file
    # records (`GWF6`, `DIS6`, `GWF6-GWF6`). Array-based variants share their
    # base's (`gwf-rcha` is `RCH6`): mf6 picks the variant from the file's own
    # READASARRAYS/READARRAYGRID option. See `Dfns.ftype_family`.
    ftype: str | None = None
    dims: dict[str, InputDim] | None = None
    runtime_dims: dict[str, RuntimeDim] | None = None
    blocks: dict[str, Block] | None = None
    memory: dict[str, MemoryVariable] | None = None
    # Observation types this component accepts in its OBS file, keyed by
    # (lower-case) name. See `ObservationField`.
    observations: dict[str, ObservationField] | None = None
    # Named key sets other components' fks can name by `key`, without knowing
    # this component's type (MVR's `id1`: `mover_provider`). See `KeySet`.
    keys: dict[str, KeySetT] | None = None
    # What this component needs from whatever binds its file, by name (an
    # exchange's `model1`, SPC's `target`). See `Param`.
    params: dict[str, ParamT] | None = None

    @field_validator("keys")
    @classmethod
    def _check_key_names(cls, v: dict[str, KeySet] | None) -> dict[str, KeySet] | None:
        for name in v or {}:
            if not _IDENT_RE.match(name):
                raise ValueError(f"key set name {name!r} must be an identifier")
            if name == OBSERVATIONS_KEY:
                raise ValueError(f"key set name {name!r} is reserved for observation types")
        return v

    @field_validator("params")
    @classmethod
    def _check_param_names(cls, v: dict[str, Param] | None) -> dict[str, Param] | None:
        for name in v or {}:
            if not _IDENT_RE.match(name):
                raise ValueError(f"parameter name {name!r} must be an identifier")
        return v

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if "type" not in data:
            data = {"type": getattr(self, "type"), **data}
        return data

    def get_fields(self, recurse: bool = False) -> OMD:
        items: list[tuple[str, InputField]] = []
        for block in (self.blocks or {}).values():
            items.extend(block.get_fields(recurse=recurse).items(multi=True))
        return OMD(items)

    def get_block(self, field_name: str) -> Block | None:
        for block in (self.blocks or {}).values():
            if block.fields.get(field_name, None) or (
                block.header is not None and block.header.field.name == field_name
            ):
                return block
        return None

    def render(self, *, developmode: bool = False) -> str:
        return "\n\n".join(
            _render_block(b, developmode=developmode) for b in (self.blocks or {}).values()
        )


class Simulation(ComponentBase):
    type: Literal["simulation"] = "simulation"


class Model(ComponentBase):
    type: Literal["model"] = "model"
    solution: Literal["ims", "ems", "sln-ims", "sln-ems"] | None = None
    dependent_variable: str | None = None


class Package(ComponentBase):
    type: Literal["package"] = "package"
    multi: bool = False
    subtype: Literal["solution", "exchange", "stress", "advanced", "utility"] | None = None


Component = Annotated[
    Simulation | Model | Package,
    PydanticField(discriminator="type"),
]

_DIM_RE = re.compile(r"^[A-Za-z_]\w*$")
_LEN_CALL_RE = re.compile(r"^len\([A-Za-z_]\w*\)$")
_LOOKUP_RE = re.compile(r"^(?:([\w-]+)\.)?(\w+)\.(\w+)\((\w+)\)$")
_BOUND_RE = re.compile(r"^[<>]=?")
_ARITH_RE = re.compile(r"^([A-Za-z_]\w*)\s*([+-])\s*(\d+)$")

_SHAPE_FORMS = (
    "must be a dim reference (^[A-Za-z_]\\w*$), an arithmetic offset "
    "(dim [+-] integer), or a row-level lookup (block.column(fk_field)), "
    "optionally prefixed by a bound (<, <=, >, >=)"
)


def split_bound(element: str) -> "tuple[str | None, str]":
    """
    Split a shape element into its bound operator and the expression it bounds.

    A bare element (``"nper"``) is an exact length; an element prefixed with an
    inequality operator (``"<=maxbound"``) bounds the length instead. Returns
    ``(operator, expression)``, with ``operator`` ``None`` for an exact length.
    """
    if m := _BOUND_RE.match(element):
        return m.group(), element[m.end() :].strip()
    return None, element


@dataclass(frozen=True)
class _ShapeRef:
    """
    A parsed shape element; see :func:`_parse_shape_element`.

    ``kind`` is ``"dim"`` for a dim reference, ``"sibling"`` for a reference
    to an Integer subfield of the same record (an inline count on the same
    row), and ``"lookup"`` for a row-level column lookup.
    """

    kind: Literal["dim", "sibling", "lookup"]
    # the dim, sibling field, or looked-up column
    name: str
    # arithmetic offset: "nseg-1" -> -1
    offset: int = 0
    # "<", "<=", ">" or ">=", or None for an exact length
    bound: str | None = None
    # lookup only: "[component.]block.column(fk_field)"
    component: str | None = None
    block: str | None = None
    fk_field: str | None = None


def _parse_shape_element(element: str, record: "Record | None" = None) -> _ShapeRef:
    """
    Parse one element of an ``Array.shape`` or ``List.shape``.

    ``record`` is the record the array is a subfield of, if any. A name that
    is an Integer subfield of it is a ``"sibling"`` (cell2d's ``ncvert``,
    counting ``icvert``), otherwise a ``"dim"``. Loading rejects a name that
    is both, so the record is all the context needed to tell them apart.

    Nothing else is checked against a component; that happens when ``Dfns``
    loads. Raises ``ValueError`` if the element is malformed.
    """
    bound, core = split_bound(element)
    if bound is not None and split_bound(core)[0] is not None:
        raise ValueError(
            f"invalid shape element {element!r}: at most one bound operator is allowed"
        )
    if m := _LOOKUP_RE.fullmatch(core):
        component_ref, block_name, col_name, fk_field_name = m.groups()
        return _ShapeRef(
            "lookup",
            col_name,
            bound=bound,
            component=component_ref,
            block=block_name,
            fk_field=fk_field_name,
        )
    if _DIM_RE.fullmatch(core):
        name, offset = core, 0
    elif m := _ARITH_RE.fullmatch(core):
        name, sign, n = m.groups()
        offset = int(sign + n)
    else:
        raise ValueError(f"invalid shape element {element!r}: {_SHAPE_FORMS}")
    sibling = record is not None and isinstance(record.fields.get(name), Integer)
    return _ShapeRef("sibling" if sibling else "dim", name, offset=offset, bound=bound)


def _find_list_in_block(component: "ComponentBase", block_name: str) -> "List | None":
    """Return the first List field in the named block, or None."""
    block = (component.blocks or {}).get(block_name)
    if block is None:
        return None
    for f in block.fields.values():
        if isinstance(f, List):
            return f
    return None


def _check_shape_element(
    element: str,
    field: "Array | List",
    known_dims: set[str],
    component: "ComponentBase | None" = None,
    enclosing_record: "Record | None" = None,
    spec: "Dfns | None" = None,
) -> None:
    """
    Check that a shape element parses and resolves in its context: a dim in
    ``known_dims``, a sibling that isn't also a dim, or a lookup of an Integer
    column in a list block (in ``component``, or with ``spec`` another
    component), selected by a sibling whose ``fk`` references that block.

    A sibling or lookup varies by row, so the array must be the rightmost
    field in its record, like a self-sizing array: a row's layout is fixed
    by the component's dimensions, except for its last field.

    Raises ValueError on any violation.
    """
    try:
        ref = _parse_shape_element(element, enclosing_record)
        _check_shape_ref(element, ref, known_dims, component, enclosing_record, spec)
        if ref.kind != "dim" and list(enclosing_record.fields)[-1] != field.name:  # type: ignore
            raise ValueError(
                f"invalid shape element {element!r}: it varies by row, so "
                f"{field.name!r} must be the rightmost field in its record"
            )
    except ValueError as e:
        raise ValueError(f"{type(field).__name__} {field.name!r} has {e}") from None


def _check_shape_ref(
    element: str,
    ref: _ShapeRef,
    known_dims: set[str],
    component: "ComponentBase | None",
    enclosing_record: "Record | None",
    spec: "Dfns | None",
) -> None:
    where = f"invalid shape element {element!r}"

    if ref.kind == "dim":
        if ref.name not in known_dims:
            raise ValueError(
                f"{where}: {ref.name!r} does not resolve to a known dim "
                f"(explicit, derived, or grid)"
            )
        return

    if ref.kind == "sibling":
        if ref.name in known_dims:
            raise ValueError(f"{where}: {ref.name!r} is both a dim and a sibling field")
        return

    # a lookup selects a row by a sibling field, so the array must be in a record
    if enclosing_record is None:
        raise ValueError(f"{where}: a row-level lookup, but the field is not inside a record")

    # Resolve target component (cross-component reference or local)
    target: ComponentBase | None
    if ref.component is not None:
        if spec is None:
            raise ValueError(f"{where}: cross-component reference requires a Dfns spec")
        target = spec.components.get(ref.component)
        if target is None:
            raise ValueError(f"{where}: component {ref.component!r} not found in spec")
    else:
        target = component
    assert target is not None and ref.block is not None and ref.fk_field is not None

    # block must identify a list block in the target component
    list_field = _find_list_in_block(target, ref.block)
    if list_field is None:
        loc = f"component {ref.component!r}" if ref.component else "this component"
        raise ValueError(f"{where}: {ref.block!r} is not a list block in {loc}")

    # the column must be an Integer field in the list's item record
    item = list_field.item
    item_fields: dict = item.fields if isinstance(item, Record) else item.arms
    col_field = item_fields.get(ref.name)
    if col_field is None:
        raise ValueError(f"{where}: {ref.name!r} is not a field in {list_field.name!r} item")
    if not isinstance(col_field, Integer):
        raise ValueError(f"{where}: {ref.name!r} is {type(col_field).__name__}, must be Integer")

    # the fk field must be a sibling field in the enclosing record
    fk_field = enclosing_record.fields.get(ref.fk_field)
    if fk_field is None:
        raise ValueError(
            f"{where}: {ref.fk_field!r} is not a sibling field in the enclosing record"
        )

    # its fk must be set and reference the lookup's list
    fk: ForeignKey | None = getattr(fk_field, "fk", None)
    if fk is None:
        raise ValueError(f"{where}: {ref.fk_field!r}.fk is not set")
    if (fk.component, fk.block) != (ref.component, ref.block):
        raise ValueError(
            f"{where}: {ref.fk_field!r}.fk = {fk.path!r} does not reference block {ref.block!r}"
        )


def _validate_shape_element(
    element: str,
    array_field: "Array",
    component: "ComponentBase",
    enclosing_record: "Record | None",
    known_dims: set[str],
    spec: "Dfns | None" = None,
) -> None:
    """Validate one element of an Array.shape (see `_check_shape_element`)."""
    _check_shape_element(element, array_field, known_dims, component, enclosing_record, spec)


def _validate_list_shape_element(
    element: str,
    list_field: "List",
    known_dims: set[str],
) -> None:
    """
    Validate one element of a List.shape. A list isn't inside a record, so
    its shape may only reference dims.
    """
    _check_shape_element(element, list_field, known_dims)


def _key_scopes(field: "InputField") -> set[str]:
    keys = (getattr(field, "pk", None), getattr(field, "fk", None))
    return {k.scope for k in keys if k is not None and k.scope is not None}


def _check_record_keys(fields: dict, outer: "Mapping[str, InputField] | None" = None) -> None:
    """
    Check a record's keys among its columns: at most one `pk`, and every
    scope names another String/Integer column, without cycles. A column's
    `pk` and `fk`, if both scoped, share the scope.

    A scope may also name a column of an enclosing record, `outer` (SFR's
    period `diversion` arm's `idv`, scoped by the list item's `ifno`), the
    nearer column winning a name both have.
    """
    pks = [n for n, f in fields.items() if getattr(f, "pk", None) is not None]
    if len(pks) > 1:
        raise ValueError(f"Fields {pks!r}: a row may have only one pk")
    visible = {**(outer or {}), **fields}
    for name, field in fields.items():
        scopes = _key_scopes(field)
        if len(scopes) > 1:
            raise ValueError(f"Field {name!r}: pk and fk scopes differ, {sorted(scopes)!r}")
        for scope in scopes:
            if scope == name or not isinstance(visible.get(scope), String | Integer):
                raise ValueError(
                    f"Field {name!r} scope={scope!r}: not another String or Integer "
                    f"field in the same or an enclosing record"
                )
    for name in fields:
        chain = [name]
        while scopes := _key_scopes(visible[chain[-1]]):
            (scope,) = scopes
            if scope in chain:
                raise ValueError(f"Fields {chain!r}: scopes form a cycle")
            chain.append(scope)


def _param_components(spec: "Dfns", owner: "ComponentBase", name: str) -> set[str]:
    """The components a parameter of `owner` can name, by its `type`, or
    nothing if `owner` declares no such parameter."""
    param = (owner.params or {}).get(name)
    if param is None:
        return set()
    return {n for n, c in spec.components.items() if admits(param.type, c)}


def _named_components(
    spec: "Dfns",
    owner: "ComponentBase",
    row: "Mapping[str, InputField]",
    column: "InputField",
    seen: frozenset[tuple[str, str]] = frozenset(),
) -> set[str]:
    """
    The components whose instance a column's value can name: whatever its
    fk's target column names, following fks across components (MVR's
    `pname1` names a `packages` row, whose `pname` names a package in a
    model), or, for a column without an fk that is the pk of a binding row,
    the components that row binds (a name file's `pname`).
    """
    if (owner.name, column.name) in seen:
        return set()
    seen = seen | {(owner.name, column.name)}
    fk: ForeignKey | None = getattr(column, "fk", None)
    if fk is None and getattr(column, "pk", None) is not None:
        selectors = [
            f.component
            for f in row.values()
            if isinstance(f, File) and f.direction == "in" and f.component is not None
        ]
        return {
            n
            for n, c in spec.components.items()
            if any(admits(s, c) for s in selectors) and admits(c.parent, owner)
        }
    if fk is not None and fk.param is not None and fk.key is None:
        return {n for p in fk.params for n in _param_components(spec, owner, p)}
    if fk is None or fk.path is None:
        return set()
    target = spec.components.get(fk.component) if fk.component else owner
    lst = _find_list_in_block(target, fk.block) if target and fk.block else None
    if target is None or lst is None or not isinstance(lst.item, Record):
        return set()
    target_col = lst.item.fields.get(fk.field)  # type: ignore[arg-type]
    if target_col is None:
        return set()
    return _named_components(spec, target, lst.item.fields, target_col, seen)


def _validate_fk_fields(component: "ComponentBase", spec: "Dfns") -> None:
    """
    For every Integer/String/Array field with an fk, validate structure (see
    docs/md/dfnspec.md, "Primary and foreign keys"). Grid-cell references are
    a separate mechanism (the `cellid` type, see `CellID`).

    An fk's path names a list block's pk column, or, for a String or string
    Array, a string-dtype Array, whose entries are then the key set (e.g.
    `options.auxiliary`). Without a component, the block is looked up in this
    component; with one, in that component via `spec.components`. A dynamic
    key (see `_is_dynamic_key`) is checked like any other String.

    A scoped fk within a component targets a pk scoped the same way: if both
    scope columns have an fk, it's the same. A scoped fk to another component
    picks its instance by the scope column, which must name (see
    `_named_components`) an instance of the target component. An fk with a
    `rule` (see `RULES`) is checked as unscoped, or by its scope if it has
    one; the rule is the consumer's.

    An fk with a `key` names a key set declared by at least one component its
    scope can name (with a rule, by any component), and fits each
    declaration: a `<=dim` path needs an integer index column, a
    `block.field` path a column of the same type.

    Observation fields (see `ObservationField`) are checked like a list item's.
    """

    def _check_param(field: "InputField", fk: ForeignKey) -> None:
        for name in fk.params:
            if name not in (component.params or {}):
                raise ValueError(
                    f"Field {field.name!r} fk param={name!r}: {component.name} declares "
                    f"no such parameter"
                )

    def _check_fk(field: "InputField", fk: ForeignKey, fields: dict) -> None:
        _check_param(field, fk)
        if fk.key is not None:
            _check_key(field, fk, fields)
            return
        if fk.path is None:
            # A param alone: the value names the instance a parameter is set to.
            if not isinstance(field, String):
                raise ValueError(
                    f"Field {field.name!r} fk param={fk.param!r}: only a string column "
                    f"may name a parameter's instance"
                )
            return
        assert fk.path is not None and fk.block is not None and fk.field is not None
        where_fk = f"Field {field.name!r} fk={fk.path!r}"
        target = component
        where = "this component"
        if fk.component is not None:
            resolved = spec.components.get(fk.component)
            if resolved is None:
                raise ValueError(f"{where_fk}: component {fk.component!r} not found in spec")
            target = resolved
            where = f"component {fk.component!r}"
        is_string = isinstance(field, String) or (
            isinstance(field, Array) and field.dtype == "string"
        )
        if is_string:
            target_block = (target.blocks or {}).get(fk.block)
            target_field = target_block.fields.get(fk.field) if target_block else None
            if isinstance(target_field, Array) and target_field.dtype == "string":
                return
        list_field = _find_list_in_block(target, fk.block)
        if list_field is None:
            raise ValueError(f"{where_fk}: {fk.block!r} is not a list block in {where}")
        item = list_field.item
        item_fields: dict = item.fields if isinstance(item, Record) else item.arms
        target_pk: PrimaryKey | None = getattr(item_fields.get(fk.field), "pk", None)
        if target_pk is None:
            raise ValueError(f"{where_fk}: {fk.field!r} is not the pk of list {list_field.name!r}")
        if fk.component is None:
            if (fk.scope is None) != (target_pk.scope is None):
                raise ValueError(
                    f"{where_fk}: scope={fk.scope!r}, but the target pk's is "
                    f"{target_pk.scope!r}; both or neither must be scoped"
                )
            if fk.scope is not None and target_pk.scope is not None:
                ours = getattr(fields[fk.scope], "fk", None)
                theirs = getattr(item_fields[target_pk.scope], "fk", None)
                if ours is not None and theirs is not None and ours != theirs:
                    raise ValueError(
                        f"{where_fk}: scope {fk.scope!r} references {ours.path!r}, but the "
                        f"target's scope {target_pk.scope!r} references {theirs.path!r}"
                    )
        elif fk.scope is not None:
            if fk.component not in _named_components(spec, component, fields, fields[fk.scope]):
                raise ValueError(
                    f"{where_fk}: scope {fk.scope!r} must be an fk to the row binding "
                    f"{fk.component!r} in its parent (directly or through fks)"
                )

    def _check_key(field: "InputField", fk: ForeignKey, fields: dict) -> None:
        assert fk.key is not None
        where_fk = f"Field {field.name!r} fk key={fk.key!r}"
        if not isinstance(field, Integer | String):
            raise ValueError(f"{where_fk}: only an integer or string column may name a key")
        if fk.scope is not None:
            named = sorted(_named_components(spec, component, fields, fields[fk.scope]))
            where_named = f"the scope {fk.scope!r} can name ({named!r})"
        elif fk.param is not None:
            assert isinstance(fk.param, str)
            named = sorted(_param_components(spec, component, fk.param))
            where_named = f"the parameter {fk.param!r} can name"
        else:
            named = sorted(spec.components)
            where_named = "in the spec"
        if fk.key == OBSERVATIONS_KEY:
            if not isinstance(field, String):
                raise ValueError(f"{where_fk}: observation types are named by a string column")
            if not any(spec.components[n].observations for n in named):
                raise ValueError(f"{where_fk}: no component {where_named} has observations")
            return
        declaring = [spec.components[n] for n in named if fk.key in (spec.components[n].keys or {})]
        if not declaring:
            raise ValueError(f"{where_fk}: no component {where_named} declares key {fk.key!r}")
        for target in declaring:
            keyset = (target.keys or {})[fk.key]
            where = f"{where_fk}: {target.name}'s {keyset.path!r}"
            if keyset.bound is not None:
                if not (isinstance(field, Integer) and field.index is True):
                    raise ValueError(f"{where}: a '<=dim' key needs an integer index column")
                continue
            column = _keyset_column(target, keyset.paths[0])
            if isinstance(field, Integer) != isinstance(column, Integer):
                raise ValueError(f"{where}: the column's type doesn't match {field.type!r}")

    def _check_fields(fields: dict, record: bool = False, outer: dict | None = None) -> None:
        # `outer`: the columns of the records enclosing these, within a list
        # item, which a scope may also name (see `_check_record_keys`).
        if record:
            _check_record_keys(fields, outer)
        visible = {**(outer or {}), **fields}
        inner = visible if record else outer
        for field in fields.values():
            fk: ForeignKey | None = getattr(field, "fk", None)
            if fk is not None:
                _check_fk(field, fk, visible)

            if isinstance(field, Record):
                _check_fields(field.fields, record=True, outer=inner)
            elif isinstance(field, Union):
                _check_fields(field.arms, outer=inner)
            elif isinstance(field, List):
                item = field.item
                # Each arm of a Union item is a distinct line form, checked like
                # a Record item of its own (a scalar arm has no siblings).
                for form in [item] if isinstance(item, Record) else item.arms.values():
                    if isinstance(form, Record):
                        _check_fields(form.fields, record=True)
                    else:
                        _check_fields({form.name: form})

    for block in (component.blocks or {}).values():
        _check_fields(block.fields)
    _check_fields(component.observations or {}, record=True)


def _keyset_column(component: "ComponentBase", path: str) -> "InputField":
    """The column a key set's `block.field` path names: a list's unscoped
    pk, or a string array. Raises if it names neither."""
    block_name, field_name = path.split(".")
    where = f"{component.name}: key set path {path!r}"
    block = (component.blocks or {}).get(block_name)
    array = block.fields.get(field_name) if block else None
    if isinstance(array, Array) and array.dtype == "string":
        return array
    lst = _find_list_in_block(component, block_name)
    if lst is None or not isinstance(lst.item, Record):
        raise ValueError(f"{where}: {block_name!r} is not a list block or string array")
    column = lst.item.fields.get(field_name)
    pk: PrimaryKey | None = getattr(column, "pk", None)
    if column is None or pk is None:
        raise ValueError(f"{where}: {field_name!r} is not the pk of list {lst.name!r}")
    if pk.scope is not None:
        raise ValueError(f"{where}: the pk is scoped, so a key alone can't name a row")
    return column


def _validate_keys(component: "ComponentBase", spec: "Dfns") -> None:
    """Each declared key set's path is valid in the component: a list's
    unscoped pk or a string array (see `_keyset_column`), or `<=dim` with a
    dimension the component can see. Several paths name columns of one type.
    A `when` names a keyword option, as a field's does."""
    options = (component.blocks or {}).get("options")
    keywords = {n for n, f in (options.fields if options else {}).items() if isinstance(f, Keyword)}
    for name, keyset in (component.keys or {}).items():
        where = f"{component.name}: key set {name!r}"
        if keyset.when is not None and keyset.when not in keywords:
            raise ValueError(f"{where}: when={keyset.when!r} names no keyword option")
        if keyset.bound is not None:
            if keyset.bound not in spec.input_dims(component.name):
                raise ValueError(f"{where}: {keyset.path!r} names no dimension of {component.name}")
            continue
        columns = [_keyset_column(component, path) for path in keyset.paths]
        if len({isinstance(c, Integer) for c in columns}) > 1:
            paths = list(keyset.paths)
            raise ValueError(f"{where}: paths {paths!r} name columns of different types")


def _iter_files(fields: "Mapping[str, InputField]"):
    """Yield every File among ``fields`` (recursively) with its sibling fields."""
    for field in fields.values():
        match field:
            case File():
                yield field, fields
            case Record():
                yield from _iter_files(field.fields)
            case Union():
                yield from _iter_files(field.arms)
            case List():
                yield from _iter_files({field.item.name: field.item})


def _validate_file_links(component: "ComponentBase", spec: "Dfns") -> None:
    """
    For every File with ``component`` or ``component_ftype`` set:

    - it must be an input file;
    - ``component`` must resolve to at least one of this component's
      children (see `Dfns.children`);
    - without ``component_ftype``, it must resolve to one ftype family (a base
      and its array-based variants, see `Dfns.ftype`);
    - ``component_ftype`` must name a sibling String in the same record.
    """
    blocks = list((component.blocks or {}).values())
    for block in blocks:
        for file, siblings in _iter_files(block.fields):
            if file.component is None and file.component_ftype is None:
                continue
            where = f"{component.name}: File {file.name!r}"
            if file.direction != "in":
                raise ValueError(f"{where}: only an input file may link a component")
            if file.component is None:
                raise ValueError(f"{where}: component_ftype without component")
            targets = [
                n for n, c in spec.children(component.name).items() if admits(file.component, c)
            ]
            if not targets:
                raise ValueError(
                    f"{where}: component={file.component!r} matches none of this "
                    f"component's children"
                )
            if file.component_ftype is None:
                components = spec.components
                families = {components[n].ftype or n for n in targets}
                if len(families) > 1:
                    raise ValueError(
                        f"{where}: component={file.component!r} matches several "
                        f"components {sorted(targets)} and has no component_ftype"
                    )
            elif not isinstance(siblings.get(file.component_ftype), String):
                raise ValueError(
                    f"{where}: component_ftype={file.component_ftype!r} is not a sibling "
                    f"String field in the same record"
                )


def _is_cellid(field: "InputField") -> bool:
    """Whether `field` is a cellid, or an array of them."""
    return isinstance(field, CellID) or (isinstance(field, Array) and field.dtype == "cellid")


def _validate_cellid_fields(component: "ComponentBase") -> None:
    """
    A cellid (a `CellID`, or an `Array` with dtype="cellid") is only
    meaningful as a column in a list item, where each row names its cell(s),
    or in an observation field, which reads like one.

    Which grid a cellid refers to (its `model`) must be unambiguous: a
    `model` names one of the component's parameters whose type admits a
    model (see `Param`); an exchange's cellids refer to one of its two
    models, never its own, so each must name one; and a list item naming a
    model on one cellid column must name one on every cellid column (GNC's
    `cellidn`, `cellidm`, `cellidsj`).
    """
    exchange = getattr(component, "subtype", None) == "exchange"
    model_params = {
        n
        for n, p in (component.params or {}).items()
        if any(t in ("model", "*") or t.endswith("-nam") for t in _parents_as_set(p.type))
    }

    def _cellids(field: "InputField", in_item: bool) -> "list[list[CellID | Array]]":
        """The cellid columns of each way a row may read `field`: one
        alternative per union arm, combined with the cellids beside it."""
        if _is_cellid(field):
            assert isinstance(field, (CellID, Array))
            if not in_item:
                raise ValueError(
                    f"{type(field).__name__} {field.name!r}: a cellid is only valid as a "
                    f"column in a list item"
                )
            if exchange and field.model is None:
                raise ValueError(
                    f"{type(field).__name__} {field.name!r}: an exchange's cellid must say "
                    f"which model's grid it refers to, by a parameter"
                )
            if field.model is not None and field.model not in model_params:
                raise ValueError(
                    f"{type(field).__name__} {field.name!r}: model={field.model!r} names no "
                    f"parameter of {component.name} whose type is a model"
                )
            return [[field]]
        if isinstance(field, List):
            _check_item(field.item)
        elif isinstance(field, Record):
            rows: list[list[CellID | Array]] = [[]]
            for subfield in field.fields.values():
                rows = [row + alt for row in rows for alt in _cellids(subfield, in_item)]
            return rows
        elif isinstance(field, Union):
            # Arms are alternatives, never read together in one row.
            return [alt for arm in field.arms.values() for alt in _cellids(arm, in_item)]
        return [[]]

    def _check_item(item: "InputField") -> None:
        for cellids in _cellids(item, True):
            if len({c.model is None for c in cellids}) > 1:
                names = {c.name: c.model for c in cellids}
                raise ValueError(
                    f"Cellid columns {names!r} mix model=None with a named model: if one "
                    f"names a model, every cellid column in the item must"
                )

    for block in (component.blocks or {}).values():
        for field in block.fields.values():
            _cellids(field, False)
    for obs_field in (component.observations or {}).values():
        _check_item(obs_field)


def _validate_when_fields(component: "ComponentBase") -> None:
    """Every field's `when` (at any depth) names a keyword in the
    component's options block, or one of its parameters (see `Param`), which
    switches the field on when it's set. A keyword can't name itself."""
    options = (component.blocks or {}).get("options")
    keywords = {n for n, f in (options.fields if options else {}).items() if isinstance(f, Keyword)}
    names = keywords | set(component.params or {})
    fields = [f for block in (component.blocks or {}).values() for f in block.fields.values()]
    for field in [*fields, *(component.observations or {}).values()]:
        for f in _iter_subfields(field):
            if f.when is None:
                continue
            if f.when not in names:
                raise ValueError(
                    f"{f.name!r}: when={f.when!r} names no keyword option or parameter of "
                    f"{component.name}"
                )
            if f.when == f.name:
                raise ValueError(f"{f.name!r}: when={f.when!r} names the field itself")


def _binders(
    component: "ComponentBase", spec: "Dfns"
) -> "list[tuple[ComponentBase, Mapping[str, InputField]]]":
    """Each component that can bind this one's file, with the binding row:
    the fields beside the File that links it. A component's `parent` must
    admit the binder too."""
    out: list[tuple[ComponentBase, Mapping[str, InputField]]] = []
    for binder in spec.components.values():
        if component.parent is not None and not admits(component.parent, binder):
            continue
        for block in (binder.blocks or {}).values():
            for file, siblings in _iter_files(block.fields):
                if file.direction == "in" and file.component and admits(file.component, component):
                    out.append((binder, siblings))
    return out


def _validate_params(component: "ComponentBase", spec: "Dfns") -> None:
    """
    Each parameter (see `Param`) resolves under every component that binds
    this one:

    - its `type` admits some component in the spec;
    - each binder named in a `from` table binds this component;
    - `parent`: the binder is of the parameter's type;
    - `row.<column>`: the binding row has the column, with an fk, and what
      the column can name (see `_named_components`) includes something of
      the parameter's type;
    - `parent.<param>`: the binder declares that parameter, and its type
      can name something of this one's type.

    Fks, cellids and `when`s that name a parameter are checked with the
    fields they're on.
    """
    if not component.params:
        return
    binders = _binders(component, spec)
    binder_names = {b.name for b, _ in binders}
    for name, param in component.params.items():
        where = f"{component.name}: parameter {name!r}"
        admitted = _param_components(spec, component, name)
        if not admitted:
            raise ValueError(f"{where}: type={param.type!r} admits no component in the spec")
        if isinstance(param.from_, dict):
            if unknown := sorted(set(param.from_) - binder_names):
                raise ValueError(f"{where}: {unknown!r} don't bind {component.name}")
        for binder, row in binders:
            source = param.source_for(binder.name)
            if source is None:
                continue
            under = f"{where} under {binder.name}"
            kind, _, rest = source.partition(".")
            if kind == "parent" and not rest:
                if not admits(param.type, binder):
                    raise ValueError(f"{under}: the binder isn't of type {param.type!r}")
            elif kind == "parent":
                if rest not in (binder.params or {}):
                    raise ValueError(f"{under}: {binder.name} declares no parameter {rest!r}")
                if not _param_components(spec, binder, rest) & admitted:
                    raise ValueError(f"{under}: {binder.name}'s {rest!r} names no {param.type!r}")
            else:
                column = row.get(rest)
                if column is None:
                    raise ValueError(f"{under}: the binding row has no column {rest!r}")
                if getattr(column, "fk", None) is None:
                    raise ValueError(f"{under}: the binding row's {rest!r} has no fk to follow")
                if not _named_components(spec, binder, row, column) & admitted:
                    raise ValueError(f"{under}: {rest!r} names nothing of type {param.type!r}")


def _obs_columns(field: "InputField") -> list[int]:
    """How many `utl-obs` columns each form of an observation field fills."""
    if isinstance(field, Union):
        return [n for arm in field.arms.values() for n in _obs_columns(arm)]
    return [len(field.fields) if isinstance(field, Record) else 1]


def _validate_observations(component: "ComponentBase") -> None:
    """
    Each observation field (see `ObservationField`) must be untagged
    throughout and fill one or two columns, `id` and optionally `id2`.
    Its fks are checked by `_validate_fk_fields`.
    """
    for obstype, field in (component.observations or {}).items():
        where = f"Observation {obstype!r}"
        if obstype != obstype.lower():
            raise ValueError(f"{where}: name must be lower case")
        tagged = [f.name for f in _iter_subfields(field) if f.tagged]
        if tagged:
            raise ValueError(f"{where}: {tagged} must be untagged")
        if any(n not in (1, 2) for n in _obs_columns(field)):
            raise ValueError(f"{where}: each form must fill id and at most id2")


def _iter_subfields(field: "InputField"):
    """Yield ``field`` and every field nested in it."""
    yield field
    for child in getattr(field, "children", {}).values():
        yield from _iter_subfields(child)


def _validate_array_shapes(
    component: "ComponentBase",
    component_name: str,
    spec: "Dfns",
) -> None:
    """
    Validate all Array.shape elements in a component.
    """
    if not component.blocks:
        return

    known_dims = spec.input_dims(component_name)

    def _check_list(lst: "List") -> None:
        for elem in lst.shape:
            _validate_list_shape_element(elem, lst, known_dims)

    def _check_array(arr: "Array", enclosing: "Record | None") -> None:
        if not arr.shape:
            # Self-sizing (shape=[]) is valid at the top level and as the rightmost
            # subfield of a record: a row's layout is fixed by the component's
            # dimensions, except for its last field.
            if enclosing is not None:
                fields_list = list(enclosing.fields.keys())
                if not fields_list or fields_list[-1] != arr.name:
                    raise ValueError(
                        f"Array {arr.name!r}: only the rightmost field in a record may "
                        f"have an undeclared shape (self-sizing)"
                    )
            return  # self-sizing: nothing to validate
        for elem in arr.shape:
            _validate_shape_element(elem, arr, component, enclosing, known_dims, spec)

    for block in component.blocks.values():
        for field in block.fields.values():
            if isinstance(field, Array):
                _check_array(field, None)

            elif isinstance(field, Record):
                for subfield in field.fields.values():
                    if isinstance(subfield, Array):
                        _check_array(subfield, field)

            elif isinstance(field, List):
                if field.shape:
                    _check_list(field)
                item = field.item
                if isinstance(item, Record):
                    for subfield in item.fields.values():
                        if isinstance(subfield, Array):
                            _check_array(subfield, item)


def _validate_memory_shapes(
    component: "ComponentBase",
    component_name: str,
    spec: "Dfns",
) -> None:
    """Validate MemoryVariable shape elements against known dims.

    Every shape element must be a plain identifier (dim name).  Expressions,
    arithmetic, and other non-identifier forms are not allowed — MODFLOW
    allocates memory arrays by scalar variable, never by expression.
    """
    if not component.memory:
        return
    known = spec.dims(component_name)
    for var_name, var in component.memory.items():
        for elem in getattr(var, "shape", []):
            if not _DIM_RE.fullmatch(elem):
                raise ValueError(
                    f"MemoryVariable {var_name!r} shape element {elem!r} "
                    f"must be a plain identifier (dim reference)"
                )
            if elem not in known:
                raise ValueError(
                    f"MemoryVariable {var_name!r} shape element {elem!r} "
                    f"is not a known dimension in {component_name!r}"
                )


def _validate_memory_source(
    component: "ComponentBase",
    component_name: str,
) -> None:
    """Validate MemoryVariable source references.

    A string source must name a field in the component's blocks.
    A list source must name memory variables in the same component.
    """
    if not component.memory:
        return
    all_field_names = set(component.get_fields(recurse=True).keys())
    all_mem_names = set(component.memory.keys())
    for var_name, var in component.memory.items():
        if var.source is None:
            continue
        if isinstance(var.source, str):
            if var.source not in all_field_names:
                raise ValueError(
                    f"MemoryVariable {var_name!r} source {var.source!r} "
                    f"does not name a field in {component_name!r}"
                )
        else:
            for ref in var.source:
                if ref not in all_mem_names:
                    raise ValueError(
                        f"MemoryVariable {var_name!r} source {ref!r} "
                        f"does not name a memory variable in {component_name!r}"
                    )


def _validate_memory_futility(
    component: "ComponentBase",
    component_name: str,
) -> None:
    """Raise if any memory variable is set in {fc, cq} but not readonly.

    Variables overwritten every formulate or calculate-flows step have no
    legitimate write use case; they must be marked readonly.  A non-readonly
    fc/cq variable is a schema authoring error, not a runtime warning.
    """
    if not component.memory:
        return
    for var_name, var in component.memory.items():
        hooks = {var.set_in} if isinstance(var.set_in, str) else set(var.set_in or [])
        overwritten = hooks & {"fc", "cq"}
        if overwritten and not var.readonly:
            raise ValueError(
                f"MemoryVariable {var_name!r} in {component_name!r} has "
                f"hook {sorted(overwritten)} but readonly=False; variables "
                f"overwritten each formulate/calculate-flows step must be readonly"
            )


def _inject_field_names(fields: dict) -> None:
    """
    Recursively inject name from dict key into field dicts.
    Necessary to compensate for field names being absent in
    serialized DFN file data.
    """
    for field_name, field in fields.items():
        field.setdefault("name", field_name)
        _inject_field_names(field.get("fields") or {})  # Record.fields
        _inject_field_names(field.get("arms") or {})  # Union.arms
        item = field.get("item")
        if isinstance(item, dict):
            # List._serialize keeps the item's name; fall back to the list's
            # for files written without it.
            item.setdefault("name", field_name)
            _inject_field_names(item.get("fields") or {})
            _inject_field_names(item.get("arms") or {})


def _inject_names(comp_data: dict) -> None:
    """
    Inject block and field names from dict keys before Pydantic validation.
    Necessary to compensate for field and block names being absent in
    serialized DFN file data.
    """
    _inject_field_names(comp_data.get("observations") or {})
    for block_name, block in (comp_data.get("blocks") or {}).items():
        block.setdefault("name", block_name)
        _inject_field_names(block.get("fields") or {})
        header = block.get("header")
        if isinstance(header, dict):
            header_field = header.get("field")
            if isinstance(header_field, dict):
                # header.field's own name is preserved verbatim by Block._serialize
                # (it isn't stored in a name-keyed dict like `fields`); only its
                # nested children need names injected from their dict keys.
                _inject_field_names(header_field.get("fields") or {})
                _inject_field_names(header_field.get("arms") or {})


class Dfns(BaseModel):
    """A set of component definitions."""

    components: dict[str, Component] = PydanticField(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def schema_version(self) -> str:
        for c in self.components.values():
            if c.schema_version is not None:
                return c.schema_version
        return CURRENT_SCHEMA_VERSION

    @property
    def root(self) -> "Simulation | None":
        """The root (simulation) component, or None if not present."""
        for c in self.components.values():
            if isinstance(c, Simulation):
                return c
        return None

    def children(self, name: str) -> "dict[str, Component]":
        """Components whose parent admits ``name`` (see `admits`)."""
        component = self.components[name]
        return {
            n: c for n, c in self.components.items() if n != name and admits(c.parent, component)
        }

    def ftype_family(self, token: str, context: str) -> list[str]:
        """
        The components a name-file ftype token can mean among ``context``'s
        children: ``DIS6`` in ``gwf-nam`` → ``["gwf-dis"]``, ``RCH6`` →
        ``["gwf-rch", "gwf-rcha"]``. More than one is a variant family, which
        the target file's own options pick between.
        """
        token = token.upper()
        return sorted(n for n, c in self.children(context).items() if c.ftype == token)

    def _parents_in_models(self, parent: "str | list[str] | None") -> set[str]:
        """
        ``parent``'s terms, plus, for a concrete package term (``utl-tvk``'s
        ``gwf-npf``), that package's own parents, transitively. A subpackage
        sits in whatever model its parent package does.
        """
        result: set[str] = set()
        todo = list(_parents_as_set(parent))
        while todo:
            p = todo.pop()
            if p in result:
                continue
            result.add(p)
            c = self.components.get(p)
            if isinstance(c, Package):
                todo.extend(_parents_as_set(c.parent))
        return result

    def local_dims(self, component_name: str) -> set[str]:
        """All dim names declared in this component, both input and runtime."""
        component = self.components[component_name]
        return set((component.dims or {}).keys()) | set((component.runtime_dims or {}).keys())

    def local_runtime_dims(self, component_name: str) -> set[str]:
        """Runtime dim names declared locally."""
        return set((self.components[component_name].runtime_dims or {}).keys())

    def _inherited_dim_names(
        self,
        component_name: str,
        dicts: "Callable[[Component], dict[str, InputDim] | dict[str, RuntimeDim] | None]",
    ) -> set[str]:
        """Names from ``dicts(c)`` on every other component, filtered by scope visibility."""
        inherited: set[str] = set()
        component = self.components[component_name]
        req_parent = component.parent
        req_model_parents = list(self._parents_in_models(req_parent))
        for cname, c in self.components.items():
            if cname == component_name:
                continue
            for dim_name, dim in (dicts(c) or {}).items():
                match dim.scope:
                    case "simulation":
                        inherited.add(dim_name)
                    case "model":
                        if _receives_from(
                            req_model_parents, c.parent, requester_name=component_name
                        ):
                            inherited.add(dim_name)
                    case "component":
                        if cname in _parents_as_set(req_parent):
                            inherited.add(dim_name)
        return inherited

    def inherited_dims(self, component_name: str) -> set[str]:
        """
        Dim names (input and runtime) visible to ``component_name`` from other components.

        - ``"simulation"`` scope: always visible.
        - ``"model"`` scope: visible when the requesting component can share a
          model with the dim-defining component, determined purely from parent
          attributes (no hardcoded model-type strings).
        - ``"component"`` scope: visible when the dim-defining component is
          explicitly listed as a parent of the requesting component (subpackage).
        """
        return self._inherited_dim_names(
            component_name, lambda c: c.dims
        ) | self._inherited_dim_names(component_name, lambda c: c.runtime_dims)

    def input_dims(self, component_name: str) -> set[str]:
        """
        Input dim names visible to ``component_name``, valid in input field shapes.

        Excludes runtime dims: a sequential parser must know an array's size
        before reading it, so input arrays may not be sized by a dim whose
        value is only known at runtime.
        """
        local = set((self.components[component_name].dims or {}).keys())
        return local | self._inherited_dim_names(component_name, lambda c: c.dims)

    def dims(self, component_name: str) -> set[str]:
        """
        All dim names (input and runtime) visible to ``component_name`` for
        shape resolution. Used for memory variable shape validation.
        """
        return self.local_dims(component_name) | self.inherited_dims(component_name)

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "Dfns":
        versions = {
            c.schema_version for c in self.components.values() if c.schema_version is not None
        }
        if len(versions) > 1:
            raise ValueError(
                f"All components must share the same schema_version; "
                f"found: {sorted(str(v) for v in versions)}"
            )
        return self

    @model_validator(mode="after")
    def _validate_relations(self) -> "Dfns":
        for name, component in self.components.items():
            if component.dims:
                _resolve_derived_dims(component, self.dims(name))
        for name, component in self.components.items():
            _validate_keys(component, self)
        for name, component in self.components.items():
            _validate_fk_fields(component, self)
        for name, component in self.components.items():
            _validate_file_links(component, self)
        for name, component in self.components.items():
            _validate_params(component, self)
        for name, component in self.components.items():
            _validate_cellid_fields(component)
        for name, component in self.components.items():
            _validate_when_fields(component)
        for name, component in self.components.items():
            _validate_observations(component)
        for name, component in self.components.items():
            _validate_array_shapes(component, name, self)
        for name, component in self.components.items():
            _validate_memory_shapes(component, name, self)
        for name, component in self.components.items():
            _validate_memory_source(component, name)
        for name, component in self.components.items():
            _validate_memory_futility(component, name)
        return self

    @classmethod
    def load(cls, path: str | PathLike) -> "Dfns":
        """Load a directory of definition files."""

        exclude = {"common", "flopy"}
        path = Path(path).expanduser().resolve()
        dfn_paths = {p.stem: p for p in sorted(path.glob("*.dfn")) if p.stem not in exclude}
        toml_paths = {p.stem: p for p in sorted(path.glob("*.toml")) if p.stem not in exclude}
        yaml_paths = {
            p.stem: p
            for ext in ("*.yaml", "*.yml")
            for p in sorted(path.glob(ext))
            if p.stem not in exclude
        }
        json_paths = {p.stem: p for p in sorted(path.glob("*.json")) if p.stem not in exclude}

        dfns: dict = {}
        if dfn_paths:
            from modflow_devtools.dfn import schema as v1
            from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import migrate_corpus
            from modflow_devtools.dfns.migrate_to_v2_0_0_dev3 import to_v2_0_0_dev3

            common_path = path / "common.dfn"
            common = None
            if common_path.is_file():
                with common_path.open() as f:
                    common, _ = v1.Dfn.load_dfn(f)  # type: ignore[attr-defined]

            raw = {}
            for stem, dfn_path in dfn_paths.items():
                with dfn_path.open() as f:
                    raw[stem] = v1.Dfn.load_dfn(f, common=common)  # type: ignore[attr-defined]
            # to_v2_0_0_dev3 runs to_v2_0_0_dev2 itself as its first step, so this
            # yields CURRENT_SCHEMA_VERSION components, not dev2 ones.
            dfns = dict(migrate_corpus(raw, to_v2_0_0_dev3))
        elif toml_paths:
            import tomli

            for toml_path in toml_paths.values():
                with toml_path.open("rb") as f:
                    dfn = tomli.load(f)
                _inject_names(dfn)
                dfns[dfn["name"]] = dfn
        elif yaml_paths:
            import yaml

            for yaml_path in yaml_paths.values():
                with yaml_path.open() as f:
                    dfn = yaml.safe_load(f)
                _inject_names(dfn)
                dfns[dfn["name"]] = dfn
        elif json_paths:
            import json

            for json_path in json_paths.values():
                with json_path.open() as f:
                    dfn = json.load(f)
                _inject_names(dfn)
                dfns[dfn["name"]] = dfn

        return cls(components=dfns)
