import ast
import re
from collections.abc import Callable, Mapping
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from boltons.dictutils import OMD
from pydantic import (
    BaseModel,
    SerializationInfo,
    computed_field,
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


class Keyword(InputFieldBase):
    type: Literal["keyword"] = PydanticField(default="keyword", frozen=True)


class String(InputFieldBase):
    type: Literal["string"] = PydanticField(default="string", frozen=True)
    valid: list[str] | None = None
    case_sensitive: bool = False
    time_series: bool = False
    pk: bool = False
    fk: str | None = None
    fk_ref: str | None = None


class Integer(InputFieldBase):
    type: Literal["integer"] = PydanticField(default="integer", frozen=True)
    valid: list[int] | None = None
    time_series: bool = False
    index: bool = False
    pk: bool = False
    fk: str | None = None
    fk_ref: str | None = None
    node: bool = False


class Double(InputFieldBase):
    type: Literal["double"] = PydanticField(default="double", frozen=True)
    time_series: bool = False


class File(InputFieldBase):
    type: Literal["file"] = PydanticField(default="file", frozen=True)
    direction: Literal["in", "out"]


Scalar = Annotated[
    Keyword | String | Integer | Double | File,
    PydanticField(discriminator="type"),
]


class Array(InputFieldBase):
    type: Literal["array"] = PydanticField(default="array", frozen=True)
    dtype: Literal["keyword", "integer", "double", "string"]
    shape: list[str] = []
    time_series: bool = False
    layered: bool = False
    index: bool = False
    fk: str | None = None

    @model_validator(mode="after")
    def _check_index_dtype(self) -> "Array":
        if self.index and self.dtype != "integer":
            raise ValueError(
                f"Array {self.name!r}: index=True requires dtype='integer', got {self.dtype!r}"
            )
        if self.fk is not None and self.dtype != "integer":
            raise ValueError(
                f"Array {self.name!r}: fk requires dtype='integer', got {self.dtype!r}"
            )
        return self


class Record(InputFieldBase):
    type: Literal["record"] = PydanticField(default="record", frozen=True)
    fields: "dict[str, Scalar | Array | Record | Union]" = PydanticField(default_factory=dict)

    @property
    def children(self) -> "dict[str, InputField]":
        return self.fields  # type: ignore[return-value]


class Union(InputFieldBase):
    type: Literal["union"] = PydanticField(default="union", frozen=True)
    arms: "dict[str, Scalar | Array | Record]" = PydanticField(default_factory=dict)

    @property
    def children(self) -> "dict[str, InputField]":
        return self.arms  # type: ignore[return-value]


def _item_tags(item: "Record | Union") -> list[str] | None:
    """The keyword(s) a list item type begins with, or None if it isn't
    keyword-led. A Record item must be keyword-led in the `_leading_tags`
    sense; so must every arm of a Union item, since each arm is a distinct
    line form the item type allows."""
    tags = []
    for form in [item] if isinstance(item, Record) else item.arms.values():
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
            return [field.name]
        case String() | Integer() | Double() | Array() | File():
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


class List(InputFieldBase):
    type: Literal["list"] = PydanticField(default="list", frozen=True)
    # Derived from `item`, like `Block.optional`: a list is tagged iff its item
    # type is keyword-led (see `_item_tags`). A tagged list's items can be told
    # apart from the block's other fields, so unlike an untagged list it needn't
    # be the last or only list in its block. Never serialized. A hidden field
    # rather than a property because pydantic can't override an inherited field
    # with one, so it's re-derived wherever pydantic skips validation (see
    # `model_copy`).
    tagged: SkipJsonSchema[bool] = PydanticField(default=False, exclude=True)
    item: "Record | Union"
    shape: list[str] = []

    @model_validator(mode="after")
    def _derive_tagged(self) -> "List":
        tagged = _item_tags(self.item) is not None
        if "tagged" in self.model_fields_set and self.tagged != tagged:
            raise ValueError(
                f"List {self.name!r}: tagged={self.tagged!r} contradicts its item, "
                f"whose type {'is' if tagged else 'is not'} keyword-led"
            )
        object.__setattr__(self, "tagged", tagged)
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> "List":
        if update and "tagged" in update:
            raise ValueError(f"List {self.name!r}: tagged is derived from item, not settable")
        copy = super().model_copy(update=update, deep=deep)
        object.__setattr__(copy, "tagged", _item_tags(copy.item) is not None)
        return copy

    @property
    def item_tags(self) -> list[str]:
        """The keywords this list's item type begins with (empty if untagged)."""
        return _item_tags(self.item) or []

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        if info.context and info.context.get("strip_names"):
            data.pop("name", None)
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
    Keyword | String | Integer | Double | File | Array | Record | Union | List,
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
    return f"({', '.join(field.shape)})" if field.shape else ""


def _render_file(field: "File") -> str:
    keyword = "FILEIN" if field.direction == "in" else "FILEOUT"
    if not field.tagged:
        return f"{keyword} <{field.name}>"
    return f"{field.name.upper()} {keyword} <{field.name}>"


def _tag(field: "InputField", inner: str) -> str:
    """Prefix `inner` with the field's uppercased name if it's tagged."""
    return f"{field.name.upper()} {inner}" if field.tagged else inner


def _ts_token(token: str, *, time_series: bool) -> str:
    return f"<@{token}@>" if time_series else f"<{token}>"


def _render_rows(item: "Record | Union") -> list[str]:
    if isinstance(item, Record):
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
        return f"[{token}]" if field.optional else token

    match field:
        case Keyword():
            return _wrap(field.name.upper())
        case String() | Integer() | Double():
            token = _ts_token(field.name, time_series=field.time_series)
            return _wrap(_tag(field, token))
        case File():
            return _wrap(_render_file(field))
        case Array():
            if inline or not field.shape:
                token = _ts_token(
                    f"{field.name}{_render_shape(field)}", time_series=field.time_series
                )
                return _wrap(_tag(field, token))
            name_line = field.name.upper()
            if field.layered:
                name_line += " [LAYERED]"
            if field.netcdf:
                name_line += " $[NETCDF]$"
            body = f"{name_line}\n  <{field.name}{_render_shape(field)}> -- READARRAY"
            return _wrap(body)
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
            # Bare identifier: must name an Integer field in this component
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


class BlockHeader(BaseModel):
    """A repeating block's header field, plus whether a missing occurrence means
    "reuse the prior occurrence's values" (`period`, e.g.). Nested here rather
    than a sibling flag on `Block` so it can't be set without a header.

    An `Integer` header is inherently a sequential key -- both `period`'s
    `iper` and `solutiongroup`'s `group_num` are documented as monotonically
    increasing across occurrences, whether or not they fill forward. It's
    only what a *gap* in that sequence means that varies.
    """

    field: InputField
    fill_forward: bool = False

    @model_validator(mode="after")
    def _check_fill_forward_requires_integer(self) -> "BlockHeader":
        if self.fill_forward and not isinstance(self.field, Integer):
            raise ValueError(
                "BlockHeader: fill_forward requires an Integer field; "
                f"got {type(self.field).__name__}"
            )
        return self


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
        # other field in the block may begin with the same one.
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


class ComponentBase(BaseModel):
    schema_version: str | None = None
    name: str
    parent: str | list[str] | None = None
    dims: dict[str, InputDim] | None = None
    runtime_dims: dict[str, RuntimeDim] | None = None
    blocks: dict[str, Block] | None = None
    memory: dict[str, MemoryVariable] | None = None

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
_ARITH_RE = re.compile(r"^([A-Za-z_]\w*)\s*[+-]\s*\d+$")


def _find_list_in_block(component: "ComponentBase", block_name: str) -> "List | None":
    """Return the first List field in the named block, or None."""
    block = (component.blocks or {}).get(block_name)
    if block is None:
        return None
    for f in block.fields.values():
        if isinstance(f, List):
            return f
    return None


def _validate_shape_element(
    element: str,
    array_field: "Array",
    component: "ComponentBase",
    enclosing_record: "Record | None",
    known_dims: set[str],
    spec: "Dfns | None" = None,
) -> None:
    """
    Validate one element of an Array.shape list.

    Valid forms:
      - Dim reference  ``^[A-Za-z_]\\w*$``
        Must resolve in the 3-level scope: explicit → derived → grid dims.
      - Row-level column lookup  ``^(\\w+)\\.(\\w+)\\((\\w+)\\)$``
        Structural checks (see plan §Shape element parsing).

    Raises ValueError on any violation.
    """
    # strip bounds (<, >, <=, >=) and validate the core identifier
    if bound_m := _BOUND_RE.match(element):
        core = element[bound_m.end() :]
        if not _DIM_RE.fullmatch(core):
            raise ValueError(
                f"Array {array_field.name!r} has invalid shape element {element!r}: "
                f"must be a plain identifier after the bound operator"
            )
        if core in known_dims:
            return
        if enclosing_record is not None:
            sibling = enclosing_record.fields.get(core)
            if isinstance(sibling, Integer):
                return
        raise ValueError(
            f"Array {array_field.name!r} shape element {element!r}: "
            f"{core!r} does not resolve to a known dim (explicit, derived, or grid)"
        )

    if _DIM_RE.fullmatch(element):
        if element in known_dims:
            return
        # Per-row varying shape: a sibling Integer with dimension="record" supplies
        # an inline count on the same line.
        if enclosing_record is not None:
            sibling = enclosing_record.fields.get(element)
            if isinstance(sibling, Integer):
                return
        raise ValueError(
            f"Array {array_field.name!r} shape element {element!r} "
            f"does not resolve to a known dim "
            f"(explicit, derived, or grid)"
        )

    if m := _LOOKUP_RE.fullmatch(element):
        component_ref, block_name, col_name, fk_field_name = m.groups()

        # array must be a subfield of a record, not a top-level block field
        if enclosing_record is None:
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r} is a "
                f"row-level lookup but the array is not inside a record"
            )

        # Resolve target component (cross-component reference or local)
        if component_ref is not None:
            if spec is None:
                raise ValueError(
                    f"Array {array_field.name!r} shape element {element!r}: "
                    f"cross-component reference requires a Dfns spec"
                )
            target = spec.components.get(component_ref)
            if target is None:
                raise ValueError(
                    f"Array {array_field.name!r} shape element {element!r}: "
                    f"component {component_ref!r} not found in spec"
                )
        else:
            target = component  # type: ignore

        # block_name must identify a list block in the target component
        list_field = _find_list_in_block(target, block_name)  # type: ignore
        if list_field is None:
            where = f"component {component_ref!r}" if component_ref else "this component"
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{block_name!r} is not a list block in {where}"
            )

        # col_name must be an Integer field in the list's item record
        item = list_field.item
        item_fields: dict = item.fields if isinstance(item, Record) else item.arms
        col_field = item_fields.get(col_name)
        if col_field is None:
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{col_name!r} is not a field in {list_field.name!r} item"
            )
        if not isinstance(col_field, Integer):
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{col_name!r} is {type(col_field).__name__}, must be Integer"
            )

        # fk_field_name must be a sibling field in the enclosing record
        fk_field = enclosing_record.fields.get(fk_field_name)
        if fk_field is None:
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{fk_field_name!r} is not a sibling field in the enclosing record"
            )

        # fk_field.fk must be set and its block portion must match block_name
        fk = getattr(fk_field, "fk", None)
        if fk is None:
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{fk_field_name!r}.fk is not set"
            )
        fk_block = fk.split(".")[0] if "." in fk else fk
        if fk_block != block_name:
            raise ValueError(
                f"Array {array_field.name!r} shape element {element!r}: "
                f"{fk_field_name!r}.fk = {fk!r} does not reference block {block_name!r}"
            )
        return

    # validate simple integer arithmetic
    if m := _ARITH_RE.fullmatch(element):
        dim_name = m.group(1)
        if dim_name in known_dims:
            return
        if enclosing_record is not None:
            sibling = enclosing_record.fields.get(dim_name)
            if isinstance(sibling, Integer):
                return
        raise ValueError(
            f"Array {array_field.name!r} shape element {element!r}: "
            f"{dim_name!r} does not resolve to a known dim "
            f"(explicit, derived, or grid)"
        )

    raise ValueError(
        f"Array {array_field.name!r} has invalid shape element {element!r}: "
        f"must be a dim reference (^[A-Za-z_]\\w*$), an arithmetic offset "
        f"(dim [+-] integer), or a row-level lookup (block.column(fk_field))"
    )


def _validate_list_shape_element(
    element: str,
    list_field: "List",
    known_dims: set[str],
) -> None:
    """
    Validate one element of a List.shape.

    Valid forms are a strict subset of array shape forms — no row-level lookup
    and no intra-record sibling reference, since lists are not inside records:
      - Plain dim reference
      - Bound-annotated dim reference (<, >, <=, >=)
      - Arithmetic offset (dim [+-] integer)
    """
    if bound_m := _BOUND_RE.match(element):
        core = element[bound_m.end() :]
        if not _DIM_RE.fullmatch(core):
            raise ValueError(
                f"List {list_field.name!r} has invalid shape element {element!r}: "
                f"must be a plain identifier after the bound operator"
            )
        if core not in known_dims:
            raise ValueError(
                f"List {list_field.name!r} shape element {element!r}: "
                f"{core!r} does not resolve to a known dim"
            )
        return

    if _DIM_RE.fullmatch(element):
        if element not in known_dims:
            raise ValueError(
                f"List {list_field.name!r} shape element {element!r} "
                f"does not resolve to a known dim"
            )
        return

    if m := _ARITH_RE.fullmatch(element):
        dim_name = m.group(1)
        if dim_name not in known_dims:
            raise ValueError(
                f"List {list_field.name!r} shape element {element!r}: "
                f"{dim_name!r} does not resolve to a known dim"
            )
        return

    raise ValueError(
        f"List {list_field.name!r} has invalid shape element {element!r}: "
        f"must be a dim reference (^[A-Za-z_]\\w*$), an arithmetic offset "
        f"(dim [+-] integer), or a bound-annotated dim (</<=/>/>=dim)"
    )


def _validate_fk_fields(component: "ComponentBase", spec: "Dfns") -> None:
    """
    For every Integer/String/Array field with fk or fk_ref set, validate
    structure. Array's `fk` (per-grid-cell rather than per-list-row) only
    ever uses the hierarchical-path form below — it has no `pk`/`fk_ref`
    counterpart (see `Array.fk`).

    Two forms (see docs/md/dfnspec.md, "Primary and foreign keys"); grid-cell
    references are a separate mechanism entirely (the `node` attribute, not an
    `fk` value — see `Integer.node`):

    - Hierarchical path fk ("[component.]block.field", no fk_ref): the named
      block must be a list block whose item has a pk field. Unqualified
      ("block.field"), the block is looked up in this component; qualified
      ("component.block.field"), it's looked up in the named component via
      `spec.components` instead.
    - Bare block name fk + fk_ref, or fk_ref alone: fk_ref must name a sibling
      String field in the same record, whose runtime value identifies the
      target component (and, with fk, the pk field is looked up in the block
      named by fk within that component). The target itself is only known at
      runtime, so no further structural check is possible statically.

    A hierarchical-path fk may not be combined with fk_ref.
    """
    if not component.blocks:
        return

    def _check_fields(fields: dict) -> None:
        for field in fields.values():
            fk: str | None = getattr(field, "fk", None)
            fk_ref: str | None = getattr(field, "fk_ref", None)

            if fk_ref is not None:
                if fk is not None and "." in fk:
                    raise ValueError(
                        f"Field {field.name!r}: fk={fk!r} may not be combined with "
                        f"fk_ref (only a bare block name may be)"
                    )
                sibling = fields.get(fk_ref)
                if not isinstance(sibling, String):
                    raise ValueError(
                        f"Field {field.name!r} fk_ref={fk_ref!r}: "
                        f"not a sibling String field in the same record"
                    )
                # fk (a bare block name, if set) and the component it lives in
                # are both resolved from fk_ref's runtime value — no further
                # static check is possible.
            elif fk is not None:
                parts = fk.split(".")
                target: ComponentBase
                if len(parts) == 3:
                    component_ref, block_name, _fk_field = parts
                    resolved = spec.components.get(component_ref)
                    if resolved is None:
                        raise ValueError(
                            f"Field {field.name!r} fk={fk!r}: "
                            f"component {component_ref!r} not found in spec"
                        )
                    target = resolved
                    where = f"component {component_ref!r}"
                elif len(parts) in (1, 2):
                    block_name = parts[0]
                    target = component
                    where = "this component"
                else:
                    raise ValueError(
                        f"Field {field.name!r} fk={fk!r}: "
                        f"must be a bare block name, 'block.field', or "
                        f"'component.block.field'"
                    )
                list_field = _find_list_in_block(target, block_name)
                if list_field is None:
                    raise ValueError(
                        f"Field {field.name!r} fk={fk!r}: "
                        f"{block_name!r} is not a list block in {where}"
                    )
                item = list_field.item
                item_fields: dict = item.fields if isinstance(item, Record) else item.arms
                has_pk = any(getattr(f, "pk", False) for f in item_fields.values())
                if not has_pk:
                    raise ValueError(
                        f"Field {field.name!r} fk={fk!r}: "
                        f"list {list_field.name!r} item has no pk=True field"
                    )

            if isinstance(field, Record):
                _check_fields(field.fields)
            elif isinstance(field, Union):
                _check_fields(field.arms)
            elif isinstance(field, List):
                item = field.item
                if isinstance(item, Record):
                    _check_fields(item.fields)

    for block in component.blocks.values():
        _check_fields(block.fields)


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
            # subfield of a record. The only invalid case is non-rightmost in a record:
            # subsequent fields on the same line would be unreadable.
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
            item.setdefault("name", field_name)
            _inject_field_names(item.get("fields") or {})
            _inject_field_names(item.get("arms") or {})


def _inject_names(comp_data: dict) -> None:
    """
    Inject block and field names from dict keys before Pydantic validation.
    Necessary to compensate for field and block names being absent in
    serialized DFN file data.
    """
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
        """Components whose parent matches ``name``."""
        return {n: c for n, c in self.components.items() if c.parent == name}

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
        for cname, c in self.components.items():
            if cname == component_name:
                continue
            for dim_name, dim in (dicts(c) or {}).items():
                match dim.scope:
                    case "simulation":
                        inherited.add(dim_name)
                    case "model":
                        if _receives_from(req_parent, c.parent, requester_name=component_name):
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
            _validate_fk_fields(component, self)
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
            from modflow_devtools.dfns.migrate_to_v2_0_0_dev3 import to_v2_0_0_dev3

            common_path = path / "common.dfn"
            common = None
            if common_path.is_file():
                with common_path.open() as f:
                    common, _ = v1.Dfn.load_dfn(f)  # type: ignore[attr-defined]

            for stem, dfn_path in dfn_paths.items():
                with dfn_path.open() as f:
                    fields, meta = v1.Dfn.load_dfn(f, common=common)  # type: ignore[attr-defined]
                # to_v2_0_0_dev3() runs to_v2_0_0_dev2() itself as its own first
                # step (same raw (name, fields, meta) input) -- this was calling
                # to_v2_0_0_dev2() directly and stopping there, silently leaving
                # every component one schema version behind CURRENT_SCHEMA_VERSION
                # (still true as of MODFLOW-ORG/modflow-devtools@develop). Confirmed
                # directly: Dfns.load() on a freshly-synced raw-.dfn directory (the
                # exact path a live RemoteDfnRegistry.spec(schema_version=
                # CURRENT_SCHEMA_VERSION) call takes) returned components with
                # schema_version == "2.0.0.dev2", not "2.0.0.dev3", with no error or
                # warning -- e.g. gwf-chdg's now-removed vestigial `maxbound`
                # DIMENSIONS field (see the dev3 migration fix in this same branch)
                # was still present, because the dev3-only fix never ran.
                dfns[stem] = to_v2_0_0_dev3(name=stem, fields=fields, meta=meta)
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
