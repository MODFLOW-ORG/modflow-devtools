"""Tests for DFN schema PK/FK relations"""

import pytest

from modflow_devtools.dfns.schema import (
    Array,
    Block,
    CellID,
    Dfns,
    Double,
    File,
    InputDim,
    Integer,
    Keyword,
    List,
    Model,
    Package,
    Record,
    Simulation,
    String,
    Union,
    _validate_fk_fields,
    admits,
    covering_selector,
)


def _fk_validation_ctx(fk_val, pk_on_item=True, fk_ref=None):
    """
    Build a Package with a packagedata list block and a period block whose
    item record has a lakeno field with fk=fk_val (and optionally fk_ref).
    """
    nlakeconn = Integer(name="nlakeconn")
    lakeno_item = Integer(name="lakeno", pk=pk_on_item)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_item, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})

    fk_field = Integer(name="lakeno", fk=fk_val, fk_ref=fk_ref)
    period_item = Record(name="item", fields={"lakeno": fk_field})
    period_list = List(name="period", item=period_item)
    period_block = Block(name="period", fields={"period": period_list})

    gwf = Model(name="gwf-nam", blocks=None)
    lak = Package(
        name="gwf-lak",
        parent="gwf-nam",
        blocks={"packagedata": pkg_block, "period": period_block},
    )
    return lak, gwf


def test_dfns_validate_fk_fields():
    lak, gwf = _fk_validation_ctx("packagedata", pk_on_item=True)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    assert "gwf-lak" in spec.components


def test_dfns_validate_fk_fields_unknown_block():
    lak, gwf = _fk_validation_ctx("nosuchblock", pk_on_item=True)
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})


def test_dfns_validate_fk_fields_no_pk_on_item():
    lak, gwf = _fk_validation_ctx("packagedata", pk_on_item=False)
    with pytest.raises(ValueError, match="has no pk=True field"):
        Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})


def _mvr_id_ctx(fk_val="packagedata", fk_ref="pname1", with_pname_sibling=True):
    """
    Build a Package mimicking gwf-mvr's period block: an `id1` field with
    `fk`/`fk_ref` set, alongside a sibling `pname1` String field (unless
    ``with_pname_sibling`` is False).
    """
    fields: dict = {"id1": Integer(name="id1", fk=fk_val, fk_ref=fk_ref)}
    if with_pname_sibling:
        fields["pname1"] = String(name="pname1")
    item = Record(name="item", fields=fields)
    lst = List(name="period", item=item)
    block = Block(name="period", fields={"period": lst})
    pkg = Package(name="gwf-mvr", blocks={"period": block})
    gwf = Model(name="gwf-nam", blocks=None)
    return pkg, gwf


def test_dfns_validate_fk_fields_fk_ref():
    # Bare block name fk + fk_ref: fk_ref must name a sibling String field.
    # The target block/component are only resolved at runtime (from that
    # field's value), so no local "packagedata" block or pk is required.
    mvr, gwf = _mvr_id_ctx()
    spec = Dfns(components={"gwf-nam": gwf, "gwf-mvr": mvr})
    assert "gwf-mvr" in spec.components


def test_dfns_validate_fk_fields_fk_ref_not_sibling():
    mvr, gwf = _mvr_id_ctx(with_pname_sibling=False)
    with pytest.raises(ValueError, match="not a sibling String field"):
        Dfns(components={"gwf-nam": gwf, "gwf-mvr": mvr})


def test_dfns_validate_fk_fields_fk_ref_with_hierarchical_fk_rejected():
    mvr, gwf = _mvr_id_ctx(fk_val="packagedata.ifno")
    with pytest.raises(ValueError, match="may not be combined with fk_ref"):
        Dfns(components={"gwf-nam": gwf, "gwf-mvr": mvr})


def test_dfns_validate_fk_fields_fk_ref_with_node_not_special_cased():
    # "node" was formerly a reserved fk sentinel for grid-cell references (now
    # replaced by the dedicated `CellID` type); as a bare fk value
    # it's just an ordinary (if oddly named) block name like any other, so
    # combining it with fk_ref is unremarkable and must not raise.
    mvr, gwf = _mvr_id_ctx(fk_val="node")
    spec = Dfns(components={"gwf-nam": gwf, "gwf-mvr": mvr})
    assert "gwf-mvr" in spec.components


def test_dfns_validate_fk_fields_no_fk_set():
    item = Record(name="item", fields={"val": Double(name="val")})
    lst = List(name="data", item=item)
    block = Block(name="data", fields={"data": lst})
    pkg = Package(name="gwf-test", blocks={"data": block})
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})
    assert "gwf-test" in spec.components


def test_dfns_validate_fk_fields_called_directly():
    lak, gwf = _fk_validation_ctx("packagedata", pk_on_item=True)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    _validate_fk_fields(lak, spec)  # should not raise


def _aux_ctx(fk="options.auxiliary", auxiliary_dtype="string", tagged=False):
    """A grid-array package whose period `aux` list is keyed by an auxiliary name."""
    auxiliary = Array(name="auxiliary", dtype=auxiliary_dtype, optional=True)
    options = Block(name="options", fields={"auxiliary": auxiliary})
    auxname = String(name="auxname", tagged=tagged, fk=fk)
    array = Array(name="aux", dtype="double", tagged=False)
    item = Record(name="aux", fields={"auxname": auxname, "aux": array})
    period = Block(name="period", fields={"aux": List(name="aux", optional=True, item=item)})
    pkg = Package(name="gwf-rcha", parent="gwf-nam", blocks={"options": options, "period": period})
    return {"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-rcha": pkg}


def test_dfns_validate_fk_to_string_array():
    spec = Dfns(components=_aux_ctx())
    assert "gwf-rcha" in spec.components


def test_dfns_validate_fk_to_string_array_tagged_string():
    """A tagged String may reference a string array too, without being a dynamic key."""
    spec = Dfns(components=_aux_ctx(tagged=True))
    assert "gwf-rcha" in spec.components


def test_dfns_validate_fk_to_non_string_array_rejected():
    with pytest.raises(ValueError, match="must name a string array"):
        Dfns(components=_aux_ctx(auxiliary_dtype="double"))


def test_dfns_validate_fk_to_missing_field_rejected():
    with pytest.raises(ValueError, match="must name a string array"):
        Dfns(components=_aux_ctx(fk="options.nosuchfield"))


def _union_ctx(arm):
    """A package whose period list's item is a union of `arm` and a keyword-led record."""
    auxiliary = Array(name="auxiliary", dtype="string", optional=True)
    options = Block(name="options", fields={"auxiliary": auxiliary})
    other = Record(name="other", fields={"flag": Keyword(name="flag")})
    item = Union(name="setting", arms={arm.name: arm, "other": other})
    period = Block(name="period", fields={"setting": List(name="setting", item=item)})
    pkg = Package(name="gwf-test", parent="gwf-nam", blocks={"options": options, "period": period})
    return {"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-test": pkg}


def _keyed_arm(fk):
    auxname = String(name="auxname", tagged=False, fk=fk)
    array = Array(name="aux", dtype="double", tagged=False)
    return Record(name="aux", fields={"auxname": auxname, "aux": array})


def test_dfns_validate_fk_in_union_item_record_arm():
    assert "gwf-test" in Dfns(components=_union_ctx(_keyed_arm("options.auxiliary"))).components
    with pytest.raises(ValueError, match="must name a string array"):
        Dfns(components=_union_ctx(_keyed_arm("options.nosuchfield")))


def test_dfns_validate_fk_in_union_item_scalar_arm():
    arm = Integer(name="lakeno", fk="nosuchblock.lakeno")
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_union_ctx(arm))


def _cellid_ctx(field, name="gwf-gnc", parent="gwf-nam", dims=None):
    item = Record(name="item", fields={field.name: field})
    lst = List(name="data", item=item)
    block = Block(name="data", fields={"data": lst})
    pkg = Package(name=name, parent=parent, blocks={"data": block}, dims=dims)
    gwf = Model(name="gwf-nam", blocks=None)
    return {"gwf-nam": gwf, name: pkg}


@pytest.mark.parametrize(
    "field",
    [
        CellID(name="cellid"),
        Array(name="cellidsj", dtype="cellid", shape=["n"]),
    ],
)
def test_dfns_validate_cellid_in_list_item(field):
    # No component declares `ncelldim`: a cellid's width comes from the grid
    # it refers to, so it isn't in any shape. An array's shape counts its
    # cellids, and is resolved as usual.
    dims = {"n": InputDim(value="2", scope="model")}
    spec = Dfns(components=_cellid_ctx(field, dims=dims))
    assert "gwf-gnc" in spec.components


def test_dfns_validate_cellid_array_shape_resolves():
    field = Array(name="cellidsj", dtype="cellid", shape=["n"])
    with pytest.raises(ValueError, match="'n' does not resolve"):
        Dfns(components=_cellid_ctx(field))


def _exchange_ctx(*fields):
    item = Record(name="item", fields={f.name: f for f in fields})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    exg = Package(name="exg-gwfgwf", subtype="exchange", blocks={"data": block})
    return {"exg-gwfgwf": exg}


def _cellid_col(name, model=None, shape=None):
    if shape is None:
        return CellID(name=name, model=model)
    return Array(name=name, dtype="cellid", shape=list(shape), model=model)


def test_dfns_validate_cellid_in_exchange():
    fields = (_cellid_col("cellidm1", "1"), _cellid_col("cellidm2", "2"))
    spec = Dfns(components=_exchange_ctx(*fields))
    item = spec.components["exg-gwfgwf"].blocks["data"].fields["data"].item
    assert {n: f.model for n, f in item.fields.items()} == {"cellidm1": "1", "cellidm2": "2"}


@pytest.mark.parametrize("shape", [None, ["n"]])
def test_dfns_validate_exchange_cellid_must_name_model(shape):
    fields = (_cellid_col("cellidm1", shape=shape), _cellid_col("cellidm2", shape=shape))
    with pytest.raises(ValueError, match="exchange's cellid must say which model"):
        Dfns(components=_exchange_ctx(*fields))


def test_dfns_validate_cellid_models_under_a_model():
    # GNC under a model: both models are that model, so "1"/"2" are valid.
    fields = (
        _cellid_col("cellidn", "1"),
        _cellid_col("cellidm", "2"),
        _cellid_col("cellidsj", "1", shape=("n",)),
    )
    item = Record(name="item", fields={f.name: f for f in fields})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(
        name="gwf-gnc",
        parent="gwf-nam",
        blocks={"data": block},
        dims={"n": InputDim(value="2", scope="model")},
    )
    spec = Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})
    assert "gwf-gnc" in spec.components


def test_dfns_validate_cellid_no_mixing():
    item = Record(name="item", fields={"a": _cellid_col("a", "1"), "b": _cellid_col("b")})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block})
    with pytest.raises(ValueError, match="mix model=None with '1'/'2'"):
        Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})


def _union_cellid_pkg(arm_model, sibling_model):
    union = Union(
        name="id",
        tagged=False,
        arms={
            "cellid": _cellid_col("cellid", arm_model),
            "boundname": String(name="boundname", tagged=False),
        },
    )
    item = Record(name="item", fields={"a": _cellid_col("a", sibling_model), "id": union})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block})
    return {"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg}


def test_dfns_validate_cellid_no_mixing_across_union_arm():
    # A union arm's cellid is read in the same row as its sibling columns.
    with pytest.raises(ValueError, match="mix model=None with '1'/'2'"):
        Dfns(components=_union_cellid_pkg(None, "1"))


@pytest.mark.parametrize("model", [None, "1"])
def test_dfns_validate_cellid_union_arm_consistent(model):
    assert "gwf-gnc" in Dfns(components=_union_cellid_pkg(model, model)).components


def test_dfns_validate_cellid_union_arms_are_alternatives():
    # Arms are never read together, so arms disagreeing is not mixing; each
    # is checked against the row's other cellid columns.
    union = Union(
        name="id",
        arms={"x": _cellid_col("x", "1"), "y": _cellid_col("y", "2")},
    )
    item = Record(name="item", fields={"a": _cellid_col("a", "1"), "id": union})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block})
    Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})


@pytest.mark.parametrize("value", [True, 1, 2, 0, "true", "3", "a"])
@pytest.mark.parametrize("shape", [None, ["n"]])
def test_cellid_rejects_non_model_values(value, shape):
    # `True == 1`: an int or bool must never be read as (or coerced to) a model.
    with pytest.raises(ValueError, match="model"):
        _cellid_col("cellid", value, shape=shape)


def test_cellid_render():
    assert CellID(name="cellid", tagged=False).render(inline=True) == "<cellid(ncelldim)>"
    assert CellID(name="cellid", optional=True).render(inline=True) == "[CELLID <cellid(ncelldim)>]"
    arr = Array(name="cellidsj", dtype="cellid", shape=["numalphaj"], tagged=False)
    assert arr.render(inline=True) == "<cellidsj(ncelldim, numalphaj)>"


@pytest.mark.parametrize("attr", ["model", "allow_zero"])
def test_array_cellid_attrs_require_cellid_dtype(attr):
    value = "1" if attr == "model" else True
    with pytest.raises(ValueError, match=f"{attr} requires dtype='cellid'"):
        Array(name="alphasj", dtype="integer", shape=["n"], **{attr: value})


@pytest.mark.parametrize(
    "attr, value, match",
    [
        ("index", True, "index=True requires dtype='integer'"),
        ("fk", "packagedata.ifno", "fk requires dtype='integer'"),
        ("time_series", True, "time_series is not valid with dtype='cellid'"),
        ("layered", True, "layered is not valid with dtype='cellid'"),
        ("netcdf", True, "netcdf is not valid with dtype='cellid'"),
    ],
)
def test_array_cellid_rejects_attrs(attr, value, match):
    with pytest.raises(ValueError, match=match):
        Array(name="cellidsj", dtype="cellid", shape=["n"], **{attr: value})


@pytest.mark.parametrize("attr", ["index", "time_series", "fk", "shape", "dtype"])
def test_cellid_has_no_array_attrs(attr):
    # Pydantic ignores unknown keys, so check the class simply doesn't have them.
    assert attr not in CellID.model_fields


def test_dfns_validate_cellid_outside_list_item():
    block = Block(name="options", fields={"cellid": CellID(name="cellid")})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"options": block})
    gwf = Model(name="gwf-nam", blocks=None)
    with pytest.raises(ValueError, match="only valid as a column in a list item"):
        Dfns(components={"gwf-nam": gwf, "gwf-gnc": pkg})


# --- observation types ---


def _obs_spec(observations: dict) -> dict:
    """gwf-lak with a packagedata list keyed by `ifno`."""
    pkg_item = Record(name="item", fields={"ifno": Integer(name="ifno", pk=True)})
    pkg_list = List(name="packagedata", item=pkg_item)
    lak = Package(
        name="gwf-lak",
        parent="gwf-nam",
        blocks={"packagedata": Block(name="packagedata", fields={"packagedata": pkg_list})},
        observations=observations,
    )
    return {"gwf-nam": Model(name="gwf-nam"), "gwf-lak": lak}


def _lak_obs(fk: str = "packagedata.ifno", tagged: bool = False) -> Union:
    """LAK's `lak` obstype: a lake and connection, or a boundname."""
    feature = Record(
        name="ifno",
        tagged=False,
        fields={
            "ifno": Integer(name="ifno", tagged=False, index=True, fk=fk),
            "iconn": Integer(name="iconn", tagged=tagged, index=True),
        },
    )
    boundname = String(name="boundname", tagged=False)
    return Union(name="lak", tagged=False, arms={"ifno": feature, "boundname": boundname})


def test_dfns_validate_observations():
    observations = {
        "lak": _lak_obs(),
        "head": Array(
            name="head", tagged=False, dtype="integer", shape=["ncelldim"], index=True, cellid=True
        ),
    }
    spec = Dfns(components=_obs_spec(observations))
    assert spec.components["gwf-lak"].observations == observations


def test_dfns_validate_observations_unresolved_fk():
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_obs_spec({"lak": _lak_obs(fk="nosuch.ifno")}))


def test_dfns_validate_observations_untagged():
    with pytest.raises(ValueError, match=r"\['iconn'\] must be untagged"):
        Dfns(components=_obs_spec({"lak": _lak_obs(tagged=True)}))


def test_dfns_validate_observations_lower_case():
    with pytest.raises(ValueError, match="must be lower case"):
        Dfns(components=_obs_spec({"LAK": _lak_obs()}))


def test_dfns_validate_observations_at_most_two_columns():
    fields = {n: Integer(name=n, tagged=False, index=True) for n in ("a", "b", "c")}
    observations = {"x": Record(name="x", tagged=False, fields=fields)}
    with pytest.raises(ValueError, match="at most id2"):
        Dfns(components=_obs_spec(observations))


# --- file links (File.component / component_ftype) ---


def _file_block(file: File, **siblings) -> dict:
    item = Record(name="item", fields={**siblings, file.name: file})
    return {"links": Block(name="links", fields={"links": List(name="links", item=item)})}


def _link_spec(file: File, owner: str = "gwf-dis", **siblings) -> dict:
    """A gwf model with dis, rch/rcha (a variant family) and a utl-ncf
    utility attached by packages; ``file`` goes in ``owner``."""
    components = {
        "sim-nam": Simulation(name="sim-nam"),
        "gwf-nam": Model(name="gwf-nam", parent="sim-nam", ftype="GWF6"),
        "gwf-dis": Package(name="gwf-dis", parent="gwf-nam", ftype="DIS6"),
        "gwf-rch": Package(name="gwf-rch", parent="gwf-nam", subtype="stress", ftype="RCH6"),
        "gwf-rcha": Package(name="gwf-rcha", parent="gwf-nam", subtype="stress", ftype="RCH6"),
        "utl-ncf": Package(name="utl-ncf", parent="package", subtype="utility", ftype="NCF6"),
    }
    components[owner] = components[owner].model_copy(
        update={"blocks": _file_block(file, **siblings)}
    )
    return components


def test_file_link_fixed_target():
    file = File(name="ncf6_filename", direction="in", component="utl-ncf")
    Dfns(components=_link_spec(file))


def test_file_link_variant_family_without_component_ftype():
    file = File(name="f", direction="in", component=["gwf-rch", "gwf-rcha"])
    Dfns(components=_link_spec(file, owner="gwf-nam"))


def test_file_link_component_ftype():
    file = File(name="fname", direction="in", component="package", component_ftype="ftype")
    Dfns(components=_link_spec(file, owner="gwf-nam", ftype=String(name="ftype")))


def test_file_link_output_rejected():
    file = File(name="f", direction="out", component="utl-ncf")
    with pytest.raises(ValueError, match="only an input file"):
        Dfns(components=_link_spec(file))


def test_file_link_unknown_selector_rejected():
    file = File(name="f", direction="in", component="utl-nope")
    with pytest.raises(ValueError, match="matches none"):
        Dfns(components=_link_spec(file))


def test_file_link_not_a_child_rejected():
    # utl-ncf's parent is `package`, which doesn't admit the model
    file = File(name="f", direction="in", component="utl-ncf")
    with pytest.raises(ValueError, match="matches none"):
        Dfns(components=_link_spec(file, owner="gwf-nam"))


def test_file_link_ambiguous_without_component_ftype_rejected():
    file = File(name="f", direction="in", component="package")
    with pytest.raises(ValueError, match="no component_ftype"):
        Dfns(components=_link_spec(file, owner="gwf-nam"))


def test_file_link_component_ftype_not_sibling_rejected():
    file = File(name="f", direction="in", component="package", component_ftype="ftype")
    with pytest.raises(ValueError, match="not a sibling String"):
        Dfns(components=_link_spec(file, owner="gwf-nam"))


def test_admits():
    rch = Package(name="gwf-rch", parent="gwf-nam", subtype="stress")
    assert admits("gwf-rch", rch)
    assert admits("stress", rch)
    assert admits("package", rch)
    assert admits(["model", "stress"], rch)
    assert admits("*", rch)
    assert not admits("model", rch)
    assert not admits(None, rch)


def test_covering_selector():
    nam = Model(name="gwf-nam")
    exg = Package(name="exg-gwfgwf", subtype="exchange")
    npf = Package(name="gwf-npf")
    wel = Package(name="gwf-wel", subtype="stress")
    chd = Package(name="gwf-chd", subtype="stress")
    spc = Package(name="utl-spc", subtype="utility")
    all_ = {c.name: c for c in (nam, exg, npf, wel, chd, spc)}
    # one linker: its own name
    assert covering_selector([npf], all_) == "gwf-npf"
    # a shared subtype beats a type
    assert covering_selector([wel, chd], all_) == "stress"
    # one type term beats two narrower ones
    assert covering_selector([wel, spc], all_) == "package"
    # no single term covers a model and an exchange: concrete names
    assert covering_selector([nam, exg], all_) == ["exg-gwfgwf", "gwf-nam"]
    # models and packages: their types
    gwt = Model(name="gwt-nam")
    all_[gwt.name] = gwt
    assert covering_selector([wel, npf, nam, gwt], all_) == ["model", "package"]


def test_children_list_parent():
    gwf = Model(name="gwf-nam", parent="sim-nam")
    exg = Package(name="exg-gwfgwf", parent="sim-nam", subtype="exchange")
    gnc = Package(name="gwf-gnc", parent=["gwf-nam", "exg-gwfgwf"])
    spec = Dfns(
        components={
            "sim-nam": Simulation(name="sim-nam"),
            "gwf-nam": gwf,
            "exg-gwfgwf": exg,
            "gwf-gnc": gnc,
        }
    )
    assert "gwf-gnc" in spec.children("gwf-nam")
    assert "gwf-gnc" in spec.children("exg-gwfgwf")
    assert "gwf-gnc" not in spec.children("sim-nam")


def test_ftype_family():
    spec = Dfns(components=_link_spec(File(name="f", direction="in")))
    spec.components["exg-gwfgwf"] = Package(name="exg-gwfgwf", parent="sim-nam", ftype="GWF6-GWF6")
    assert spec.ftype_family("DIS6", "gwf-nam") == ["gwf-dis"]
    assert spec.ftype_family("rch6", "gwf-nam") == ["gwf-rch", "gwf-rcha"]
    assert spec.ftype_family("GWF6", "sim-nam") == ["gwf-nam"]
    assert spec.ftype_family("GWF6-GWF6", "sim-nam") == ["exg-gwfgwf"]
    assert spec.ftype_family("NCF6", "gwf-nam") == []


def test_concrete_package_parent_sees_model_dims():
    """A subpackage whose parent is a concrete package (utl-tvk's gwf-npf)
    is in that package's model, so it sees the model's grid dims."""
    spec = Dfns(
        components={
            "gwf-nam": Model(name="gwf-nam"),
            "gwf-dis": Package(
                name="gwf-dis",
                parent="gwf-nam",
                dims={"nodes": InputDim(value="10", scope="model")},
            ),
            "gwf-npf": Package(name="gwf-npf", parent="gwf-nam"),
            "utl-tvk": Package(name="utl-tvk", parent="gwf-npf", subtype="utility"),
        }
    )
    assert "nodes" in spec.inherited_dims("utl-tvk")
