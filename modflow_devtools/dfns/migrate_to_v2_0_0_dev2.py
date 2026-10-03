import ast
import re
from collections.abc import Callable, Mapping
from typing import Any, Literal

from boltons.dictutils import OMD

from modflow_devtools.dfn import schema as v1
from modflow_devtools.dfns import schema as v2
from modflow_devtools.misc import try_literal_eval

_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
_LOOKUP_RE = re.compile(r"^(\w+)\.(\w+)\((\w+)\)$")
_COL_FK_RE = re.compile(r"^([A-Za-z_]\w*)\(([A-Za-z_]\w*)\)$")
_DIS_RE = re.compile(r"^[a-z0-9]+-dis(?:v|u|2d|v1d|v2d)?$")

# v1 shapes that are wrong at the source. `utl-ts` `sfacval` is `(<time_series_name)`,
# naming a field that exists only in `utl-tas`; MF6 reads one SFACS value per
# time series name, so the count is exactly `time_series_names`.
_V1_SHAPE_FIXES: dict[tuple[str, str], str] = {
    ("utl-ts", "sfacval"): "(time_series_names)",
    ("gwf-sfr", "ic"): "(ncon(ifno))",
    ("gwf-lak", "connectiondata"): "(sum(nlakeconn))",
}


def _split_v1_bound(elem: str) -> tuple[str, str]:
    """
    Split a v1 shape element into a v2 bound operator and the bounded expression.

    v1 marks an upper bound with ``<`` (``shape (<nstp)``: at most ``nstp``)
    and reserves ``>`` for a lower bound. v2 has the full set of inequalities,
    where ``<`` is strict, so v1's markers become ``<=``/``>=``.
    """
    if elem[:1] in ("<", ">"):
        return f"{elem[0]}=", elem[1:].lstrip("=").strip()
    return "", elem


def try_parse_bool(v: Any, default: bool = False) -> bool:
    """
    Try to parse a boolean from a string.

    An empty string is treated as ``True`` rather than ``False``: DFN files
    allow a bare attribute line with no value (e.g. ``optional`` on its own
    line, as opposed to ``optional true``/``optional false``) to mean the
    attribute is set. ``load_dfn`` parses such a line to an empty string, as
    distinct from ``None``, which indicates the attribute wasn't present at
    all (and falls through to ``default``).
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", ""):
            return True
        if s == "false":
            return False
    return default


_DEPENDENT_VARS: dict[str, str] = {
    "gwf": "head",
    "gwt": "concentration",
    "gwe": "temperature",
    "chf": "stage",
    "olf": "stage",
    "swf": "stage",
    # prt: particle tracking; no scalar dependent variable
}

_OC_RTYPE_VALID: dict[str, list[str]] = {
    "gwf": ["HEAD", "BUDGET"],
    "gwt": ["CONCENTRATION", "BUDGET"],
    "gwe": ["TEMPERATURE", "BUDGET"],
    "chf": ["STAGE", "BUDGET"],
    "olf": ["STAGE", "BUDGET"],
    "swf": ["STAGE", "BUDGET"],
    "prt": ["BUDGET"],
}


def _scope_for(
    parent: "str | list[str] | None",
) -> "Literal['component', 'model', 'simulation']":
    """
    Derive the DimDef scope for dims in a component's dimensions block from its parent.

    - Parent is a model (``<type>-nam``) or a generic type (``"model"``,
      ``"package"``, ``"*"``) → ``"model"``
    - Parent is ``"sim-nam"`` (directly under simulation) → ``"simulation"``
    - Otherwise → ``"component"``
    """
    parents = ([parent] if isinstance(parent, str) else parent) if parent is not None else []
    for p in parents:
        if p == "sim-nam":
            return "simulation"
        if p.endswith("-nam") or p in ("model", "package", "*"):
            return "model"
    return "component"


def _dims_scope(
    name: str,
    parent: "str | list[str] | None",
) -> "Literal['component', 'model', 'simulation']":
    """
    Scope of the dims a component's dimensions block declares.

    Only a model's discretization and the simulation's TDIS declare dims that
    other components share (grid shape, ``nper``). Every other component's dims
    describe one instance of it -- two EVT packages in a model can have
    different ``nseg``, and every list package has its own ``maxbound`` -- so
    they're ``"component"``-scoped regardless of where the component sits.
    """
    if name == "sim-tdis" or _DIS_RE.match(name):
        return _scope_for(parent)
    return "component"


def _raw_dim_names(blocks: dict[str, v2.Block]) -> set[str]:
    """Names of all Integer fields in the dimensions block."""
    dim_block = blocks.get("dimensions")
    if not dim_block:
        return set()
    return {fname for fname, f in dim_block.fields.items() if isinstance(f, v2.Integer)}


def _parse_list_shape(s: str) -> list[str]:
    """
    Parse a v1 recarray shape string into a ``List.shape`` value.

    Only a bare identifier, optionally bound-marked (``<maxats``), is accepted —
    complex expressions such as ``sum(nlakeconn)`` are handled separately by
    ``_infer_list_shape_dims``.
    """
    if not s:
        return []
    s_clean = s.strip()
    if s_clean.startswith("(") and s_clean.endswith(")"):
        s_clean = s_clean[1:-1].strip()
    op, s_clean = _split_v1_bound(s_clean)
    if _IDENT_RE.fullmatch(s_clean):
        return [f"{op}{s_clean}"]
    return []


def _remap_list_shapes(
    blocks: dict[str, v2.Block],
    fn: "Callable[[str, str, v2.List], list[str] | None]",
) -> dict[str, v2.Block]:
    """
    Walk every List field in every block, calling ``fn(bname, fname, field)``.
    If ``fn`` returns a new shape list, replace the field's shape; otherwise
    leave it unchanged.  Returns a new blocks dict (immutable update pattern).
    """
    result = {}
    for bname, block in blocks.items():
        new_fields = {}
        changed = False
        for fname, field in block.fields.items():
            if isinstance(field, v2.List):
                new_shape = fn(bname, fname, field)
                if new_shape is not None:
                    field = field.model_copy(update={"shape": new_shape})
                    changed = True
            new_fields[fname] = field
        result[bname] = block.model_copy(update={"fields": new_fields}) if changed else block
    return result


def _normalize_n_prefix_shapes(
    blocks: dict[str, v2.Block],
    raw_dim_names: set[str],
) -> dict[str, v2.Block]:
    """
    Fix List shapes that use ``nFoo`` where the actual dimension is ``maxFoo``.

    Some v1 DFNs (e.g. ``gwf-mvr [packages]`` with ``shape (npackages)``) use
    an ``n``-prefixed name while the dimensions block defines the same quantity
    under a ``max``-prefixed name.  Normalise before building explicit dims.
    """

    def _fn(bname, fname, field):
        if not field.shape:
            return None
        op, elem = v2.split_bound(field.shape[0])
        if elem not in raw_dim_names and elem.startswith("n") and len(elem) > 1:
            candidate = "max" + elem[1:]
            if candidate in raw_dim_names:
                return [f"{op or ''}{candidate}"]
        return None

    return _remap_list_shapes(blocks, _fn)


def _build_explicit_dims(
    name: str,
    parent: "str | list[str] | None",
    blocks: dict[str, v2.Block],
) -> dict[str, v2.InputDim]:
    """Build the dims section from a component's dimensions block.

    ``nodes`` here is always the user-facing, pre-reduction grid cell count
    (what sizes K/TOP/BOTM/IDOMAIN); see dfnspec.md's "Dimensions" section
    for how this coexists with the runtime ``nodes``/``nodesuser`` dims dev3
    injects for memory variables.
    """
    dims: dict[str, v2.InputDim] = {}
    dim_block = blocks.get("dimensions")
    if not dim_block:
        return dims

    scope = _dims_scope(name, parent)
    for fname, field in dim_block.fields.items():
        if isinstance(field, v2.Integer):
            dims[fname] = v2.InputDim(value=fname, scope=scope)

    if scope == "model":
        has = set(dims.keys())
        if {"nlay", "nrow", "ncol"} <= has:
            dims["ncpl"] = v2.InputDim(value="nrow * ncol", scope="model")
            dims["nodes"] = v2.InputDim(value="nlay * nrow * ncol", scope="model")
            dims["ncelldim"] = v2.InputDim(value="3", scope="model")
        elif {"nlay", "ncpl"} <= has:
            dims["nodes"] = v2.InputDim(value="nlay * ncpl", scope="model")
            dims["ncelldim"] = v2.InputDim(value="2", scope="model")
        elif {"nrow", "ncol"} <= has:
            dims["ncpl"] = v2.InputDim(value="nrow * ncol", scope="model")
            dims["nodes"] = v2.InputDim(value="nrow * ncol", scope="model")
            dims["ncelldim"] = v2.InputDim(value="2", scope="model")
        elif "nodes" in has:
            dims["ncelldim"] = v2.InputDim(value="1", scope="model")

    return dims


def _sanitize_list_shapes(
    blocks: dict[str, v2.Block],
    known_dims: set[str],
) -> dict[str, v2.Block]:
    """
    Clear the shape of any List whose shape element doesn't resolve to a known
    dim.

    Advanced packages (LAK, SFR, GNC, transport packages, etc.) often carry
    ``shape (maxbound)`` in their v1 DFNs as a convention even though
    ``maxbound`` is not declared as a dimension.  The structurally correct v2
    representation for such lists is ``shape=[]``.
    """
    return _remap_list_shapes(
        blocks,
        lambda bname, fname, field: (
            []
            if field.shape
            and any(v2.split_bound(elem)[1] not in known_dims for elem in field.shape)
            else None
        ),
    )


def _resolve_dimensions(
    blocks: dict[str, v2.Block],
) -> tuple[dict[str, v2.Block], dict[str, v2.InputDim]]:
    """
    Detect self-sizing arrays whose name is referenced in another array's shape
    expression — those define a component-scoped dimension.

    Any array type qualifies (not just string). Returns the unchanged blocks
    alongside a dict of component-scoped DimDef entries.
    """
    self_sizing: set[str] = set()
    shape_refs: set[str] = set()

    def _scan(fields: Mapping[str, v2.InputField]) -> None:
        for name, field in fields.items():
            if isinstance(field, v2.Array):
                if not field.shape:
                    self_sizing.add(name)
                else:
                    for elem in field.shape:
                        _, elem = v2.split_bound(elem)
                        if _IDENT_RE.fullmatch(elem):
                            shape_refs.add(elem)
            if isinstance(field, v2.Record):
                _scan(field.fields)
            elif isinstance(field, v2.Union):
                _scan(field.arms)
            elif isinstance(field, v2.List):
                item = field.item
                _scan(item.fields if isinstance(item, v2.Record) else item.arms)

    for block in blocks.values():
        _scan(block.fields)

    array_dim_names = self_sizing & shape_refs
    # 'auxiliary' always defines naux even in grid-based packages where the aux
    # array has shape (nodes) and never references 'auxiliary' by name in a shape.
    if "auxiliary" in self_sizing:
        array_dim_names.add("auxiliary")
    array_dims = {
        n: v2.InputDim(value=f"len({n})", scope="component") for n in sorted(array_dim_names)
    }
    return blocks, array_dims


def _collect_item_int_fields(fields: Mapping[str, v2.InputField]) -> set[str]:
    """
    Return the names of Integer fields declared directly on a block's list-item
    record(s) (or item union arms), one level deep. These are candidate row
    identifiers — e.g. ``ifno`` in a ``packagedata`` recarray.
    """
    names: set[str] = set()

    def _scan_record(record: v2.Record) -> None:
        for fname, field in record.fields.items():
            if isinstance(field, v2.Integer):
                names.add(fname)

    def _scan(fields: Mapping[str, v2.InputField]) -> None:
        for field in fields.values():
            if isinstance(field, v2.Record):
                _scan_record(field)
            elif isinstance(field, v2.Union):
                _scan(field.arms)
            elif isinstance(field, v2.List):
                item = field.item
                if isinstance(item, v2.Record):
                    _scan_record(item)
                elif isinstance(item, v2.Union):
                    _scan(item.arms)

    _scan(fields)
    return names


def _resolve_relations(blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Detect and annotate primary/foreign-key relations between a component's
    blocks, from two independent signals:

    1. Shape-expression lookups: a v1 recarray shape like ``ncon(ifno)``
       names an array whose per-row length is looked up via a sibling
       ``ifno`` field in another block's ``packagedata`` row. The referenced
       column becomes ``pk``, the sibling becomes ``fk``.

    2. Same-name row identifiers: advanced/multi-instance packages (SFR,
       LAK, MAW, UZF, ...) define a numeric feature index once in
       ``packagedata`` and repeat it, identically named, as the leading
       column of other blocks addressing the same feature. Wherever the
       name recurs outside ``packagedata``, that occurrence becomes ``pk``
       and the others become ``fk``.

    Renamed identifiers (e.g. LAK's ``lakein``/``lakeout``) or genuinely
    ambiguous ones (LAK's period ``number``, which means a lake or an outlet
    number depending on the setting) aren't inferred here — see
    ``_fix_lak_relations`` and ``docs/md/sfr-lak-structure.md``.
    """
    pk_set: set[tuple[str, str]] = set()
    fk_map: dict[tuple[str, str], str] = {}

    def _scan_fields(block_name: str, fields: Mapping[str, v2.InputField]) -> None:

        def _scan_record(record: v2.Record) -> None:
            for field in record.fields.values():
                if isinstance(field, v2.Array):
                    for dim in field.shape:
                        if m := _LOOKUP_RE.fullmatch(v2.split_bound(dim)[1]):
                            pk_block, _, fk_fname = m.groups()
                            sibling = record.fields.get(fk_fname)
                            if sibling is not None and getattr(sibling, "fk", None) is None:
                                fk_map[(block_name, fk_fname)] = f"{pk_block}.{fk_fname}"
                                pk_set.add((pk_block, fk_fname))

        for field in fields.values():
            if isinstance(field, v2.Record):
                _scan_record(field)
            elif isinstance(field, v2.Union):
                _scan_fields(block_name, field.arms)
            elif isinstance(field, v2.List):
                item = field.item
                if isinstance(item, v2.Record):
                    _scan_record(item)
                elif isinstance(item, v2.Union):
                    _scan_fields(block_name, item.arms)

    for block_name, block in blocks.items():
        _scan_fields(block_name, block.fields)

    # Signal 2: same-name row identifiers, keyed off the `packagedata` block.
    pk_block_name = "packagedata"
    if pk_block_name in blocks:
        pk_names = _collect_item_int_fields(blocks[pk_block_name].fields)
        for block_name, block in blocks.items():
            if block_name == pk_block_name:
                continue
            for name in pk_names & _collect_item_int_fields(block.fields):
                pk_set.add((pk_block_name, name))
                fk_map.setdefault((block_name, name), f"{pk_block_name}.{name}")

    if not fk_map and not pk_set:
        return blocks

    def _resolve_fields(
        block_name: str, fields: Mapping[str, v2.InputField]
    ) -> dict[str, v2.InputField]:

        def _resolve_record(record: v2.Record) -> v2.Record:
            updates: dict = {}
            for fname, sf in record.fields.items():
                updated = sf
                if (block_name, fname) in fk_map and getattr(sf, "fk", None) is None:
                    updated = updated.model_copy(update={"fk": fk_map[(block_name, fname)]})
                if (block_name, fname) in pk_set and not getattr(sf, "pk", False):
                    updated = updated.model_copy(update={"pk": True})
                if updated is not sf:
                    updates[fname] = updated
            if not updates:
                return record
            return record.model_copy(
                update={"fields": {fn: updates.get(fn, sf) for fn, sf in record.fields.items()}}
            )

        result = {}
        for name, f in fields.items():
            if isinstance(f, v2.Record):
                f = _resolve_record(f)
            elif isinstance(f, v2.Union):
                f = f.model_copy(update={"arms": _resolve_fields(block_name, f.arms)})
            elif isinstance(f, v2.List):
                if isinstance(f.item, v2.Record):
                    f = f.model_copy(update={"item": _resolve_record(f.item)})
                else:
                    f = f.model_copy(
                        update={
                            "item": f.item.model_copy(
                                update={"arms": _resolve_fields(block_name, f.item.arms)}
                            )
                        }
                    )
            result[name] = f
        return result

    return {
        block_name: block.model_copy(update={"fields": _resolve_fields(block_name, block.fields)})
        for block_name, block in blocks.items()
    }


_LONELY_PK_FIELDS = (
    "packagedata",
    "perioddata",
    # DISU/DISV/DISV1D/DISV2D geometry lists: row identifiers by construction
    # (MF6 requires consecutive numbering from 1), never referenced by name
    # elsewhere in their own component. Distinct names because MF6 names the
    # block/list field after the geometry it holds, same idiom as
    # period/perioddata above.
    "vertices",
    "cell2d",
    "cell1d",
)


def _mark_lonely_pk(blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Mark the leading identifier column of a ``packagedata``/``perioddata``/
    geometry (``vertices``/``cell2d``/``cell1d``) recarray as ``pk`` even when
    nothing else in the component names the same field, so
    ``_resolve_relations``'s cross-block signal never fires (e.g. BUY's
    ``irhospec``, CSUB's ``icsubno``, ATS's ``iperats``, SPC's ``bndno``,
    DISV's ``icell2d``). These are still genuine row identifiers by
    construction (MODFLOW rejects a repeated one, or requires consecutive
    numbering) — they're just never referenced by name anywhere else in
    their own component, unlike SFR/MAW/LAK/UZF's `ifno` columns.

    Matches on the *list field's* name, not the enclosing block's — MF6
    names the period block ``period`` but its list field ``perioddata``.

    Conservative by design: only fires when the list field's item record
    leads with a required Integer column carrying no ``fk`` and no existing
    ``pk`` anywhere in the record. This deliberately excludes the FK side of
    relations like ``gwf-mvr.period.perioddata`` (leads with ``mname1``, a
    String — not an Integer identifier at all).
    """
    updated: dict[str, v2.Block] = {}
    for block_name, block in blocks.items():
        field_name = next((n for n in _LONELY_PK_FIELDS if n in block.fields), None)
        if field_name is None:
            continue
        field = block.fields[field_name]
        if not isinstance(field, v2.List) or not isinstance(field.item, v2.Record):
            continue
        record = field.item
        if not record.fields or any(getattr(f, "pk", False) for f in record.fields.values()):
            continue
        first_name, first = next(iter(record.fields.items()))
        if not isinstance(first, v2.Integer) or first.optional or first.fk is not None:
            continue
        new_record = record.model_copy(
            update={
                "fields": {
                    **record.fields,
                    first_name: first.model_copy(update={"pk": True}),
                }
            }
        )
        new_field = field.model_copy(update={"item": new_record})
        updated[block_name] = block.model_copy(
            update={"fields": {**block.fields, field_name: new_field}}
        )
    return {**blocks, **updated}


# Cellid columns in a list item record whose v1 shape omits the cellid's own
# width: either declared as a plain integer (one cellid), or as an integer array
# shaped only by the number of cellids (GNC's `cellidsj`). Everywhere else v1
# writes a cellid as `shape (ncelldim)`, which `_mark_cellids` recognizes
# mechanically; these are rewritten into that form by an explicit, audited
# per-field allowlist, since v1 has no attribute that signals a cellid
# (`numeric_index` only means "needs 1-based/0-based conversion"). In every
# entry here the list field's own name matches its enclosing block's name.
_CELLID_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "exg-chfgwf": ("exchangedata", ("cellidm1", "cellidm2")),
    "exg-gwegwe": ("exchangedata", ("cellidm1", "cellidm2")),
    "exg-gwfgwf": ("exchangedata", ("cellidm1", "cellidm2")),
    "exg-gwtgwt": ("exchangedata", ("cellidm1", "cellidm2")),
    "exg-olfgwf": ("exchangedata", ("cellidm1", "cellidm2")),
    "gwf-gnc": ("gncdata", ("cellidm", "cellidn", "cellidsj")),
}


def _as_cellid(field: v2.InputField) -> v2.InputField:
    """Rewrite an integer column as an `ncelldim`-led integer array, the axis
    `ncelldim` varying fastest (each cellid's components are contiguous)."""
    if isinstance(field, v2.Integer):
        base = field.model_dump(include=set(v2.InputFieldBase.model_fields))
        base.pop("type", None)  # the serializer restores it
        return v2.Array(**base, dtype="integer", shape=["ncelldim"])
    if isinstance(field, v2.Array) and field.dtype == "integer":
        if field.shape[:1] == ["ncelldim"]:
            return field
        return field.model_copy(update={"shape": ["ncelldim", *field.shape]})
    return field


def _fix_cellid_fields(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """Rewrite this component's known cellid columns into the standard
    `ncelldim`-shaped form. See `_CELLID_FIELDS`."""
    entry = _CELLID_FIELDS.get(name)
    if entry is None:
        return blocks
    block_name, field_names = entry
    block = blocks.get(block_name)
    if block is None:
        return blocks
    list_field = block.fields.get(block_name)
    if not isinstance(list_field, v2.List) or not isinstance(list_field.item, v2.Record):
        return blocks
    item = list_field.item
    updates = {
        fname: _as_cellid(item.fields[fname]) for fname in field_names if fname in item.fields
    }
    new_item = item.model_copy(update={"fields": {**item.fields, **updates}})
    new_list = list_field.model_copy(update={"item": new_item})
    new_block = block.model_copy(update={"fields": {**block.fields, block_name: new_list}})
    return {**blocks, block_name: new_block}


def _mark_cellids(blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """Mark every cellid column `index=True, cellid=True`: an integer array in a
    list item whose first (fastest-varying) axis is `ncelldim`. Every v1 field
    shaped by `ncelldim` is a cellid, so this needs no allowlist."""

    def _mark(field: Any) -> Any:
        if isinstance(field, v2.Array):
            if field.dtype == "integer" and field.shape[:1] == ["ncelldim"]:
                return field.model_copy(update={"index": True, "cellid": True})
            return field
        if isinstance(field, v2.Record):
            fields = {n: _mark(f) for n, f in field.fields.items()}
            return field.model_copy(update={"fields": fields})
        if isinstance(field, v2.Union):
            arms = {n: _mark(f) for n, f in field.arms.items()}
            return field.model_copy(update={"arms": arms})
        return field

    def _walk(field: Any) -> Any:
        if isinstance(field, v2.List):
            return field.model_copy(update={"item": _mark(field.item)})
        return field

    return {
        block_name: block.model_copy(
            update={"fields": {n: _walk(f) for n, f in block.fields.items()}}
        )
        for block_name, block in blocks.items()
    }


# Real relational facts the general `_resolve_relations`/`_mark_lonely_pk`
# passes can't infer, backfilled by an explicit, audited allowlist rather than
# derived. Each entry: component -> [(block name, list field name, {column:
# fk target}), ...]. Unlike `_NODE_REF_FIELDS`, block name and list field name
# aren't assumed equal (MF6's period/perioddata idiom applies to two of these).
# A column may be an integer scalar or an integer array (each element a key).
#
# - UZF's `ivertcon` is a self-referential fk (a UZF cell may point to another
#   UZF cell below it) -- a same-block relation `_resolve_relations`
#   explicitly never looks for.
# - SFR's `iconr` is the downstream reach receiving diverted water -- a
#   reference into `packagedata`'s reach numbers, not the record's leading
#   field, so `_mark_lonely_pk` doesn't catch it either.
# - SFR's `ic` lists the reaches connected to the current one. It's a signed
#   index (`support_negative_index`): the sign says which end of the current
#   reach, the magnitude which reach, so the fk applies to the magnitude.
# - `chf-cdb`/`chf-zdg`/`olf-zdg`'s `idcxs` reference the cross-section
#   defined by `chf-cxs`'s `packagedata.idcxs` -- a cross-component fk
#   `_resolve_relations` structurally can't reach (single-component scope).
#   OLF has no `*-cxs` component of its own (overland flow has no concept of
#   cross section upstream), but `olf-zdg`'s Fortran source shares CHF's
#   cross-section object, so the fk target is `chf-cxs`. `chf/olf-dfw`'s
#   `idcxs` is the same relation but is an `Array` field, not a list column
#   -- see `_ARRAY_FK_BACKFILL` below, not here.
_FK_BACKFILL: dict[str, list[tuple[str, str, dict[str, str]]]] = {
    "gwf-uzf": [("packagedata", "packagedata", {"ivertcon": "packagedata.ifno"})],
    "gwf-sfr": [
        ("diversions", "diversions", {"iconr": "packagedata.ifno"}),
        ("connectiondata", "connectiondata", {"ic": "packagedata.ifno"}),
    ],
    "chf-cdb": [("period", "stress_period_data", {"idcxs": "chf-cxs.packagedata.idcxs"})],
    "chf-zdg": [("period", "stress_period_data", {"idcxs": "chf-cxs.packagedata.idcxs"})],
    "olf-zdg": [("period", "stress_period_data", {"idcxs": "chf-cxs.packagedata.idcxs"})],
}


def _apply_fk_backfill(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """Set `fk` on this component's known-good backfill targets.

    See `_FK_BACKFILL` for why this is an explicit allowlist rather than a
    derived/mechanical pass.
    """
    for block_name, list_field_name, field_targets in _FK_BACKFILL.get(name, []):
        block = blocks.get(block_name)
        if block is None:
            continue
        list_field = block.fields.get(list_field_name)
        if not isinstance(list_field, v2.List) or not isinstance(list_field.item, v2.Record):
            continue
        item = list_field.item
        updates = {
            fname: f.model_copy(update={"fk": target})
            for fname, target in field_targets.items()
            if isinstance(f := item.fields.get(fname), v2.Integer | v2.Array) and f.fk is None
        }
        if not updates:
            continue
        new_item = item.model_copy(update={"fields": {**item.fields, **updates}})
        new_list = list_field.model_copy(update={"item": new_item})
        new_block = block.model_copy(update={"fields": {**block.fields, list_field_name: new_list}})
        blocks = {**blocks, block_name: new_block}
    return blocks


# `chf-dfw`/`olf-dfw`'s `idcxs` is a per-cell grid array (`griddata` block,
# dtype="integer", shape=["nodes"]), not a list column, so it can't go through
# `_apply_fk_backfill` above (which targets a List item's Record). It's the
# same cross-section relation as `_FK_BACKFILL`'s `*-zdg`/`chf-cdb` entries
# (including OLF targeting `chf-cxs` -- see the comment there).
# Each entry: component -> (block name, field name, fk target).
_ARRAY_FK_BACKFILL: dict[str, tuple[str, str, str]] = {
    "chf-dfw": ("griddata", "idcxs", "chf-cxs.packagedata.idcxs"),
    "olf-dfw": ("griddata", "idcxs", "chf-cxs.packagedata.idcxs"),
}


def _apply_array_fk_backfill(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """Set `fk` on this component's known-good Array backfill target.

    See `_ARRAY_FK_BACKFILL` for why this is a separate, explicit allowlist
    rather than folded into `_apply_fk_backfill`.
    """
    entry = _ARRAY_FK_BACKFILL.get(name)
    if entry is None:
        return blocks
    block_name, field_name, target = entry
    block = blocks.get(block_name)
    if block is None:
        return blocks
    field = block.fields.get(field_name)
    if not isinstance(field, v2.Array) or field.fk is not None:
        return blocks
    new_block = block.model_copy(
        update={"fields": {**block.fields, field_name: field.model_copy(update={"fk": target})}}
    )
    return {**blocks, block_name: new_block}


def _fill_period_list_shapes(
    blocks: dict[str, v2.Block],
    explicit_dims: dict[str, v2.InputDim],
) -> dict[str, v2.Block]:
    """
    For period blocks whose List field has no shape expression, infer the shape
    from the component's explicit dims.  Currently handles ``maxbound`` only:
    if the component defines a ``maxbound`` dimension but the period list omits
    it, add ``shape=["maxbound"]``.
    """
    if "maxbound" not in explicit_dims:
        return blocks
    return _remap_list_shapes(
        blocks,
        lambda bname, fname, field: ["maxbound"] if "period" in bname and not field.shape else None,
    )


def _item_array_dims(field: v2.List) -> set[str]:
    """Return dim names referenced in array shapes inside a list's item record."""
    dims: set[str] = set()
    item = field.item
    item_fields = item.fields if isinstance(item, v2.Record) else item.arms
    for f in item_fields.values():
        if isinstance(f, v2.Array):
            dims.update(v2.split_bound(elem)[1] for elem in f.shape)
    return dims


def _fill_named_list_shapes(
    blocks: dict[str, v2.Block],
    explicit_dims: dict[str, v2.InputDim],
) -> dict[str, v2.Block]:
    """
    For non-period named list blocks (e.g. packagedata) whose List field has no
    shape, infer it by elimination.

    Some v1 DFNs (LAK, SFR, GNC) write ``shape (maxbound)`` on their primary
    list recarray even though ``maxbound`` is not a declared dimension — the
    actual row count is a feature-specific dim (``nlakes``, ``nreaches``,
    ``numgnc``).  ``_sanitize_list_shapes`` strips those unresolvable shapes,
    leaving the list unsized.  Here we recover by process of elimination:

    1. Exclude ``auxiliary`` (array-length dim, not a row count).
    2. Exclude dims already used as the shape of another non-period list.
    3. Exclude dims that appear in array shapes *inside* the target list's item
       record — those are per-row column counts (e.g. ``numalphaj`` in GNC),
       not list row counts.
    4. If exactly one candidate remains, use it.
    """
    # Dims already claimed by existing shaped lists in non-period blocks.
    used: set[str] = {
        dim
        for bname, block in blocks.items()
        if "period" not in bname
        for field in block.fields.values()
        if isinstance(field, v2.List)
        for dim in (v2.split_bound(elem)[1] for elem in field.shape)
    }
    _SKIP = {"auxiliary"}

    def _fn(bname, fname, field):
        if "period" in bname or field.shape:
            return None
        intra_row = _item_array_dims(field)
        candidates = [
            n for n in explicit_dims if n not in _SKIP and n not in used and n not in intra_row
        ]
        if len(candidates) == 1:
            used.update(candidates)
            return list(candidates)
        return None

    return _remap_list_shapes(blocks, _fn)


def _col_to_list_map(blocks: dict[str, v2.Block]) -> dict[str, str]:
    """Map Integer column name → list field name for all list item records."""
    result: dict[str, str] = {}
    for block in blocks.values():
        for fname, field in block.fields.items():
            if isinstance(field, v2.List):
                item = field.item
                item_fields = item.fields if isinstance(item, v2.Record) else item.arms
                for col_name, col_field in item_fields.items():
                    if isinstance(col_field, v2.Integer):
                        result[col_name] = fname
    return result


def _translate_v1_shape_expr(
    shape_str: str,
    col_to_list: dict[str, str],
) -> "tuple[str, str] | None":
    """
    Translate a complex v1 shape expression to a ``(dim_name, v2_expr)`` pair.

    Bare ``Name`` nodes inside function-call arguments (e.g. the ``col`` in
    ``sum(col)``) are qualified to ``list.col`` form when ``col`` matches a
    known Integer column in a list item record.  All other nodes pass through
    unchanged, so any valid Python expression is handled generically.

    Returns ``None`` if the string is a bare identifier (handled by
    ``_parse_list_shape``) or cannot be parsed / translated.
    """
    s = shape_str.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()

    # Bare identifiers are already handled upstream.
    if _IDENT_RE.fullmatch(s):
        return None

    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError:
        return None

    class _Qualifier(ast.NodeTransformer):
        """Qualify bare column names inside function-call arguments."""

        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            new_args: list[ast.expr] = []
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in col_to_list:
                    new_args.append(
                        ast.Attribute(
                            value=ast.Name(id=col_to_list[arg.id], ctx=ast.Load()),
                            attr=arg.id,
                            ctx=ast.Load(),
                        )
                    )
                else:
                    new_args.append(arg)
            node.args = new_args
            return node

    new_tree = ast.fix_missing_locations(_Qualifier().visit(tree))
    try:
        v2_expr = ast.unparse(new_tree.body)
    except Exception:
        return None

    # Derive a concise dim name: for sum(list.col), use the column name;
    # for anything else sanitize the expression into a valid identifier.
    if m := re.fullmatch(r"sum\([A-Za-z_]\w+\.([A-Za-z_]\w+)\)", v2_expr):
        dim_name = m.group(1)
    else:
        dim_name = re.sub(r"[^A-Za-z0-9_]", "_", v2_expr).strip("_")

    return dim_name, v2_expr


def _infer_list_shape_dims(
    name: str,
    blocks: dict[str, v2.Block],
    v1_fields: OMD,
    scope: "Literal['component', 'model', 'simulation']",
    existing_dims: set[str],
) -> "tuple[dict[str, v2.Block], dict[str, v2.InputDim]]":
    """
    For shapeless List fields whose original v1 recarray had a complex shape
    expression, translate that expression to a derived dim and restore the shape.

    This handles cases like ``shape (sum(nlakeconn))`` in ``gwf-lak`` where the
    total row count is a function of values in another list block.
    """
    col_to_list = _col_to_list_map(blocks)

    # Map (block_name, field_name) -> original v1 shape string for all recarrays.
    v1_shapes: dict[tuple[str, str], str] = {}
    for f in v1_fields.values(multi=True):
        if (f.get("type") or "").startswith("recarray"):
            shape = _V1_SHAPE_FIXES.get((name, f["name"]), f.get("shape") or "").strip()
            if shape:
                v1_shapes[(f["block"], f["name"])] = shape

    derived: dict[str, v2.InputDim] = {}
    new_blocks = dict(blocks)

    for bname, block in blocks.items():
        new_fields = dict(block.fields)
        changed = False
        for fname, field in block.fields.items():
            if not isinstance(field, v2.List) or field.shape:
                continue
            shape_str = v1_shapes.get((bname, fname))
            if not shape_str:
                continue
            s = shape_str.strip()
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1].strip()
            op, s = _split_v1_bound(s)
            result = _translate_v1_shape_expr(s, col_to_list)
            if not result:
                continue
            dim_name, v2_expr = result
            # Avoid clobbering an existing dim with the same name.
            if dim_name in existing_dims or dim_name in derived:
                continue
            derived[dim_name] = v2.InputDim(value=v2_expr, scope=scope)
            new_fields[fname] = field.model_copy(update={"shape": [f"{op}{dim_name}"]})
            changed = True
        if changed:
            new_blocks[bname] = block.model_copy(update={"fields": new_fields})

    return new_blocks, derived


def _wrap_oc_period_records(
    blocks: dict[str, v2.Block],
) -> dict[str, v2.Block]:
    """
    OC packages define their period block as sibling optional Records (saverecord,
    printrecord) with no wrapping List, implying each appears at most once. Wrap
    them into a List[Union] so the repeatable nature is explicit in the schema.
    """
    result = {}
    for bname, block in blocks.items():
        if "period" not in bname:
            result[bname] = block
            continue
        fields = block.fields
        if not fields or any(isinstance(f, v2.List) for f in fields.values()):
            result[bname] = block
            continue
        if not all(isinstance(f, v2.Record) and f.optional for f in fields.values()):
            result[bname] = block
            continue
        union = v2.Union(
            name="output_record",
            arms=dict(fields),  # type: ignore[arg-type]
        )
        lst = v2.List(name="output", optional=True, item=union)
        result[bname] = block.model_copy(update={"fields": {"output": lst}})
    return result


# Records MF6 accepts any number of times in a block, each occurrence adding
# another value (IDM's `load_io_tag` appends every `FILEIN` line it reads).
# v1 has no attribute for this (its `repeating` flag marks unrelated fields), so
# these are an explicit, audited allowlist of record names, backed by
# mf6io's tsi.tex: "Any number of time-series files can be associated with a
# given package; a TS6 entry is required for each time-series file", and the
# same for TAS6. Other FILEIN records (OBS6, NCF6, ...) aren't documented as
# repeatable and stay single records.
_REPEATING_RECORDS = frozenset({"ts_filerecord", "tas_filerecord"})


def _wrap_repeating_records(blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Wrap each `_REPEATING_RECORDS` record in a List so its repetition is
    explicit. The record's leading keyword (e.g. `TS6`) makes the list tagged,
    so it can stay where it is among the block's other fields.
    """
    result = {}
    for bname, block in blocks.items():
        fields = {
            fname: (
                v2.List(
                    name=fname,
                    optional=f.optional,
                    item=f.model_copy(update={"optional": False}),
                )
                if fname in _REPEATING_RECORDS and isinstance(f, v2.Record)
                else f
            )
            for fname, f in block.fields.items()
        }
        result[bname] = block.model_copy(update={"fields": fields})
    return result


def _collapse_sto_keywords(
    blocks: dict[str, v2.Block],
) -> dict[str, v2.Block]:
    """
    STO packages define their period block with two mutually exclusive optional
    Keywords (steady-state, transient). Replace them with a single optional
    String field named 'storage' with constrained valid values.
    """
    _STO_KEYWORDS = frozenset({"steady-state", "transient"})
    result = {}
    for bname, block in blocks.items():
        if "period" not in bname:
            result[bname] = block
            continue
        fields = block.fields
        present = {
            name
            for name, f in fields.items()
            if isinstance(f, v2.Keyword) and f.optional and name in _STO_KEYWORDS
        }
        if present != _STO_KEYWORDS:
            result[bname] = block
            continue
        non_sto = {name: f for name, f in fields.items() if name not in _STO_KEYWORDS}
        storage = v2.String(
            name="storage",
            longname="storage state",
            description=fields["steady-state"].description,
            optional=True,
            # The v1 fields this replaces are plain Keywords, which are inherently
            # untagged: PERIOD writes a bare STEADY-STATE/TRANSIENT line, no STORAGE
            # prefix. Synthesized here, so there's no .dfn `tagged` line to inherit from.
            tagged=False,
            valid=["steady-state", "transient"],
        )
        result[bname] = block.model_copy(update={"fields": {**non_sto, "storage": storage}})
    return result


def _patch_oc_rtype(
    name: str,
    blocks: dict[str, v2.Block],
) -> dict[str, v2.Block]:
    """Set valid values on rtype string fields in OC packages."""
    if not name.endswith("-oc"):
        return blocks
    prefix = name.split("-")[0]
    valid = _OC_RTYPE_VALID.get(prefix)
    if not valid:
        return blocks

    def _patch(fields: dict) -> tuple[dict, bool]:
        new_fields = {}
        changed = False
        for fname, field in fields.items():
            if isinstance(field, v2.String) and fname == "rtype":
                field = field.model_copy(update={"valid": valid})
                changed = True
            elif isinstance(field, v2.Record):
                patched, c = _patch(field.fields)
                if c:
                    field = field.model_copy(update={"fields": patched})
                    changed = True
            elif isinstance(field, v2.Union):
                patched, c = _patch(field.arms)
                if c:
                    field = field.model_copy(update={"arms": patched})
                    changed = True
            elif isinstance(field, v2.List):
                item = field.item
                if isinstance(item, v2.Record):
                    patched, c = _patch(item.fields)
                    if c:
                        field = field.model_copy(
                            update={"item": item.model_copy(update={"fields": patched})}
                        )
                        changed = True
                elif isinstance(item, v2.Union):
                    patched, c = _patch(item.arms)
                    if c:
                        field = field.model_copy(
                            update={"item": item.model_copy(update={"arms": patched})}
                        )
                        changed = True
            new_fields[fname] = field
        return new_fields, changed

    result = {}
    for bname, block in blocks.items():
        new_fields, changed = _patch(block.fields)
        result[bname] = block.model_copy(update={"fields": new_fields}) if changed else block
    return result


# LAK's period block pairs a single `number` field with a `laksetting` union
# whose arms are either lake settings or outlet settings; `number` means a
# lake number for the former, an outlet number for the latter. See
# docs/md/sfr-lak-structure.md for the full rationale.
_LAK_LAKE_SETTING_ARMS = frozenset(
    {
        "status",
        "stage",
        "rainfall",
        "evaporation",
        "runoff",
        "inflow",
        "withdrawal",
        "auxiliaryrecord",
    }
)
_LAK_OUTLET_SETTING_ARMS = frozenset({"rate", "invert", "width", "slope", "rough"})

# outlets.lakein/lakeout are unambiguous lake references (unlike period
# `number`), just under names that don't match packagedata's `ifno` — a
# naming gap rather than a genuine ambiguity, so a static `fk` is correct.
_LAK_OUTLET_LAKE_REFS = frozenset({"lakein", "lakeout"})


def _fix_lak_relations(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Patch LAK's pk/fk relations that the general `_resolve_relations` name
    match can't reach on its own — see docs/md/sfr-lak-structure.md.

    - Splits the ambiguous period `number` field into `lakeno` / `outletno`
      fields nested inside the corresponding `laksetting` union arms, each
      carrying a correct, non-conditional `fk` (a single `fk` on the shared
      `number` field can't be correct for both arm categories at once, since
      the target block depends on which arm is present).
    - Marks `outlets.outletno` as `pk` (the new `outletno` fk needs one).
    - Marks `outlets.lakein`/`outlets.lakeout` as `fk: packagedata.ifno` —
      unambiguous, but named differently from `ifno` so the general
      name-matching pass never finds them.
    """
    if name != "gwf-lak":
        return blocks

    period = blocks.get("period")
    outlets = blocks.get("outlets")
    if period is None or outlets is None:
        return blocks

    perioddata = period.fields.get("perioddata")
    if not isinstance(perioddata, v2.List) or not isinstance(perioddata.item, v2.Record):
        return blocks
    item = perioddata.item
    number_field = item.fields.get("number")
    setting_field = item.fields.get("laksetting")
    if not isinstance(number_field, v2.Integer) or not isinstance(setting_field, v2.Union):
        return blocks

    outlets_list = outlets.fields.get("outlets")
    if not isinstance(outlets_list, v2.List) or not isinstance(outlets_list.item, v2.Record):
        return blocks
    outletno_field = outlets_list.item.fields.get("outletno")
    if not isinstance(outletno_field, v2.Integer):
        return blocks

    def _retarget(
        arm_name: str, arm: "v2.Scalar | v2.Array | v2.Record", key: str, fk: str
    ) -> v2.Record:
        renamed = number_field.model_copy(update={"name": key, "fk": fk})
        if isinstance(arm, v2.Record):
            return arm.model_copy(update={"fields": {key: renamed, **arm.fields}})
        # Most arms are a bare scalar (e.g. `stage`), not a Record — wrap it
        # alongside the renamed id field so the id can carry its own `fk`.
        return v2.Record(
            name=arm_name,
            fields={key: renamed, arm.name: arm},
        )

    new_arms: dict[str, v2.Scalar | v2.Array | v2.Record] = {}
    for arm_name, arm in setting_field.arms.items():
        if arm_name in _LAK_LAKE_SETTING_ARMS:
            new_arms[arm_name] = _retarget(arm_name, arm, "lakeno", "packagedata.ifno")
        elif arm_name in _LAK_OUTLET_SETTING_ARMS:
            new_arms[arm_name] = _retarget(arm_name, arm, "outletno", "outlets.outletno")
        else:
            new_arms[arm_name] = arm

    new_setting = setting_field.model_copy(update={"arms": new_arms})
    new_item = item.model_copy(
        update={
            "fields": {fn: f for fn, f in item.fields.items() if fn != "number"}
            | {"laksetting": new_setting}
        }
    )
    new_perioddata = perioddata.model_copy(update={"item": new_item})
    new_period = period.model_copy(
        update={"fields": {**period.fields, "perioddata": new_perioddata}}
    )

    outlets_item_fields = dict(outlets_list.item.fields)
    changed = False
    if not outletno_field.pk:
        outlets_item_fields["outletno"] = outletno_field.model_copy(update={"pk": True})
        changed = True
    for fname in _LAK_OUTLET_LAKE_REFS:
        f = outlets_item_fields.get(fname)
        if isinstance(f, v2.Integer) and f.fk is None:
            outlets_item_fields[fname] = f.model_copy(update={"fk": "packagedata.ifno"})
            changed = True

    if changed:
        new_outlets_item = outlets_list.item.model_copy(update={"fields": outlets_item_fields})
        new_outlets_list = outlets_list.model_copy(update={"item": new_outlets_item})
        new_outlets = outlets.model_copy(update={"fields": {"outlets": new_outlets_list}})
    else:
        new_outlets = outlets

    return {**blocks, "period": new_period, "outlets": new_outlets}


def _fix_mvr_relations(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Patch MVR's pk/fk relations that the general passes can't reach on their
    own.

    - Marks `packages.pname` as `pk`: it's the unique name of a package
      participating in the mover, but nothing else in the component repeats
      the field name `pname` (the period block's `pname1`/`pname2` are
      renamed), so neither `_resolve_relations` nor `_mark_lonely_pk` finds
      it, and `pname` isn't `packages`' leading column anyway (`mname` is).
    - Marks `period.perioddata`'s `pname1`/`pname2` as
      `fk: "packages.pname"`, since each identifies the provider/receiver
      package by name.

    Does *not* annotate `id1`/`id2`. Each identifies a feature within the
    package named by the sibling `pname1`/`pname2` field, but which block
    that resolves to depends on that package's *type*: `packagedata`'s pk
    for SFR/MAW/UZF, `outlets.outletno` for LAK, and a positional row index
    (no `pk`-flagged column at all) for ordinary boundary packages like
    WEL/DRN/RIV. A single static `fk` value can't express a target that's
    conditional on resolved data like that.
    """
    if name != "gwf-mvr":
        return blocks

    packages = blocks.get("packages")
    period = blocks.get("period")
    if packages is None or period is None:
        return blocks

    packages_list = packages.fields.get("packages")
    if not isinstance(packages_list, v2.List) or not isinstance(packages_list.item, v2.Record):
        return blocks
    pname_field = packages_list.item.fields.get("pname")
    if not isinstance(pname_field, v2.String):
        return blocks

    perioddata = period.fields.get("perioddata")
    if not isinstance(perioddata, v2.List) or not isinstance(perioddata.item, v2.Record):
        return blocks
    item_fields = perioddata.item.fields
    if not all(isinstance(item_fields.get(n), v2.String) for n in ("pname1", "pname2")):
        return blocks

    new_packages = packages
    if not pname_field.pk:
        new_packages_item = packages_list.item.model_copy(
            update={
                "fields": {
                    **packages_list.item.fields,
                    "pname": pname_field.model_copy(update={"pk": True}),
                }
            }
        )
        new_packages_list = packages_list.model_copy(update={"item": new_packages_item})
        new_packages = packages.model_copy(update={"fields": {"packages": new_packages_list}})

    new_item_fields = dict(item_fields)
    for pname_key in ("pname1", "pname2"):
        pname_f = item_fields[pname_key]
        if not isinstance(pname_f, v2.String):
            continue
        if pname_f.fk is None:
            new_item_fields[pname_key] = pname_f.model_copy(update={"fk": "packages.pname"})

    new_item = perioddata.item.model_copy(update={"fields": new_item_fields})
    new_perioddata = perioddata.model_copy(update={"item": new_item})
    new_period = period.model_copy(
        update={"fields": {**period.fields, "perioddata": new_perioddata}}
    )

    return {**blocks, "packages": new_packages, "period": new_period}


def _fix_ssm_sources_write_if_empty(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Mark SSM's SOURCES block write_if_empty: MF6 requires the block's header
    to appear in the input file even with zero source terms (IDM
    required=.true. in src/Idm/gwt-ssmidm.f90 and src/Idm/gwe-ssmidm.f90,
    matching optional=false on the field in the DFN) -- it errors on read if
    the block is absent entirely, unlike a block gated by a real dimension
    count (e.g. LAK TABLES/OUTLETS), which must instead be omitted when
    empty. There's no DFN tag for this distinction yet; once modflow6 adds a
    `write_if_empty true` line to the SOURCES field in gwt-ssm.dfn/
    gwe-ssm.dfn, the general per-field pass in to_v2_0_0_dev2 picks it up
    directly and this stopgap can be removed.
    """
    if name not in ("gwt-ssm", "gwe-ssm"):
        return blocks
    sources = blocks.get("sources")
    if sources is None or sources.write_if_empty:
        return blocks
    return {**blocks, "sources": sources.model_copy(update={"write_if_empty": True})}


# Blocks MF6 reads with `GetBlock(..., blockRequired=.false.)` though their v1
# fields aren't all marked optional, so the derived `Block.optional` comes out
# false. SFR CROSSSECTIONS/DIVERSIONS/INITIALSTAGES (gwf-sfr.f90) and LAK
# OUTLETS (gwf-lak.f90) each hold one list; IMS NONLINEAR (NumericalSolution.f90)
# and LINEAR (ImsLinearSettings.f90) hold settings that all have defaults.
# SFR DIVERSIONS and LAK OUTLETS are really conditional: present iff
# `sum(packagedata.ndv) > 0` and `noutlets > 0` respectively. There's no way to
# say that yet; optional is enough for a writer that omits empty blocks.
_OPTIONAL_BLOCKS: dict[str, tuple[str, ...]] = {
    "gwf-sfr": ("crosssections", "diversions", "initialstages"),
    "gwf-lak": ("outlets",),
    "sln-ims": ("nonlinear", "linear"),
}


def _fix_optional_blocks(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Mark every field in each of `_OPTIONAL_BLOCKS` optional, making the block
    optional. Without this, a writer that emits required blocks even when empty
    writes e.g. an empty SFR DIVERSIONS block, which MF6 rejects. Once modflow6
    marks these fields `optional true`, this stopgap can be removed.
    """
    block_names = _OPTIONAL_BLOCKS.get(name)
    if not block_names:
        return blocks
    missing = [b for b in block_names if b not in blocks]
    if missing:
        raise ValueError(f"{name}: expected optional block(s) not found: {missing!r}")
    new_blocks = dict(blocks)
    for b in block_names:
        block = blocks[b]
        fields = {
            k: f if f.optional else f.model_copy(update={"optional": True})
            for k, f in block.fields.items()
        }
        new_blocks[b] = block.model_copy(update={"fields": fields})
    return new_blocks


# List dims that MF6 treats as an upper bound (it reads up to that many rows and
# uses the count read), though v1 doesn't mark them `<`. Each is confirmed in the
# MF6 source: IDM's period list loader sets `nbound` from the rows read (every
# `maxbound`), HFB sets `nhfb` likewise, CSUB loops over the `nbound` read, and
# ATS reads PERIODDATA until the block ends. Unmarked dims are exact, whatever
# their name: MVR errors unless there are exactly `maxpackages` PACKAGES rows.
_UPPER_BOUND_LIST_DIMS = frozenset({"maxbound", "maxhfb", "maxsig0", "maxats"})

# Lists whose v1 recarray has no shape, though a declared dim counts its rows.
_MISSING_LIST_SHAPES: dict[tuple[str, str], str] = {
    ("sim-tdis", "perioddata"): "nper",
    ("utl-ats", "perioddata"): "maxats",
}


def _fix_list_shapes(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Fill in list shapes v1 omits and mark upper bounds v1 leaves unmarked.

    Stopgap until the modflow6 DFNs carry ``shape (nper)``, ``shape (<maxbound)``
    and so on; then the per-field shape parsing picks them up directly.
    """

    def _fn(bname, fname, field):
        shape = field.shape
        if not shape and (dim := _MISSING_LIST_SHAPES.get((name, fname))):
            shape = [dim]
        shape = [f"<={elem}" if elem in _UPPER_BOUND_LIST_DIMS else elem for elem in shape]
        return shape if shape != field.shape else None

    return _remap_list_shapes(blocks, _fn)


def _fix_ts_sfac(name: str, blocks: dict[str, v2.Block]) -> dict[str, v2.Block]:
    """
    Make ``utl-ts``'s SFAC scale factor a scalar.

    v1 shares one ``sfacval`` between the SFACS record (one factor per time
    series) and the SFAC record (a single factor for all of them), so both map
    to the SFACS array. MF6 reads one value after SFAC.
    """
    if name != "utl-ts" or "attributes" not in blocks:
        return blocks
    block = blocks["attributes"]
    record = block.fields.get("sfacrecord_single")
    if not isinstance(record, v2.Record) or not isinstance(
        sfacval := record.fields.get("sfacval"), v2.Array
    ):
        return blocks
    shared = (set(v2.Double.model_fields) & sfacval.model_fields_set) - {"type"}
    scalar = v2.Double(**{k: getattr(sfacval, k) for k in shared})
    record = record.model_copy(update={"fields": {**record.fields, "sfacval": scalar}})
    fields = {**block.fields, "sfacrecord_single": record}
    return {**blocks, "attributes": block.model_copy(update={"fields": fields})}


def _wrap_grid_aux(blocks: dict[str, v2.Block], fields: OMD) -> dict[str, v2.Block]:
    """
    Make an array-based package's period ``aux`` field a list of
    (auxiliary name, array) records.

    The READASARRAYS (``gwf-rcha``, ``gwf-evta``) and READARRAYGRID
    (``gwf-*g``) packages' v1 period ``aux`` is a single readarray tagged
    ``AUX``, but the input file has zero or more grid arrays, each introduced
    by one of the ``auxiliary`` names (MF6 treats any period tag matching one
    as ``AUX``). The leading ``auxname`` is a dynamic keyword (an untagged
    String with an ``fk`` to ``options.auxiliary``), which makes the list
    tagged, so it mixes freely with the block's other arrays. Each auxiliary
    variable is set at most once per period, so the list is bounded by the
    ``auxiliary`` count, and is always optional (v1's ``gwf-evta`` says
    otherwise). The outer name stays ``aux`` so memory variables sourced from
    it still resolve.

    Matched by ``mf6internal auxvar`` on a period readarray, in a component
    with ``options.auxiliary``; list-based packages' aux columns are record
    subfields, never top-level period fields.
    """
    options = blocks.get("options")
    period = blocks.get("period")
    if options is None or period is None or "auxiliary" not in options.fields:
        return blocks
    v1_names = {
        f["name"]
        for f in fields.values(multi=True)
        if f.get("block") == "period"
        and f.get("reader") == "readarray"
        and f.get("mf6internal") == "auxvar"
    }
    updates: dict[str, v2.InputField] = {}
    for fname, field in period.fields.items():
        if fname not in v1_names or not isinstance(field, v2.Array):
            continue
        auxname = v2.String(
            name="auxname",
            longname="auxiliary variable name",
            description="name of the auxiliary variable the following array sets; must be "
            "one of the auxiliary variables.",
            tagged=False,
            fk="options.auxiliary",
        )
        array = field.model_copy(update={"tagged": False, "optional": False, "description": None})
        updates[fname] = v2.List(
            name=fname,
            longname=field.longname,
            description=field.description,
            optional=True,
            developmode=field.developmode,
            removed=field.removed,
            deprecated=field.deprecated,
            shape=["<=auxiliary"],
            item=v2.Record(name=fname, fields={"auxname": auxname, fname: array}),
        )
    if not updates:
        return blocks
    new_fields = {n: updates.get(n, f) for n, f in period.fields.items()}
    return {**blocks, "period": period.model_copy(update={"fields": new_fields})}


def _parse_valid(valid: Any, coerce=None) -> list | None:
    """Parse a v1 ``valid`` attribute to a list, optionally coercing each element."""
    parts = valid.split() if isinstance(valid, str) else (list(valid) if valid else [])
    if not parts:
        return None
    return [coerce(x) for x in parts] if coerce else parts


def _is_unsized_readarray(f: Mapping[str, object]) -> bool:
    """Return True for a U2DREL (`reader readarray`) field whose v1 shape is `(unknown)`.

    Unlike genuinely self-sizing fields (`reader urword` trailing tokens), a readarray
    control record is never self-sizing: the caller must supply its length. Every other
    readarray field in the v1 corpus declares one; `utl-tas.tas_array` is the sole
    exception, and its length is one layer's worth of cells (`ncpl`), since time-array
    series only feed 2-D array input in structured models.
    """
    return f.get("reader") == "readarray" and str(f.get("shape") or "").strip() in (
        "(unknown)",
        "unknown",
    )


def _has_grid_dependent_shapes(fields: OMD) -> bool:
    """Return True if any field uses a semicolon grid-type-dependent shape, references
    ncelldim, or is an unsized readarray (implicitly per-cell)."""

    def _field_has_grid_shape(f: dict) -> bool:
        shape = str(f.get("shape") or "")
        if ";" in shape or "ncelldim" in shape:
            return True
        return _is_unsized_readarray(f)

    for field in fields.values():
        if _field_has_grid_shape(field):
            return True
    return False


def infer_parent(name: str, fields: OMD) -> str | None:
    """Infer a component's parent using naming conventions."""
    if name == "sim-nam":
        return None
    if name.endswith("-nam"):
        return "sim-nam"
    if name.startswith(("exg-", "sln-")):
        return "sim-nam"
    if name.startswith("utl-"):
        # Grid-dependent shapes (semicolon notation) mean the utility must be
        # model-attached, not simulation-level.
        if _has_grid_dependent_shapes(fields):
            return "package"
        return "sim-nam"
    if "-" in name:
        mdl = name.split("-")[0]
        return f"{mdl}-nam"
    return None


def to_v2_0_0_dev2(name: str, fields: OMD, meta: list[str]) -> v2.Component:
    """Map a component definition from the raw v1 schema to 2.0.0.dev2."""

    from modflow_devtools.dfn.migrate_to_v2_0_0_dev0 import (
        is_advanced_package,
        is_multi_package,
        is_stress_package,
    )

    parent = infer_parent(name, fields)

    def _map_field(f: v1.Field) -> v2.InputField:
        _name: str = f["name"]
        _type: str | None = f.get("type")
        shape_str: str | None = _V1_SHAPE_FIXES.get((name, _name), f.get("shape") or None)
        description: str | None = f.get("description") or None
        longname: str | None = f.get("longname") or None
        optional: bool = try_parse_bool(f.get("optional"), False)
        # `dev_`-prefixed names are v1's de facto (and only-ever-used) convention for
        # marking a field internal/undocumented; the `developmode` attribute itself is
        # declared in zero DFN files in the wild, so fold the name convention into it
        # here rather than leaving `render()` to special-case a naming pattern.
        developmode: bool = try_parse_bool(f.get("developmode"), False) or _name.startswith("dev_")
        netcdf: bool = try_parse_bool(f.get("netcdf"), False)
        tagged: bool = try_parse_bool(f.get("tagged"), True)
        preserve_case: bool = try_parse_bool(f.get("preserve_case"), False)
        time_series: bool = try_parse_bool(f.get("time_series"), False)
        layered: bool = try_parse_bool(f.get("layered"), False)
        # Pure serialization fact (1-based/0-based conversion), orthogonal to pk/fk
        # relational identity. Direct copy from v1: valid on Integer/Array(dtype=
        # "integer") only, never on String. v1's `support_negative_index` (only
        # SFR's `ic`) means the sign carries meaning and the magnitude is the index.
        numeric_index: v2.Index = try_parse_bool(f.get("numeric_index"), False)
        if numeric_index and try_parse_bool(f.get("support_negative_index"), False):
            numeric_index = "signed"
        removed: str | None = f.get("removed") or None
        deprecated: str | None = f.get("deprecated") or None
        valid = f.get("valid")
        _default_raw = f.get("default", f.get("default_value", None))
        if _type == "keyword" and isinstance(_default_raw, str):
            default = try_parse_bool(_default_raw, False)
        else:
            default = (
                try_literal_eval(_default_raw)  # type: ignore
                if _type != "string" and isinstance(_default_raw, str)
                else _default_raw
            )

        def _parse_shape_elem(elem: str) -> str | None:
            if ";" in elem:
                return "ncpl"
            if elem in ("any1d", "unknown"):
                return None
            if m := _COL_FK_RE.fullmatch(elem):
                col_name = m.group(1)
                block_name = next(
                    (
                        fi["block"]
                        for fi in fields.values(multi=True)
                        if fi["name"] == col_name
                        and fi["type"] == "integer"
                        and try_parse_bool(fi.get("in_record", False))
                    ),
                    None,
                )
                return f"{block_name}.{elem}" if block_name else None
            # A dim that isn't itself a field (e.g. `naux`) is named for the
            # string array it counts (`auxiliary`, shape `(naux)`).
            if any(fi["name"] == elem for fi in fields.values(multi=True)):
                return elem
            provider = next(
                (
                    fi["name"]
                    for fi in fields.values(multi=True)
                    if fi["type"] == "string"
                    and (fi.get("shape") or "").strip() in (f"({elem})", elem)
                ),
                None,
            )
            return provider if provider else elem

        def _parse_shape(s: str) -> list[str]:
            result = []
            s_clean = s.strip()
            if s_clean.startswith("(") and s_clean.endswith(")"):
                s_clean = s_clean[1:-1]
            for elem in (x.strip() for x in s_clean.split(",") if x.strip()):
                op, elem = _split_v1_bound(elem)
                if (parsed := _parse_shape_elem(elem)) is not None:
                    result.append(f"{op}{parsed}")
            return result

        def _to_scalar() -> v2.Scalar:
            assert _type is not None
            if _type == "keyword":
                return v2.Keyword(
                    name=_name,
                    longname=longname,
                    description=description,
                    optional=optional,
                    default=default,
                    developmode=developmode,
                    netcdf=netcdf,
                    removed=removed,
                    deprecated=deprecated,
                    aliases=(f.get("other_names") or "").lower().split(),
                )
            if _type == "string":
                return v2.String(
                    name=_name,
                    longname=longname,
                    description=description,
                    optional=optional,
                    default=default,
                    developmode=developmode,
                    netcdf=netcdf,
                    removed=removed,
                    deprecated=deprecated,
                    tagged=tagged,
                    valid=_parse_valid(valid),
                    case_sensitive=preserve_case,
                    time_series=time_series,
                )
            if _type == "integer":
                return v2.Integer(
                    name=_name,
                    longname=longname,
                    description=description,
                    optional=optional,
                    default=default,
                    developmode=developmode,
                    netcdf=netcdf,
                    removed=removed,
                    deprecated=deprecated,
                    tagged=tagged,
                    valid=_parse_valid(valid, int),
                    time_series=time_series,
                    index=numeric_index,
                )
            if _type in ("double", "double precision"):
                return v2.Double(
                    name=_name,
                    longname=longname,
                    description=description,
                    optional=optional,
                    default=default,
                    developmode=developmode,
                    netcdf=netcdf,
                    removed=removed,
                    deprecated=deprecated,
                    tagged=tagged,
                    time_series=time_series,
                )
            raise TypeError(f"Unsupported scalar type: {_type!r}")

        def _row_field() -> v2.Record | v2.Union:
            item_names = (_type or "").split()[1:]
            if not item_names:
                raise ValueError(f"Missing list item definition: {_type!r}")

            item_types = [
                fi["type"]
                for fi in fields.values(multi=True)
                if fi["name"] in item_names
                and try_parse_bool(fi.get("in_record", False))
                and fi.get("block") == f.get("block")
            ]

            if (
                len(item_names) == 1
                and item_types
                and (
                    (item_types[0] or "").startswith("record")
                    or (item_types[0] or "").startswith("keystring")
                )
            ):
                mapped = _map_field(next(iter(fields.getlist(item_names[0]))))
                if isinstance(mapped, (v2.Record, v2.Union)):
                    return mapped
                raise TypeError(
                    f"Expected Record or Union for list item, got {type(mapped).__name__}"
                )

            if all(t in v1.SCALAR_TYPES for t in item_types):
                rec_fields = _file_record_fields() or _subfield_map()
                return v2.Record(
                    name=_name,
                    description=(
                        (description or "").replace("is the list of", "is the record of") or None
                    ),
                    fields=rec_fields,
                )

            children = {
                fi["name"]: _map_field(fi)
                for fi in fields.values(multi=True)
                if fi["name"] in item_names
                and try_parse_bool(fi.get("in_record", False))
                and fi.get("block") == f.get("block")
            }
            first = next(iter(children.values()))
            if len(children) == 1 and isinstance(first, v2.Union):
                return first
            return v2.Record(
                name=_name,
                description=(
                    (description or "").replace("is the list of", "is the record of") or None
                ),
                fields=children,  # type: ignore[arg-type]
            )

        def _subfield_map() -> dict:
            result = {}
            for rname in (_type or "").split()[1:]:
                for fi in fields.values(multi=True):
                    if (
                        fi["name"] == rname
                        and try_parse_bool(fi.get("in_record", False))
                        and fi.get("block") == f.get("block")
                    ):
                        result[rname] = _map_field(fi)
                        break
            return result

        def _file_record_fields() -> dict | None:
            """Map this record's subfields, folding a `FILEIN|FILEOUT <path>` pair
            into one File field, or return None if it isn't a file record."""
            subnames = (_type or "").split()[1:]

            # Detect filerecord from type string sub-field names
            file_mode: str | None = None
            for sname in subnames:
                if sname in ("filein", "fileout"):
                    m = next(
                        (
                            fi
                            for fi in fields.values(multi=True)
                            if fi["name"] == sname
                            and try_parse_bool(fi.get("in_record", False))
                            and fi.get("block") == f.get("block")
                        ),
                        None,
                    )
                    if m and (m.get("type") or "").strip() == "keyword":
                        file_mode = sname
                        break

            if not file_mode:
                return None

            # Filerecord pattern: <tag...> <filein|fileout> <path_string> [<flag>...].
            # The mode keyword and path string together denote one File value;
            # tag keyword(s) before it and flag keyword(s) after it are ordinary
            # sibling fields, mapped like any other tagged Record subfield -- no
            # special-casing needed for render() to reconstruct the v1 text
            # exactly (e.g. utl-obs's untagged `output` record already worked
            # this way: `FILEOUT <path> [BINARY]`).
            mode_idx = subnames.index(file_mode)

            # The path is the first untagged string after the mode keyword; an
            # untagged string before it is a variable tag (e.g. FMI's flowtype).
            path_field_name: str | None = None
            for sname in subnames[mode_idx + 1 :]:
                m_s = next(
                    (
                        fi
                        for fi in fields.values(multi=True)
                        if fi["name"] == sname
                        and try_parse_bool(fi.get("in_record", False))
                        and fi.get("block") == f.get("block")
                    ),
                    None,
                )
                if (
                    m_s
                    and (m_s.get("type") or "").strip() == "string"
                    and not try_parse_bool(m_s.get("tagged"), True)
                ):
                    path_field_name = sname
                    break

            def _lookup(rname: str) -> dict | None:
                return next(
                    (
                        fi
                        for fi in fields.values(multi=True)
                        if fi["name"] == rname
                        and try_parse_bool(fi.get("in_record", False))
                        and fi.get("block") == f.get("block")
                        and not (fi.get("type") or "").startswith("record")
                    ),
                    None,
                )

            rec_fields: dict[str, v2.InputField] = {}
            for i, sname in enumerate(subnames):
                if i == mode_idx:
                    continue  # folded into the File field at the path's position
                if sname == path_field_name:
                    m = _lookup(sname)
                    if m is None:
                        continue
                    rec_fields[sname] = v2.File(
                        name=sname,
                        longname=m.get("longname") or None,
                        description=m.get("description") or None,
                        optional=try_parse_bool(m.get("optional"), False),
                        developmode=try_parse_bool(m.get("developmode"), False)
                        or (m.get("name") or "").startswith("dev_"),
                        netcdf=try_parse_bool(m.get("netcdf"), False),
                        removed=m.get("removed") or None,
                        deprecated=m.get("deprecated") or None,
                        tagged=False,
                        direction="in" if file_mode == "filein" else "out",
                    )
                    continue
                m = _lookup(sname)
                if m is None:
                    continue
                rec_fields[sname] = _map_field(m)  # type: ignore
            return rec_fields

        if _type is None:
            raise ValueError(f"Missing type for v1 field: {_name!r}")

        if _type.startswith("recarray"):
            item = _row_field()
            list_shape = _parse_list_shape(shape_str) if shape_str else []
            return v2.List(
                name=_name,
                longname=longname,
                description=description,
                optional=optional,
                default=default,
                developmode=developmode,
                netcdf=netcdf,
                removed=removed,
                deprecated=deprecated,
                item=item,
                shape=list_shape,
            )

        if _type.startswith("keystring"):
            arms = _subfield_map()
            return v2.Union(
                name=_name,
                longname=longname,
                description=description,
                optional=optional,
                default=default,
                developmode=developmode,
                removed=removed,
                deprecated=deprecated,
                arms=arms,  # type: ignore[arg-type]
            )

        if _type.startswith("record"):
            rec_fields = _file_record_fields() or _subfield_map()

            return v2.Record(
                name=_name,
                longname=longname,
                description=description,
                optional=optional,
                default=default,
                developmode=developmode,
                removed=removed,
                deprecated=deprecated,
                fields=rec_fields,  # type: ignore[arg-type]
            )

        if shape_str is not None:
            dtype_map: dict[str, Literal["keyword", "integer", "double", "string"]] = {
                "double precision": "double",
                "double": "double",
                "integer": "integer",
                "string": "string",
                "keyword": "keyword",
            }
            dtype = dtype_map.get(_type)
            if dtype is not None:
                if dtype == "string":
                    if shape_str.strip() != "lenbigline":
                        return v2.Array(
                            name=_name,
                            longname=longname,
                            description=description,
                            optional=optional,
                            default=default,
                            developmode=developmode,
                            netcdf=netcdf,
                            removed=removed,
                            deprecated=deprecated,
                            tagged=tagged,
                            time_series=time_series,
                            layered=layered,
                            dtype="string",
                            # A string array is self-sizing unless another field
                            # counts it: `auxiliary`'s `(naux)` names itself.
                            shape=[e for e in _parse_shape(shape_str) if e != _name],
                        )
                    # lenbigline is a character-length constraint (v1 overloading),
                    # not an array dimension; fall through to _to_scalar() below.
                else:
                    parsed_shape = _parse_shape(shape_str)
                    if _is_unsized_readarray(f):
                        parsed_shape = ["ncpl"]
                    return v2.Array(
                        name=_name,
                        longname=longname,
                        description=description,
                        optional=optional,
                        default=default,
                        developmode=developmode,
                        netcdf=netcdf,
                        removed=removed,
                        deprecated=deprecated,
                        tagged=tagged,
                        time_series=time_series,
                        layered=layered,
                        dtype=dtype,
                        shape=parsed_shape,
                        index=numeric_index if dtype == "integer" else False,
                    )

        return _to_scalar()

    blocks: dict[str, v2.Block] = {}

    for field in fields.values(multi=True):
        block = blocks.setdefault(field["block"], v2.Block(name=field["block"], fields={}))
        if try_parse_bool(field.get("write_if_empty", False)):
            block.write_if_empty = True
        if try_parse_bool(field.get("block_variable", False)):
            # Field's token(s) attach to the BEGIN <BLOCK> line itself (e.g. `BEGIN
            # PERIOD <iper>`) rather than appearing as a body row. Must be checked
            # before the in_record skip below: block-attached scalars are marked
            # in_record=true in v1 even though they aren't a record subfield.
            #
            # No v1 tag for `fill_forward`, so it's hardcoded by block name:
            # `period` is the only repeating-block header in the v1 corpus that
            # fill-forwards (confirmed against MF6 source; see
            # repeating-block-fill-forward-plan.md).
            block.header = v2.BlockHeader(
                field=_map_field(field), fill_forward=field["block"] == "period"
            )
            continue
        if try_parse_bool(field.get("in_record", False)):
            continue  # record subfields are handled recursively
        block.fields[field["name"]] = _map_field(field)

    blocks, array_dims = _resolve_dimensions(blocks)
    blocks = _resolve_relations(blocks)
    raw_dim_names = _raw_dim_names(blocks)
    blocks = _normalize_n_prefix_shapes(blocks, raw_dim_names)
    explicit_dims = _build_explicit_dims(name, parent, blocks)
    known_dims = set(explicit_dims) | set(array_dims)
    blocks = _sanitize_list_shapes(blocks, known_dims)
    blocks = _fill_period_list_shapes(blocks, explicit_dims)
    blocks = _fill_named_list_shapes(blocks, explicit_dims)
    blocks, derived_dims = _infer_list_shape_dims(
        name, blocks, fields, _dims_scope(name, parent), known_dims
    )
    blocks = _fix_list_shapes(name, blocks)
    blocks = _fix_ts_sfac(name, blocks)
    blocks = _wrap_oc_period_records(blocks)
    blocks = _wrap_repeating_records(blocks)
    blocks = _collapse_sto_keywords(blocks)
    blocks = _patch_oc_rtype(name, blocks)
    blocks = _fix_lak_relations(name, blocks)
    blocks = _fix_mvr_relations(name, blocks)
    blocks = _fix_ssm_sources_write_if_empty(name, blocks)
    blocks = _fix_optional_blocks(name, blocks)
    blocks = _wrap_grid_aux(blocks, fields)
    # Must run after `_fix_lak_relations`: LAK's period `number` field looks
    # exactly like a lonely pk (leading required Integer, no fk) before it's
    # split into per-arm `lakeno`/`outletno` fk's — marking it pk here first
    # would carry a stale `pk=True` into those fk copies (`model_copy` off
    # the original field). No other pass between the old and new call sites
    # reads or depends on `pk`/`fk` state.
    blocks = _mark_lonely_pk(blocks)
    blocks = _fix_cellid_fields(name, blocks)
    blocks = _mark_cellids(blocks)
    blocks = _apply_fk_backfill(name, blocks)
    blocks = _apply_array_fk_backfill(name, blocks)
    dims = {**explicit_dims, **array_dims, **derived_dims} or None

    d: dict[str, Any] = {
        "schema_version": "2.0.0.dev2",
        "name": name,
        "parent": parent,
        "blocks": blocks or None,
        "dims": dims,
    }
    if name == "sim-nam":
        return v2.Simulation(**d)
    if name.endswith("-nam"):
        prefix = name.split("-")[0]
        return v2.Model(**d, dependent_variable=_DEPENDENT_VARS.get(prefix))

    subtype: Literal["solution", "exchange", "stress", "advanced", "utility"] | None = None
    if name.startswith("sln-"):
        subtype = "solution"
    elif name.startswith("exg-"):
        subtype = "exchange"
    elif name.startswith("utl-"):
        subtype = "utility"
    else:
        # Transport-side advanced packages (gwt-lkt, gwe-lke, etc.) pair with a
        # GWF advanced package via flow_package_name but lack the v1
        # "package-type advanced-stress-package" header.
        is_advanced = is_advanced_package(meta) or any(
            f["name"] == "flow_package_name" for f in fields.values(multi=True)
        )
        is_stress_pkg = is_stress_package(name, meta)
        subtype = "advanced" if is_advanced else "stress" if is_stress_pkg else None
    return v2.Package(**d, subtype=subtype, multi=is_multi_package(meta))
