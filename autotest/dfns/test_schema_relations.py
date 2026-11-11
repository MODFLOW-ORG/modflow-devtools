"""Tests for DFN schema PK/FK relations"""

import pytest

from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import _replace_named
from modflow_devtools.dfns.schema import (
    Array,
    Block,
    CellID,
    Dfns,
    Double,
    File,
    ForeignKey,
    InputDim,
    Integer,
    KeySet,
    Keyword,
    List,
    Model,
    Package,
    Param,
    PrimaryKey,
    Record,
    Simulation,
    String,
    Union,
    _validate_fk_fields,
    admits,
    covering_selector,
)


def _fk_validation_ctx(fk_val, pk_on_item=True):
    """
    Build a Package with a packagedata list block and a period block whose
    item record has a lakeno field with fk=fk_val.
    """
    nlakeconn = Integer(name="nlakeconn")
    lakeno_item = Integer(name="lakeno", pk=pk_on_item)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_item, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})

    fk_field = Integer(name="lakeno", fk=fk_val)
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
    lak, gwf = _fk_validation_ctx("packagedata.lakeno", pk_on_item=True)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    assert "gwf-lak" in spec.components


def test_dfns_validate_fk_fields_unknown_block():
    lak, gwf = _fk_validation_ctx("nosuchblock.lakeno", pk_on_item=True)
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})


def test_dfns_validate_fk_fields_no_pk_on_item():
    lak, gwf = _fk_validation_ctx("packagedata.lakeno", pk_on_item=False)
    with pytest.raises(ValueError, match="is not the pk of"):
        Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})


@pytest.mark.parametrize("path", ["packagedata", "a.b.c.d", "packagedata."])
def test_foreign_key_path_rejected(path):
    with pytest.raises(ValueError, match="must be a hierarchical path"):
        Integer(name="lakeno", fk=path)


@pytest.mark.parametrize(
    "cls,toml,obj",
    [
        (Integer, {"pk": True}, {"pk": PrimaryKey()}),
        (Integer, {"pk": {"scope": "mname"}}, {"pk": PrimaryKey(scope="mname")}),
        (String, {"fk": "packages.pname"}, {"fk": ForeignKey(path="packages.pname")}),
        (
            String,
            {"fk": {"path": "packages.pname", "scope": "mname1"}},
            {"fk": ForeignKey(path="packages.pname", scope="mname1")},
        ),
    ],
)
def test_keys_load_as_objects_and_dump_as_written(cls, toml, obj):
    field = cls.model_validate({"name": "x", **toml})
    assert {k: getattr(field, k) for k in obj} == obj
    assert field.model_dump(exclude_defaults=True) == {"type": field.type, "name": "x", **toml}


def test_pk_false_loads_as_none():
    assert Integer.model_validate({"name": "x", "pk": False}).pk is None


def test_foreign_key_parts():
    fk = ForeignKey(path="gwf-nam.packages.pname")
    assert (fk.component, fk.block, fk.field) == ("gwf-nam", "packages", "pname")
    fk = ForeignKey(path="packages.pname")
    assert (fk.component, fk.block, fk.field) == (None, "packages", "pname")


def test_array_fk_scope_rejected():
    with pytest.raises(ValueError, match="can't be scoped"):
        Array(name="ids", dtype="string", fk={"path": "models.mname", "scope": "mtype"})


def test_dynamic_fk_scope_rejected():
    with pytest.raises(ValueError, match="can't be scoped"):
        String(
            name="pname",
            tagged=False,
            dynamic=True,
            fk={"path": "packages.pname", "scope": "mname"},
        )


def _mvr_ctx(
    packages_pk=None,
    packages_fk=None,
    period_fk=None,
    period_mname_fk="sim-nam.models.mname",
    period_extra=None,
):
    """
    A simulation with a GWF model and a mover whose `packages` rows key a
    package within a model, as MF6's exchange mover does, and whose period
    rows reference those rows.
    """
    mname = String(name="mname", tagged=False, pk=True)
    mfname = File(name="mfname", direction="in", mode_keyword=False, component="model")
    models_item = Record(
        name="models",
        fields={"mtype": String(name="mtype"), "mfname": mfname, "mname": mname},
    )
    models = Block(name="models", fields={"models": List(name="models", item=models_item)})
    sim = Simulation(name="sim-nam", blocks={"models": models})

    pname = String(name="pname", tagged=False, pk=True, optional=True)
    gwf_item = Record(name="packages", fields={"ftype": String(name="ftype"), "pname": pname})
    gwf_packages = Block(name="packages", fields={"packages": List(name="packages", item=gwf_item)})
    gwf = Model(name="gwf-nam", parent="sim-nam", blocks={"packages": gwf_packages})

    mvr_pname = String(
        name="pname",
        tagged=False,
        pk=packages_pk or {"scope": "mname"},
        fk=packages_fk or {"path": "gwf-nam.packages.pname", "scope": "mname"},
    )
    mvr_item = Record(
        name="packages",
        fields={
            "mname": String(name="mname", tagged=False, fk="sim-nam.models.mname"),
            "pname": mvr_pname,
        },
    )
    mvr_packages = Block(name="packages", fields={"packages": List(name="packages", item=mvr_item)})
    period_fields = {
        "mname1": String(name="mname1", tagged=False, fk=period_mname_fk),
        "pname1": String(
            name="pname1",
            tagged=False,
            fk=period_fk or {"path": "packages.pname", "scope": "mname1"},
        ),
        **(period_extra or {}),
    }
    period_item = Record(name="perioddata", fields=period_fields)
    period = Block(name="period", fields={"perioddata": List(name="perioddata", item=period_item)})
    mvr = Package(
        name="gwf-mvr", parent="gwf-nam", blocks={"packages": mvr_packages, "period": period}
    )
    return {"sim-nam": sim, "gwf-nam": gwf, "gwf-mvr": mvr}


def test_dfns_validate_scoped_keys():
    spec = Dfns(components=_mvr_ctx())
    pname = spec.components["gwf-mvr"].blocks["packages"].fields["packages"].item.fields["pname"]
    assert pname.pk == PrimaryKey(scope="mname")
    assert pname.fk == ForeignKey(path="gwf-nam.packages.pname", scope="mname")


@pytest.mark.parametrize("scope", ["nosuchfield", "pname1"])
def test_dfns_validate_scope_not_another_sibling(scope):
    with pytest.raises(ValueError, match="not another String or Integer field"):
        Dfns(components=_mvr_ctx(period_fk={"path": "packages.pname", "scope": scope}))


def test_dfns_validate_scope_cycle():
    extra = {"x": String(name="x", tagged=False, fk={"path": "packages.pname", "scope": "y"})}
    extra["y"] = String(name="y", tagged=False, fk={"path": "packages.pname", "scope": "x"})
    with pytest.raises(ValueError, match="scopes form a cycle"):
        Dfns(components=_mvr_ctx(period_extra=extra))


def _sfr_ctx(arm_idv_fk=None, item_ifno="ifno"):
    """
    A package whose `diversions` rows are keyed by (ifno, idv), and whose
    period rows give a diversion in a union arm, its `idv` scoped by the
    list item's `ifno` (SFR's).
    """
    ifno_pk = Integer(name="ifno", index=True, pk=True)
    pkg_item = Record(name="packagedata", fields={"ifno": ifno_pk})
    pkg = Block(name="packagedata", fields={"packagedata": List(name="packagedata", item=pkg_item)})
    div_item = Record(
        name="diversions",
        fields={
            "ifno": Integer(name="ifno", index=True, fk="packagedata.ifno"),
            "idv": Integer(name="idv", index=True, pk={"scope": "ifno"}),
        },
    )
    div = Block(name="diversions", fields={"diversions": List(name="diversions", item=div_item)})
    arm = Record(
        name="diversionrecord",
        fields={
            "diversion": Keyword(name="diversion"),
            "idv": Integer(
                name="idv",
                index=True,
                fk=arm_idv_fk or {"path": "diversions.idv", "scope": "ifno"},
            ),
            "divflow": Double(name="divflow"),
        },
    )
    setting = Union(name="sfrsetting", arms={"diversionrecord": arm})
    period_item = Record(
        name="perioddata",
        fields={
            item_ifno: Integer(name=item_ifno, index=True, fk="packagedata.ifno"),
            "sfrsetting": setting,
        },
    )
    period = Block(name="period", fields={"perioddata": List(name="perioddata", item=period_item)})
    sfr = Package(
        name="gwf-sfr",
        parent="gwf-nam",
        blocks={"packagedata": pkg, "diversions": div, "period": period},
    )
    return {"gwf-nam": Model(name="gwf-nam"), "gwf-sfr": sfr}


def test_dfns_validate_scope_in_enclosing_record():
    Dfns(components=_sfr_ctx())


def test_dfns_validate_scope_not_in_enclosing_record():
    with pytest.raises(ValueError, match="same or an enclosing record"):
        Dfns(components=_sfr_ctx(item_ifno="rno"))


def test_dfns_validate_enclosing_scope_must_match_target():
    with pytest.raises(ValueError, match="both or neither must be scoped"):
        Dfns(components=_sfr_ctx(arm_idv_fk="diversions.idv"))


def test_dfns_validate_two_pks_rejected():
    extra = {"id": Integer(name="id", pk=True), "id2": Integer(name="id2", pk=True)}
    with pytest.raises(ValueError, match="only one pk"):
        Dfns(components=_mvr_ctx(period_extra=extra))


def test_dfns_validate_pk_fk_scopes_differ():
    with pytest.raises(ValueError, match="pk and fk scopes differ"):
        Dfns(
            components=_mvr_ctx(
                packages_fk={"path": "gwf-nam.packages.pname", "scope": "pname"},
                packages_pk={"scope": "mname"},
            )
        )


def test_dfns_validate_unscoped_fk_to_scoped_pk():
    with pytest.raises(ValueError, match="both or neither must be scoped"):
        Dfns(components=_mvr_ctx(period_fk="packages.pname"))


def test_dfns_validate_scoped_fk_to_unscoped_pk():
    with pytest.raises(ValueError, match="both or neither must be scoped"):
        Dfns(components=_mvr_ctx(packages_pk=True, packages_fk="gwf-nam.packages.pname"))


def test_dfns_validate_scope_columns_reference_differently():
    with pytest.raises(ValueError, match="but the target's scope"):
        Dfns(components=_mvr_ctx(period_mname_fk="gwf-nam.packages.pname"))


def test_dfns_validate_cross_component_scope_not_a_binding():
    extra = {
        "pname2": String(
            name="pname2",
            tagged=False,
            fk={"path": "gwf-nam.packages.pname", "scope": "pname1"},
        )
    }
    with pytest.raises(ValueError, match="must be an fk to the row binding"):
        Dfns(components=_mvr_ctx(period_extra=extra))


def test_dfns_validate_fk_fields_no_fk_set():
    item = Record(name="item", fields={"val": Double(name="val")})
    lst = List(name="data", item=item)
    block = Block(name="data", fields={"data": lst})
    pkg = Package(name="gwf-test", blocks={"data": block})
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})
    assert "gwf-test" in spec.components


def test_dfns_validate_fk_fields_called_directly():
    lak, gwf = _fk_validation_ctx("packagedata.lakeno", pk_on_item=True)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    _validate_fk_fields(lak, spec)  # should not raise


def _aux_ctx(fk="options.auxiliary", auxiliary_dtype="string", tagged=False):
    """A grid-array package whose period `aux` list is keyed by an auxiliary name."""
    auxiliary = Array(name="auxiliary", dtype=auxiliary_dtype, optional=True)
    options = Block(name="options", fields={"auxiliary": auxiliary})
    auxname = String(name="auxname", tagged=tagged, fk=fk, dynamic=not tagged)
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
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_aux_ctx(auxiliary_dtype="double"))


def test_dfns_validate_fk_to_missing_field_rejected():
    with pytest.raises(ValueError, match="is not a list block"):
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
    auxname = String(name="auxname", tagged=False, fk=fk, dynamic=True)
    array = Array(name="aux", dtype="double", tagged=False)
    return Record(name="aux", fields={"auxname": auxname, "aux": array})


def test_dfns_validate_fk_in_union_item_record_arm():
    assert "gwf-test" in Dfns(components=_union_ctx(_keyed_arm("options.auxiliary"))).components
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_union_ctx(_keyed_arm("options.nosuchfield")))


def test_dfns_validate_fk_in_union_item_scalar_arm():
    arm = Integer(name="lakeno", fk="nosuchblock.lakeno")
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_union_ctx(arm))


def _model_names_ctx(fk="models.mname", pk=True):
    """A simulation whose solution rows each name several models, by key."""
    mname = String(name="mname", tagged=False, pk=pk)
    models_item = Record(name="models", fields={"mtype": String(name="mtype"), "mname": mname})
    models = Block(name="models", fields={"models": List(name="models", item=models_item)})
    slnmnames = Array(name="slnmnames", dtype="string", tagged=False, fk=fk)
    sln_item = Record(
        name="sln", fields={"slntype": String(name="slntype"), "slnmnames": slnmnames}
    )
    sln = Block(name="sln", fields={"sln": List(name="sln", item=sln_item)})
    return {"sim-nam": Simulation(name="sim-nam", blocks={"models": models, "sln": sln})}


def test_dfns_validate_string_array_fk():
    assert "sim-nam" in Dfns(components=_model_names_ctx()).components


def test_dfns_validate_string_array_fk_no_pk_rejected():
    with pytest.raises(ValueError, match="is not the pk of"):
        Dfns(components=_model_names_ctx(pk=False))


def test_dfns_validate_string_array_fk_unknown_block_rejected():
    with pytest.raises(ValueError, match="is not a list block"):
        Dfns(components=_model_names_ctx(fk="nosuchblock.mname"))


def _hpc_ctx(dynamic=False):
    """A simulation plus an HPC-like package whose rows lead with a model name."""
    mname = String(name="mname", tagged=False, fk="sim-nam.models.mname", dynamic=dynamic)
    mrank = Integer(name="mrank", tagged=False)
    item = Record(name="partitions", fields={"mname": mname, "mrank": mrank})
    partitions = Block(name="partitions", fields={"partitions": List(name="partitions", item=item)})
    hpc = Package(name="utl-hpc", parent="sim-nam", blocks={"partitions": partitions})
    return {**_model_names_ctx(), "utl-hpc": hpc}


def test_dfns_validate_leading_fk_to_list_pk_is_data():
    """A leading untagged String keying another component's list is data
    unless marked dynamic: its list stays untagged."""
    spec = Dfns(components=_hpc_ctx())
    assert spec.components["utl-hpc"].blocks["partitions"].fields["partitions"].tagged is False


def test_dfns_validate_dynamic_key_to_list_pk():
    """A dynamic key's keywords may come from a list's pk as well as a string array."""
    spec = Dfns(components=_hpc_ctx(dynamic=True))
    assert spec.components["utl-hpc"].blocks["partitions"].fields["partitions"].tagged is True


@pytest.mark.parametrize("dtype", ["integer", "string"])
def test_array_fk_bare_block_rejected(dtype):
    with pytest.raises(ValueError, match="must be a hierarchical path"):
        Array(name="slnmnames", dtype=dtype, fk="models")


@pytest.mark.parametrize("dtype", ["double", "keyword"])
def test_array_fk_requires_integer_or_string_dtype(dtype):
    with pytest.raises(ValueError, match="fk requires dtype='integer' or 'string'"):
        Array(name="slnmnames", dtype=dtype, fk="models.mname")


# A GNC's or an exchange's two models, as parameters (see `Param`).
_MODELS = {"model1": Param(type="model"), "model2": Param(type="model")}


def _cellid_ctx(field, name="gwf-gnc", parent="gwf-nam", dims=None):
    item = Record(name="item", fields={field.name: field})
    lst = List(name="data", item=item)
    block = Block(name="data", fields={"data": lst})
    pkg = Package(name=name, parent=parent, blocks={"data": block}, dims=dims, params=_MODELS)
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
    exg = Package(name="exg-gwfgwf", subtype="exchange", blocks={"data": block}, params=_MODELS)
    return {"gwf-nam": Model(name="gwf-nam", blocks=None), "exg-gwfgwf": exg}


def _cellid_col(name, model=None, shape=None):
    if shape is None:
        return CellID(name=name, model=model)
    return Array(name=name, dtype="cellid", shape=list(shape), model=model)


def test_dfns_validate_cellid_in_exchange():
    fields = (_cellid_col("cellidm1", "model1"), _cellid_col("cellidm2", "model2"))
    spec = Dfns(components=_exchange_ctx(*fields))
    item = spec.components["exg-gwfgwf"].blocks["data"].fields["data"].item
    models = {n: f.model for n, f in item.fields.items()}
    assert models == {"cellidm1": "model1", "cellidm2": "model2"}


@pytest.mark.parametrize("shape", [None, ["n"]])
def test_dfns_validate_exchange_cellid_must_name_model(shape):
    fields = (_cellid_col("cellidm1", shape=shape), _cellid_col("cellidm2", shape=shape))
    with pytest.raises(ValueError, match="exchange's cellid must say which model"):
        Dfns(components=_exchange_ctx(*fields))


def test_dfns_validate_cellid_models_under_a_model():
    # GNC under a model: its model parameters are unset, meaning that model.
    fields = (
        _cellid_col("cellidn", "model1"),
        _cellid_col("cellidm", "model2"),
        _cellid_col("cellidsj", "model1", shape=("n",)),
    )
    item = Record(name="item", fields={f.name: f for f in fields})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(
        name="gwf-gnc",
        parent="gwf-nam",
        blocks={"data": block},
        dims={"n": InputDim(value="2", scope="model")},
        params=_MODELS,
    )
    spec = Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})
    assert "gwf-gnc" in spec.components


def test_dfns_validate_cellid_no_mixing():
    item = Record(name="item", fields={"a": _cellid_col("a", "model1"), "b": _cellid_col("b")})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block}, params=_MODELS)
    with pytest.raises(ValueError, match="mix model=None with a named model"):
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
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block}, params=_MODELS)
    return {"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg}


def test_dfns_validate_cellid_no_mixing_across_union_arm():
    # A union arm's cellid is read in the same row as its sibling columns.
    with pytest.raises(ValueError, match="mix model=None with a named model"):
        Dfns(components=_union_cellid_pkg(None, "model1"))


@pytest.mark.parametrize("model", [None, "model1"])
def test_dfns_validate_cellid_union_arm_consistent(model):
    assert "gwf-gnc" in Dfns(components=_union_cellid_pkg(model, model)).components


def test_dfns_validate_cellid_union_arms_are_alternatives():
    # Arms are never read together, so arms disagreeing is not mixing; each
    # is checked against the row's other cellid columns.
    union = Union(
        name="id",
        arms={"x": _cellid_col("x", "model1"), "y": _cellid_col("y", "model2")},
    )
    item = Record(name="item", fields={"a": _cellid_col("a", "model1"), "id": union})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block}, params=_MODELS)
    Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})


@pytest.mark.parametrize("value", [True, 1, 2, 0, "1", "", "model 1"])
@pytest.mark.parametrize("shape", [None, ["n"]])
def test_cellid_rejects_non_model_values(value, shape):
    # A model is a parameter's name. `True == 1`: an int or bool must never be
    # read as (or coerced to) one.
    with pytest.raises(ValueError, match="model"):
        _cellid_col("cellid", value, shape=shape)


@pytest.mark.parametrize("params", [None, {"model1": Param(type="package")}])
def test_dfns_validate_cellid_model_names_a_model_param(params):
    # The name must be a parameter of the component, and of a model.
    item = Record(name="item", fields={"a": _cellid_col("a", "model1")})
    block = Block(name="data", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-gnc", parent="gwf-nam", blocks={"data": block}, params=params)
    with pytest.raises(ValueError, match="model='model1' names no parameter of gwf-gnc"):
        Dfns(components={"gwf-nam": Model(name="gwf-nam", blocks=None), "gwf-gnc": pkg})


def test_cellid_render():
    assert CellID(name="cellid", tagged=False).render(inline=True) == "<cellid(ncelldim)>"
    assert CellID(name="cellid", optional=True).render(inline=True) == "[CELLID <cellid(ncelldim)>]"
    arr = Array(name="cellidsj", dtype="cellid", shape=["numalphaj"], tagged=False)
    assert arr.render(inline=True) == "<cellidsj(ncelldim, numalphaj)>"


@pytest.mark.parametrize("attr", ["model", "allow_zero"])
def test_array_cellid_attrs_require_cellid_dtype(attr):
    value = "model1" if attr == "model" else True
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


def _when_ctx(when, option=None):
    options = Block(name="options", fields={option.name: option} if option else {})
    col = Double(name="petm0", tagged=False, when=when)
    item = Record(name="item", fields={"rate": Double(name="rate", tagged=False), "petm0": col})
    period = Block(name="period", fields={"data": List(name="data", item=item)})
    pkg = Package(name="gwf-evt", blocks={"options": options, "period": period})
    return {"gwf-evt": pkg}


def test_dfns_validate_when_names_keyword_option():
    spec = Dfns(components=_when_ctx("surf", Keyword(name="surf", optional=True)))
    item = spec.components["gwf-evt"].blocks["period"].fields["data"].item
    assert item.fields["petm0"].when == "surf"


@pytest.mark.parametrize(
    "option", [None, Keyword(name="other", optional=True), Integer(name="surf", optional=True)]
)
def test_dfns_validate_when_names_no_keyword_option(option):
    with pytest.raises(
        ValueError, match="when='surf' names no keyword option or parameter of gwf-evt"
    ):
        Dfns(components=_when_ctx("surf", option))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"index": True},
        {"fk": "packagedata.ifno"},
        {"fk": "packagedata.ifno", "index": "signed"},
    ],
)
def test_integer_allow_zero_requires_index_fk(kwargs):
    with pytest.raises(ValueError, match="allow_zero requires an fk and index=true"):
        Integer(name="lakeout", allow_zero=True, **kwargs)


def test_integer_allow_zero_round_trips():
    col = Integer(name="lakeout", index=True, fk="packagedata.ifno", allow_zero=True)
    assert Integer.model_validate(col.model_dump()) == col


# Component `keys` named by an fk's `key`, and named rules (`fk.rule`).


@pytest.mark.parametrize(
    "toml, obj",
    [
        (
            {"scope": "pname1", "key": "mover_provider"},
            ForeignKey(scope="pname1", key="mover_provider"),
        ),
        ({"key": "bound", "param": "target"}, ForeignKey(key="bound", param="target")),
        ({"param": ["model1", "model2"]}, ForeignKey(param=("model1", "model2"))),
        (
            {"path": "gwf-nam.packages.pname", "rule": "flow_model"},
            ForeignKey(path="gwf-nam.packages.pname", rule="flow_model"),
        ),
    ],
)
def test_key_and_rule_fks_load(toml, obj):
    field = String.model_validate({"name": "x", "fk": toml})
    assert field.fk == obj
    dumped = field.model_dump(exclude_defaults=True)["fk"]
    assert dumped == toml
    assert String.model_validate({"name": "x", "fk": dumped}).fk == obj


def test_key_fk_parts():
    fk = ForeignKey(scope="pname1", key="mover_provider")
    assert (fk.component, fk.block, fk.field, fk.simple) == (None, None, None, False)
    fk = ForeignKey(path="gwf-nam.packages.pname", rule="flow_model")
    assert (fk.component, fk.block, fk.field, fk.simple) == ("gwf-nam", "packages", "pname", False)


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({}, "needs one of path, key and param"),
        ({"path": "a.b", "key": "k", "scope": "s"}, "with a path can't have a key or param"),
        ({"path": "a.b", "param": "target"}, "with a path can't have a key or param"),
        ({"key": "mover_provider"}, "needs one of scope and param"),
        ({"key": "bound", "rule": "flow_model"}, "needs one of scope and param"),
        ({"key": "bound", "scope": "s", "param": "p"}, "needs one of scope and param"),
        ({"key": "bound", "param": ["p", "q"]}, "picks its instance by one param"),
        ({"param": "p", "scope": "s"}, "only a param can't have a scope or rule"),
        ({"param": "p", "rule": "flow_model"}, "only a param can't have a scope or rule"),
        ({"param": []}, "at least one parameter"),
        ({"param": ["p", "p"]}, "repeat a parameter"),
        ({"param": "a.b"}, "must be a parameter name"),
        ({"key": "a.b", "scope": "s"}, "must be a key set name"),
        ({"path": "a.b", "rule": "nope"}, "fk rule 'nope' is not one of"),
    ],
)
def test_fk_form_errors(kwargs, match):
    with pytest.raises(ValueError, match=match):
        ForeignKey(**kwargs)


def test_rule_fk_not_on_arrays_or_dynamic_keywords():
    fk = {"path": "a.b", "rule": "flow_model"}
    with pytest.raises(ValueError, match="an array's fk must be a plain path"):
        Array(name="x", dtype="string", fk=fk)
    with pytest.raises(ValueError, match="dynamic keyword's fk must be a plain path"):
        String(name="x", tagged=False, dynamic=True, fk=fk)


@pytest.mark.parametrize("path", ["a.b.c", "a", "<maxbound", ">=maxbound", "<=n + 1", "<="])
def test_keyset_path_rejected(path):
    with pytest.raises(ValueError, match=r"must be 'block\.field' or a bound"):
        KeySet(path=path)


@pytest.mark.parametrize(
    "path, match",
    [
        ([], "at least one path"),
        (["a.b", "a.b"], "repeat a path"),
        (["a.b", "<=maxbound"], "a bound can't be one of several paths"),
        (["a.b", "a.b.c"], r"must be 'block\.field' or a bound"),
    ],
)
def test_keyset_paths_rejected(path, match):
    with pytest.raises(ValueError, match=match):
        KeySet(path=path)


def test_keyset_paths():
    """Several paths are a union; one path in a list is just that path."""
    ks = KeySet(path=["sources.pname", "fileinput.pname"])
    assert ks.path == ("sources.pname", "fileinput.pname")
    assert ks.paths == ks.path and ks.bound is None
    assert KeySet(path=["a.b"]) == KeySet(path="a.b")
    assert KeySet(path="<=maxbound").paths == ("<=maxbound",)
    pkg = Package.model_validate(
        {"name": "gwt-ssm", "keys": {"source": ["sources.pname", "fileinput.pname"]}}
    )
    assert pkg.model_dump(exclude_defaults=True)["keys"] == {
        "source": ["sources.pname", "fileinput.pname"]
    }


def test_keyset_bound():
    assert KeySet(path="<=maxbound").bound == "maxbound"
    assert KeySet(path="outlets.outletno").bound is None


def test_keys_load_and_dump_as_paths():
    pkg = Package.model_validate({"name": "gwf-wel", "keys": {"bound": "<=maxbound"}})
    assert pkg.keys == {"bound": KeySet(path="<=maxbound")}
    assert pkg.model_dump(exclude_defaults=True)["keys"] == {"bound": "<=maxbound"}


def test_keys_with_when_load_and_dump_as_tables():
    """A key set switched on by an option is written `{path, when}`; one
    without stays its path alone."""
    keys = {
        "mover_provider": {"path": "<=maxbound", "when": "mover"},
        "bound": "<=maxbound",
    }
    pkg = Package.model_validate({"name": "gwf-wel", "keys": keys})
    assert pkg.keys["mover_provider"] == KeySet(path="<=maxbound", when="mover")
    assert pkg.model_dump(exclude_defaults=True)["keys"] == keys


def _list_block(name, *fields, list_name=None):
    item = Record(name=name, fields={f.name: f for f in fields})
    return Block(name=name, fields={list_name or name: List(name=list_name or name, item=item)})


def _options(*names):
    return Block(name="options", fields={n: Keyword(name=n, optional=True) for n in names})


def _ctx_sim():
    """A simulation binding models (`models` rows) and exchanges
    (`exchanges` rows, which name two models), a GWF model whose name file
    binds packages, and a GWF-GWF exchange binding a mover; and a factory
    for other model name files."""
    sim = Simulation(
        name="sim-nam",
        blocks={
            "models": _list_block(
                "models",
                String(name="mtype", tagged=False),
                File(
                    name="mfname",
                    tagged=False,
                    direction="in",
                    mode_keyword=False,
                    component="model",
                    component_ftype="mtype",
                ),
                String(name="mname", tagged=False, pk=True),
            ),
            "exchanges": _list_block(
                "exchanges",
                String(name="exgtype", tagged=False),
                File(
                    name="exgfile",
                    tagged=False,
                    direction="in",
                    mode_keyword=False,
                    component="exchange",
                    component_ftype="exgtype",
                    args={"model1": "exgmnamea", "model2": "exgmnameb"},
                ),
                String(name="exgmnamea", tagged=False, fk="models.mname"),
                String(name="exgmnameb", tagged=False, fk="models.mname"),
            ),
        },
    )

    def _nam(name, ftype):
        packages = _list_block(
            "packages",
            String(name="ftype", tagged=False),
            File(
                name="fname",
                tagged=False,
                direction="in",
                mode_keyword=False,
                component="package",
                component_ftype="ftype",
            ),
            String(name="pname", tagged=False, pk=True, optional=True),
        )
        return Model(name=name, parent="sim-nam", ftype=ftype, blocks={"packages": packages})

    mvr_file = Record(
        name="mvr_filerecord",
        optional=True,
        fields={
            "mvr6": Keyword(name="mvr6"),
            "filein": Keyword(name="filein"),
            "mvr6_filename": File(
                name="mvr6_filename",
                tagged=False,
                direction="in",
                component="gwf-mvr",
                args={"model1": "model1", "model2": "model2"},
            ),
        },
    )
    exg = Package(
        name="exg-gwfgwf",
        parent="sim-nam",
        subtype="exchange",
        ftype="GWF6-GWF6",
        params=_MODELS,
        blocks={"options": Block(name="options", fields={"mvr_filerecord": mvr_file})},
    )
    return {"sim-nam": sim, "gwf-nam": _nam("gwf-nam", "GWF6"), "exg-gwfgwf": exg}, _nam


def _mover_pkgs(lak_keys=None, wel_keys=None, wel_options=("mover",)):
    """A LAK with outlets and lakes and a WEL with a `maxbound`, each
    declaring the mover key sets."""
    lak = Package(
        name="gwf-lak",
        parent="gwf-nam",
        ftype="LAK6",
        subtype="advanced",
        blocks={
            "options": _options("mover"),
            "packagedata": _list_block("packagedata", Integer(name="ifno", index=True, pk=True)),
            "outlets": _list_block("outlets", Integer(name="outletno", index=True, pk=True)),
        },
        keys=lak_keys
        if lak_keys is not None
        else {
            "mover_provider": KeySet(path="outlets.outletno"),
            "mover_receiver": KeySet(path="packagedata.ifno"),
        },
    )
    wel = Package(
        name="gwf-wel",
        parent="gwf-nam",
        ftype="WEL6",
        subtype="stress",
        dims={"maxbound": InputDim(value="maxbound")},
        blocks={
            "options": _options(*wel_options),
            "dimensions": Block(name="dimensions", fields={"maxbound": Integer(name="maxbound")}),
        },
        keys=wel_keys
        if wel_keys is not None
        else {
            "mover_provider": KeySet(path="<=maxbound"),
            "bound": KeySet(path="<=maxbound"),
        },
    )
    return {"gwf-lak": lak, "gwf-wel": wel}


_MNAME_FK = {"param": ["model1", "model2"]}

# A mover's models, passed down from the exchange that binds it.
_FORWARD = _MODELS


_PNAME_FK = {"path": "gwf-nam.packages.pname", "scope": "mname", "rule": "mover_enabled"}


def _ctx_mvr(mname_fk=_MNAME_FK, id1_fk=None, id2_fk=None, pname_fk=_PNAME_FK, **pkgs):
    """`_ctx_sim` plus a mover, in a model or the GWF-GWF exchange, whose
    rows name one of the exchange's models, then a package in it, then a
    feature of that package by the role it plays."""
    packages = _list_block(
        "packages",
        String(name="mname", tagged=False, when="modelnames", fk=mname_fk),
        String(
            name="pname",
            tagged=False,
            pk={"scope": "mname"},
            fk=pname_fk,
        ),
    )
    period = _list_block(
        "period",
        String(name="mname1", tagged=False, when="modelnames", fk=mname_fk),
        String(name="pname1", tagged=False, fk={"path": "packages.pname", "scope": "mname1"}),
        Integer(
            name="id1",
            tagged=False,
            index=True,
            fk=id1_fk or {"scope": "pname1", "key": "mover_provider"},
        ),
        String(name="mname2", tagged=False, when="modelnames", fk=mname_fk),
        String(name="pname2", tagged=False, fk={"path": "packages.pname", "scope": "mname2"}),
        Integer(
            name="id2",
            tagged=False,
            index=True,
            fk=id2_fk or {"scope": "pname2", "key": "mover_receiver"},
        ),
        list_name="stress_period_data",
    )
    mvr = Package(
        name="gwf-mvr",
        parent=["exg-gwfgwf", "gwf-nam"],
        ftype="MVR6",
        blocks={"options": _options("modelnames"), "packages": packages, "period": period},
        params=_FORWARD,
    )
    return {**_ctx_sim()[0], "gwf-mvr": mvr, **(pkgs or _mover_pkgs())}


def test_dfns_validate_mover_keys():
    spec = Dfns(components=_ctx_mvr())
    period = spec.components["gwf-mvr"].blocks["period"].fields["stress_period_data"]
    assert period.item.fields["id1"].fk == ForeignKey(scope="pname1", key="mover_provider")
    assert period.item.fields["mname1"].fk.params == ("model1", "model2")
    assert spec.components["gwf-wel"].keys["mover_provider"].bound == "maxbound"


def test_dfns_validate_rule_with_scope():
    """A scope picks the instance and a rule narrows its values: MVR's
    `packages.pname` names a package of the row's model with MOVER on."""
    spec = Dfns(components=_ctx_mvr())
    item = spec.components["gwf-mvr"].blocks["packages"].fields["packages"].item
    assert item.fields["pname"].fk == ForeignKey(**_PNAME_FK)
    assert item.fields["pname"].model_dump(exclude_none=True)["fk"] == _PNAME_FK


def test_dfns_validate_rule_with_scope_checks_scope():
    """With a rule, the scope is still checked like any scope."""
    bad = {**_PNAME_FK, "scope": "pname"}
    with pytest.raises(ValueError, match="pk and fk scopes differ"):
        Dfns(components=_ctx_mvr(pname_fk=bad))


def test_dfns_validate_rule_fk_path_checked():
    bad = {**_PNAME_FK, "path": "gwf-nam.packages.nope"}
    with pytest.raises(ValueError, match="'nope' is not the pk of list 'packages'"):
        Dfns(components=_ctx_mvr(pname_fk=bad))


def test_dfns_validate_key_undeclared():
    with pytest.raises(ValueError, match="declares key 'mover_nope'"):
        Dfns(components=_ctx_mvr(id1_fk={"scope": "pname1", "key": "mover_nope"}))


def test_dfns_validate_key_scope_names_no_package():
    # mname1 names a model, which declares no mover keys
    with pytest.raises(ValueError, match="declares key 'mover_provider'"):
        Dfns(components=_ctx_mvr(id1_fk={"scope": "mname1", "key": "mover_provider"}))


def test_dfns_validate_key_bound_needs_index():
    ctx = _ctx_mvr()
    period = ctx["gwf-mvr"].blocks["period"].fields["stress_period_data"]
    id1 = period.item.fields["id1"].model_copy(update={"index": False})
    item = period.item.model_copy(update={"fields": {**period.item.fields, "id1": id1}})
    lst = period.model_copy(update={"item": item})
    block = ctx["gwf-mvr"].blocks["period"].model_copy(update={"fields": {lst.name: lst}})
    ctx["gwf-mvr"] = ctx["gwf-mvr"].model_copy(
        update={"blocks": {**ctx["gwf-mvr"].blocks, "period": block}}
    )
    with pytest.raises(ValueError, match="a '<=dim' key needs an integer index column"):
        Dfns(components=ctx)


@pytest.mark.parametrize(
    "keyset, match",
    [
        (KeySet(path="nope.ifno"), "'nope' is not a list block"),
        (KeySet(path="outlets.nope"), "'nope' is not the pk of list"),
        (KeySet(path="<=nodim"), "names no dimension of gwf-lak"),
    ],
)
def test_dfns_validate_keyset_bad(keyset, match):
    pkgs = _mover_pkgs(lak_keys={"mover_provider": keyset})
    with pytest.raises(ValueError, match=match):
        Dfns(components=_ctx_mvr(**pkgs))


def test_dfns_validate_keyset_when():
    """A key set's `when` names a keyword option, as a field's does."""
    pkgs = _mover_pkgs(
        wel_keys={"mover_provider": KeySet(path="<=maxbound", when="mover")},
    )
    Dfns(components=_ctx_mvr(**pkgs))
    pkgs = _mover_pkgs(
        wel_keys={"mover_provider": KeySet(path="<=maxbound", when="nope")},
    )
    with pytest.raises(ValueError, match="when='nope' names no keyword option"):
        Dfns(components=_ctx_mvr(**pkgs))


def test_dfns_validate_keyset_scoped_pk_rejected():
    pkgs = _mover_pkgs()
    lak = pkgs["gwf-lak"]
    outlets = _list_block(
        "outlets",
        Integer(name="lakeno", index=True),
        Integer(name="outletno", index=True, pk={"scope": "lakeno"}),
    )
    pkgs["gwf-lak"] = lak.model_copy(update={"blocks": {**lak.blocks, "outlets": outlets}})
    with pytest.raises(ValueError, match="the pk is scoped"):
        Dfns(components=_ctx_mvr(**pkgs))


_SOURCE = {"source": KeySet(path=["sources.pname", "fileinput.pname"])}


def _ctx_transport(spc_key="bound", ssm_keys=_SOURCE, srctype=None):
    """`_ctx_sim` plus an SSM naming packages of its flow model, and an SPC
    under SSM naming a bound of the flow package its SSM row names, both by
    named rules."""
    pname_fk = {"path": "gwf-nam.packages.pname", "rule": "flow_model"}
    ssm = Package(
        name="gwt-ssm",
        parent="gwt-nam",
        ftype="SSM6",
        keys=ssm_keys,
        blocks={
            "sources": _list_block(
                "sources",
                String(name="pname", tagged=False, pk=True, fk=pname_fk),
                srctype or String(name="srctype", tagged=False),
            ),
            "fileinput": _list_block(
                "fileinput",
                String(name="pname", tagged=False, pk=True, fk=pname_fk),
                Keyword(name="spc6"),
                File(
                    name="spc6_filename",
                    tagged=False,
                    direction="in",
                    component="utl-spc",
                    args={"target": "pname"},
                ),
            ),
        },
    )
    spc = Package(
        name="utl-spc",
        parent="gwt-ssm",
        subtype="utility",
        ftype="SPC6",
        params={"target": Param(type="package", rule="no_advanced_transport")},
        blocks={
            "period": _list_block(
                "period",
                Integer(
                    name="bndno",
                    tagged=False,
                    index=True,
                    pk=True,
                    fk={"key": spc_key, "param": "target"},
                ),
                Double(name="concentration", tagged=False),
                list_name="stress_period_data",
            )
        },
    )
    return {
        **_ctx_mvr(),
        "gwt-nam": _ctx_sim()[1]("gwt-nam", "GWT6"),
        "gwt-ssm": ssm,
        "utl-spc": spc,
    }


def test_dfns_validate_ssm_and_spc_rules():
    spec = Dfns(components=_ctx_transport())
    item = spec.components["gwt-ssm"].blocks["fileinput"].fields["fileinput"].item
    assert item.fields["pname"].fk.rule == "flow_model"
    period = spec.components["utl-spc"].blocks["period"].fields["stress_period_data"]
    assert period.item.fields["bndno"].fk == ForeignKey(key="bound", param="target")


# Binding parameters (`params`, see `Param`): what a component needs from
# whatever binds it, named by an fk's `param`, a cellid's `model` or a `when`.


def _with_params(ctx, name, **params):
    """`ctx` with component `name`'s parameters replaced or added."""
    component = ctx[name]
    merged = {**(component.params or {}), **params}
    return {**ctx, name: component.model_copy(update={"params": merged})}


def _with_args(ctx, name, block, field, args):
    """`ctx` with the args of component `name`'s File `field` replaced."""
    blocks = _replace_named(
        name,
        ctx[name].blocks,
        block,
        lambda f, _: f.model_copy(update={"args": args}),
        {field},
    )
    return {**ctx, name: ctx[name].model_copy(update={"blocks": blocks})}


def test_param_loads_and_dumps():
    toml = {"type": ["gwf-rcha", "gwf-evta"], "rule": "no_advanced_transport"}
    pkg = Package.model_validate({"name": "utl-spca", "params": {"target": toml}})
    assert pkg.params["target"] == Param(
        type=["gwf-rcha", "gwf-evta"], rule="no_advanced_transport"
    )
    assert pkg.model_dump(exclude_none=True)["params"] == {"target": toml}


def test_param_rule_checked():
    with pytest.raises(ValueError, match="parameter rule 'nope' is not one of"):
        Param(type="package", rule="nope")


def test_param_name_checked():
    with pytest.raises(ValueError, match="parameter name 'a-b' must be an identifier"):
        Package(name="x", params={"a-b": Param(type="model")})


@pytest.mark.parametrize("args", [{"a": "b.c"}, {"a.b": "c"}, {"a": ""}])
def test_file_args_checked(args):
    with pytest.raises(ValueError, match="must name a column or parameter"):
        File(name="f", direction="in", component="x", args=args)


def test_dfns_validate_args():
    """An exchange's models are passed from its `sim-nam` row, a mover's from
    the exchange's own, and SPC's target from SSM's row. A mover under a
    model gets none."""
    spec = Dfns(components=_ctx_transport())
    assert spec.components["exg-gwfgwf"].params == _MODELS
    item = spec.components["gwt-ssm"].blocks["fileinput"].fields["fileinput"].item
    assert item.fields["spc6_filename"].args == {"target": "pname"}


_EXG = ("sim-nam", "exchanges", "exgfile")
_MVR = ("exg-gwfgwf", "options", "mvr6_filename")


@pytest.mark.parametrize(
    "where, args, match",
    [
        (
            _EXG,
            {"model1": "nope"},
            "arg model1='nope' must name exactly one of a sibling column and a parameter "
            "of sim-nam",
        ),
        (_EXG, {"model1": "exgtype"}, "arg model1='exgtype': the column has no fk to follow"),
        (_EXG, {"model3": "exgmnamea"}, "passes 'model3', which exg-gwfgwf doesn't declare"),
        (_MVR, {"model1": "model3"}, "must name exactly one of a sibling column"),
        (_MVR, {"model3": "model1"}, "passes 'model3', which gwf-mvr doesn't declare"),
    ],
)
def test_dfns_validate_args_bad(where, args, match):
    with pytest.raises(ValueError, match=match):
        Dfns(components=_with_args(_ctx_transport(), *where, args))


@pytest.mark.parametrize(
    "param, match",
    [
        (Param(type="package"), "names nothing of type 'package'"),
        (Param(type="nope-nam"), "admits no component"),
    ],
)
def test_dfns_validate_params_bad(param, match):
    with pytest.raises(ValueError, match=match):
        Dfns(components=_with_params(_ctx_transport(), "exg-gwfgwf", model1=param))


def test_dfns_validate_fk_param_undeclared():
    ctx = _with_args(_ctx_transport(), *_MVR, None)
    ctx["gwf-mvr"] = ctx["gwf-mvr"].model_copy(update={"params": None})
    with pytest.raises(ValueError, match="fk param='model1': gwf-mvr declares no such parameter"):
        Dfns(components=ctx)


def test_dfns_validate_fk_param_only_names_from_a_string():
    with pytest.raises(ValueError, match="only a string column may name a parameter's instance"):
        Dfns(components=_ctx_mvr(id1_fk={"param": "model1"}))


def _mvr_with_modelnames(**attrs):
    ctx = _ctx_mvr()
    mvr = ctx["gwf-mvr"]
    options = Block(name="options", fields={"modelnames": Keyword(name="modelnames", **attrs)})
    ctx["gwf-mvr"] = mvr.model_copy(update={"blocks": {**mvr.blocks, "options": options}})
    return ctx


def test_dfns_validate_when_names_param():
    """`MODELNAMES` is set exactly when the mover's `model2` is: when an
    exchange binds it."""
    spec = Dfns(components=_mvr_with_modelnames(when="model2"))
    assert spec.components["gwf-mvr"].blocks["options"].fields["modelnames"].when == "model2"


@pytest.mark.parametrize(
    "when, match",
    [
        ("model3", "when='model3' names no keyword option or parameter of gwf-mvr"),
        ("modelnames", "when='modelnames' names the field itself"),
    ],
)
def test_dfns_validate_when_names_param_bad(when, match):
    with pytest.raises(ValueError, match=match):
        Dfns(components=_mvr_with_modelnames(when=when))


def test_dfns_validate_multi_path_keyset():
    spec = Dfns(components=_ctx_transport())
    assert spec.components["gwt-ssm"].keys["source"].paths == ("sources.pname", "fileinput.pname")


@pytest.mark.parametrize(
    "keys, match",
    [
        ({"source": KeySet(path=["sources.pname", "nope.pname"])}, "'nope' is not a list block"),
        ({"source": KeySet(path=["sources.srctype", "fileinput.pname"])}, "not the pk of list"),
    ],
)
def test_dfns_validate_multi_path_keyset_bad(keys, match):
    with pytest.raises(ValueError, match=match):
        Dfns(components=_ctx_transport(ssm_keys=keys))


def test_dfns_validate_multi_path_keyset_types_differ():
    keys = {"source": KeySet(path=["sources.srctype", "fileinput.pname"])}
    srctype = Integer(name="srctype", tagged=False, index=True, pk=True)
    with pytest.raises(ValueError, match="name columns of different types"):
        Dfns(components=_ctx_transport(ssm_keys=keys, srctype=srctype))


def test_dfns_validate_rule_key_undeclared():
    with pytest.raises(ValueError, match="no component the parameter 'target' can name declares"):
        Dfns(components=_ctx_transport(spc_key="nope"))
