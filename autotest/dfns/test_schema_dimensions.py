"""Tests for DFN schema array shape expressions and dimension resolution"""

import ast
from collections import ChainMap

import pytest

from autotest.dfns.test_schema import _DEV3_SNAPSHOT_DIR, _pkg
from modflow_devtools.dfns.schema import (
    Array,
    Block,
    Dfns,
    Double,
    InputDim,
    Integer,
    List,
    Model,
    Package,
    Record,
    RuntimeDim,
    String,
    _names_in_expr,
    _parse_shape_element,
    _resolve_derived_dims,
    _ShapeRef,
    _validate_len_call,
    _validate_list_shape_element,
    _validate_shape_element,
    _validate_sum_call,
    dim_input,
    dim_value,
    split_bound,
)


def test_names_in_expr_simple_arithmetic():
    assert _names_in_expr("nlay * nrow * ncol") == {"nlay", "nrow", "ncol"}


def test_names_in_expr_single_name():
    assert _names_in_expr("nodes") == {"nodes"}


def test_names_in_expr_excludes_sum_internals():
    names = _names_in_expr("sum(packagedata.nlakeconn)")
    assert "packagedata" not in names
    assert "nlakeconn" not in names


def test_names_in_expr_mixed_sum_and_arithmetic():
    names = _names_in_expr("nlay * nrow + sum(packagedata.nlakeconn)")
    assert names == {"nlay", "nrow"}


def test_names_in_expr_excludes_sum_func_name_itself():
    names = _names_in_expr("sum(list.col)")
    assert "sum" not in names


def test_names_in_expr_excludes_builtin_func_name():
    assert _names_in_expr("abs(nlay)") == {"nlay"}
    assert _names_in_expr("min(nlay, ncol)") == {"nlay", "ncol"}
    assert _names_in_expr("round(nlay)") == {"nlay"}


def test_names_in_expr_excludes_qualified_func_name():
    # math.floor(nlay): 'math' is a Name inside the Attribute func, not a dim ref
    assert _names_in_expr("math.floor(nlay)") == {"nlay"}
    assert _names_in_expr("math.ceil(nrow * 2)") == {"nrow"}


def test_names_in_expr_invalid_syntax():
    with pytest.raises(ValueError, match="Invalid expression"):
        _names_in_expr("nlay * (")


def test_shape_expr_cyclic_resolution():
    pkg = Package(
        name="bad",
        blocks=None,
        dims={
            "a": InputDim(value="b + 1", scope="component"),
            "b": InputDim(value="a + 1", scope="component"),
        },
    )
    with pytest.raises(ValueError, match="Cycle in"):
        Dfns(components={"bad": pkg})


def test_shape_expr_unknown_operand():
    pkg = Package(
        name="bad",
        blocks=None,
        dims={"nodes": InputDim(value="ghost_dim * 2", scope="component")},
    )
    with pytest.raises(ValueError, match="not a known dimension"):
        Dfns(components={"bad": pkg})


def _pkg_with_list(list_field_name: str, col_name: str, col_type=None) -> Package:
    col = (col_type or Integer)(name=col_name)
    item = Record(name="item", fields={col_name: col})
    lst = List(name=list_field_name, item=item)
    block = Block(name=list_field_name, fields={list_field_name: lst})
    return _pkg("test", blocks={list_field_name: block})


def test_resolve_derived_dims_sum_expr():
    pkg = _pkg_with_list("packagedata", "nlakeconn")
    pkg = Package(
        name="test",
        blocks=pkg.blocks,
        dims={"total_conn": InputDim(value="sum(packagedata.nlakeconn)", scope="component")},
    )
    order = _resolve_derived_dims(pkg, set())
    assert order == ["total_conn"]


def test_resolve_derived_dims_no_derived_returns_empty():
    pkg = Package(name="test", blocks=None, dims=None)
    assert _resolve_derived_dims(pkg, set()) == []


def test_resolve_derived_dims_cycle_error():
    pkg = Package(
        name="test",
        blocks=None,
        dims={
            "a": InputDim(value="b + 1", scope="component"),
            "b": InputDim(value="a + 1", scope="component"),
        },
    )
    with pytest.raises(ValueError, match="Cycle in"):
        _resolve_derived_dims(pkg, set())


def test_resolve_derived_dims_unknown_operand_error():
    pkg = Package(
        name="test",
        blocks=None,
        dims={"nodes": InputDim(value="mystery_dim * 2", scope="component")},
    )
    with pytest.raises(ValueError, match="not a known dimension"):
        _resolve_derived_dims(pkg, set())


def test_resolve_derived_dims_invalid_expression_error():
    pkg = Package(
        name="test",
        blocks=None,
        dims={"nodes": InputDim(value="nlay * (", scope="component")},
    )
    with pytest.raises(ValueError, match="Invalid"):
        _resolve_derived_dims(pkg, set())


def _make_sum_call(expr: str):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError("No Call node found")


def test_validate_sum_expr():
    pkg = _pkg_with_list("packagedata", "nlakeconn")
    call = _make_sum_call("sum(packagedata.nlakeconn)")
    _validate_sum_call(call, pkg, "sum(packagedata.nlakeconn)")

    # fully qualified
    pkg = _pkg_with_list("packagedata", "nlakeconn")
    call = _make_sum_call("sum(packagedata.packagedata.nlakeconn)")
    _validate_sum_call(call, pkg, "sum(packagedata.packagedata.nlakeconn)")

    # unrecognized
    pkg = _pkg("test", blocks=None)
    call = _make_sum_call("sum(nolist.col)")
    with pytest.raises(ValueError, match="unknown list field"):
        _validate_sum_call(call, pkg, "sum(nolist.col)")

    pkg = _pkg_with_list("packagedata", "nlakeconn")
    call = _make_sum_call("sum(wrongblock.packagedata.nlakeconn)")
    with pytest.raises(ValueError, match="block qualifier"):
        _validate_sum_call(call, pkg, "sum(wrongblock.packagedata.nlakeconn)")

    pkg = _pkg_with_list("packagedata", "name", col_type=String)
    call = _make_sum_call("sum(packagedata.name)")
    with pytest.raises(ValueError, match="must be Integer"):
        _validate_sum_call(call, pkg, "sum(packagedata.name)")

    pkg = _pkg_with_list("packagedata", "nlakeconn")
    call = _make_sum_call("sum(packagedata.nosuchcol)")
    with pytest.raises(ValueError, match="not found"):
        _validate_sum_call(call, pkg, "sum(packagedata.nosuchcol)")


def _make_len_call(expr: str):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError("No Call node found")


def test_validate_len_call():
    arr = Array(name="auxiliary", dtype="string", shape=[])
    block = Block(name="options", fields={"auxiliary": arr})
    pkg = Package(name="test", blocks={"options": block})

    call = _make_len_call("len(auxiliary)")
    _validate_len_call(call, pkg, "len(auxiliary)")  # no error

    # too many arguments
    with pytest.raises(ValueError, match="exactly one argument"):
        bad = ast.parse("len(a, b)", mode="eval").body  # type: ignore[attr-defined]
        _validate_len_call(bad, pkg, "len(a, b)")

    # non-name argument
    with pytest.raises(ValueError, match="field name"):
        bad = ast.parse("len(a.b)", mode="eval").body  # type: ignore[attr-defined]
        _validate_len_call(bad, pkg, "len(a.b)")


def test_names_in_expr_excludes_len_internals():
    assert _names_in_expr("len(auxiliary)") == set()


def test_names_in_expr_len_and_arithmetic():
    assert _names_in_expr("len(auxiliary) + nlay") == {"nlay"}


def test_dim_value_len_form():
    arr = Array(name="auxiliary", dtype="string", shape=[])
    block = Block(name="options", fields={"auxiliary": arr})
    pkg = Package(
        name="test",
        blocks={"options": block},
        dims={"auxiliary": InputDim(value="len(auxiliary)", scope="component")},
    )
    Dfns(components={"test": pkg})  # no error


def test_dim_value_integer_field_not_found():
    pkg = Package(
        name="test",
        blocks=None,
        dims={"nlay": InputDim(value="nlay", scope="component")},
    )
    with pytest.raises(ValueError, match="not found in component"):
        Dfns(components={"test": pkg})


def test_dim_value_array_field_requires_len():
    arr = Array(name="auxiliary", dtype="string", shape=[])
    block = Block(name="options", fields={"auxiliary": arr})
    pkg = Package(
        name="test",
        blocks={"options": block},
        dims={"auxiliary": InputDim(value="auxiliary", scope="component")},
    )
    with pytest.raises(ValueError, match="use len\\(auxiliary\\)"):
        Dfns(components={"test": pkg})


def _dim_block(*names: str) -> Block:
    return Block(
        name="dimensions",
        fields={n: Integer(name=n) for n in names},
    )


def _make_shape_validation_ctx(dim_names: set[str], derived: dict | None = None):
    """Return (array, component, known_dims) for shape element tests."""
    dims: dict[str, InputDim] = {n: InputDim(value=n, scope="component") for n in dim_names}
    if derived:
        dims.update({n: InputDim(value=e, scope="component") for n, e in derived.items()})
    blocks = {"dimensions": _dim_block(*dim_names)} if dim_names else None
    pkg = Package(name="test", blocks=blocks, dims=dims or None)
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "test": pkg})
    known = spec.dims("test")
    arr = Array(name="arr", dtype="double", shape=[])
    return arr, pkg, known


def test_validate_shape_element_explicit_dim():
    arr, pkg, known = _make_shape_validation_ctx({"nlay", "nrow", "ncol"})
    _validate_shape_element("nlay", arr, pkg, None, known)  # no error


def test_validate_shape_element_inherited_dim():
    """A dim declared in a sibling component (model-scoped) is valid."""
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks=None,
        dims={"nodes": InputDim(value="42", scope="model")},
    )
    test_pkg = Package(name="gwf-test", parent="gwf-nam", blocks=None)
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis, "gwf-test": test_pkg})
    known = spec.dims("gwf-test")
    arr = Array(name="arr", dtype="double", shape=[])
    _validate_shape_element("nodes", arr, test_pkg, None, known)


def test_validate_shape_element_derived_dim():
    arr, pkg, known = _make_shape_validation_ctx(
        {"nlay", "nrow", "ncol"}, derived={"nodes": "nlay * nrow * ncol"}
    )
    _validate_shape_element("nodes", arr, pkg, None, known)


def test_validate_shape_element_unknown_dim():
    arr, pkg, known = _make_shape_validation_ctx({"nlay"})
    with pytest.raises(ValueError, match="does not resolve"):
        _validate_shape_element("mystery", arr, pkg, None, known)


def test_validate_shape_element_invalid_syntax():
    arr, pkg, known = _make_shape_validation_ctx({"nlay"})
    with pytest.raises(ValueError, match="invalid shape element"):
        _validate_shape_element("123bad", arr, pkg, None, known)


def test_validate_shape_element_empty_string():
    arr, pkg, known = _make_shape_validation_ctx({"nlay"})
    with pytest.raises(ValueError, match="invalid shape element"):
        _validate_shape_element("", arr, pkg, None, known)


def test_top_level_array_empty_shape_valid():
    arr = Array(name="auxiliary", dtype="string", shape=[])
    block = Block(name="options", fields={"auxiliary": arr})
    pkg = Package(name="gwf-test", blocks={"options": block})
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})


def test_validate_shape_element_bound_lt():
    arr, pkg, known = _make_shape_validation_ctx({"nrow"})
    _validate_shape_element("<nrow", arr, pkg, None, known)


def test_validate_shape_element_bound_gt():
    arr, pkg, known = _make_shape_validation_ctx({"nrow"})
    _validate_shape_element(">nrow", arr, pkg, None, known)


def test_validate_shape_element_bound_lte():
    arr, pkg, known = _make_shape_validation_ctx({"ncol"})
    _validate_shape_element("<=ncol", arr, pkg, None, known)


def test_validate_shape_element_bound_gte():
    arr, pkg, known = _make_shape_validation_ctx({"ncol"})
    _validate_shape_element(">=ncol", arr, pkg, None, known)


def test_validate_shape_element_bound_unknown_dim():
    arr, pkg, known = _make_shape_validation_ctx({"nlay"})
    with pytest.raises(ValueError, match="does not resolve"):
        _validate_shape_element("<unknown_dim", arr, pkg, None, known)


@pytest.mark.parametrize(
    "element,expected",
    [
        ("nper", (None, "nper")),
        ("<nper", ("<", "nper")),
        ("<=nper", ("<=", "nper")),
        (">nper", (">", "nper")),
        (">= nper", (">=", "nper")),
        ("<=packagedata.ncon(ifno)", ("<=", "packagedata.ncon(ifno)")),
    ],
)
def test_split_bound(element, expected):
    assert split_bound(element) == expected


def test_validate_shape_element_bound_arithmetic():
    arr, pkg, known = _make_shape_validation_ctx({"ncol"})
    _validate_shape_element("<=ncol + 1", arr, pkg, None, known)


def test_validate_shape_element_bound_derived_dim():
    arr, pkg, known = _make_shape_validation_ctx({"nrow", "ncol"}, derived={"ncpl": "nrow * ncol"})
    _validate_shape_element("<=ncpl", arr, pkg, None, known)


def test_validate_shape_element_bound_invalid_expression():
    arr, pkg, known = _make_shape_validation_ctx({"nrow"})
    with pytest.raises(ValueError, match="invalid shape element"):
        _validate_shape_element("<=nrow * 2", arr, pkg, None, known)


def test_validate_shape_element_bound_repeated_operator():
    arr, pkg, known = _make_shape_validation_ctx({"nrow"})
    with pytest.raises(ValueError, match="at most one bound operator"):
        _validate_shape_element("<=<nrow", arr, pkg, None, known)


@pytest.mark.parametrize("element", ["maxbound", "<maxbound", "<=maxbound", ">=maxbound"])
def test_validate_list_shape_element_bound(element):
    lst = List(name="stress_period_data", item=Record(name="item", fields={}))
    _validate_list_shape_element(element, lst, {"maxbound"})


def test_validate_list_shape_element_bound_arithmetic():
    lst = List(name="stress_period_data", item=Record(name="item", fields={}))
    _validate_list_shape_element(">=maxbound - 1", lst, {"maxbound"})


def test_validate_list_shape_element_bound_unknown_dim():
    lst = List(name="stress_period_data", item=Record(name="item", fields={}))
    with pytest.raises(ValueError, match="does not resolve"):
        _validate_list_shape_element("<=nope", lst, {"maxbound"})


def test_validate_list_shape_element_bound_repeated_operator():
    lst = List(name="stress_period_data", item=Record(name="item", fields={}))
    with pytest.raises(ValueError, match="at most one bound operator"):
        _validate_list_shape_element("<<=maxbound", lst, {"maxbound"})


def _lookup_ctx():
    """
    Returns (array, enclosing_record, component, known_dims) for a valid
    row-level lookup scenario mirroring the gwf-lak period table.

    packagedata block has a List with item Record(lakeno pk, nlakeconn int).
    The array lives inside a Record with sibling lakeno(fk='packagedata').
    """
    nlakeconn = Integer(name="nlakeconn")
    lakeno_pk = Integer(name="lakeno", pk=True)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_pk, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})

    fk_lakeno = Integer(name="lakeno", fk="packagedata")
    arr = Array(name="outflow", dtype="double", shape=[])
    enc_record = Record(name="item", fields={"lakeno": fk_lakeno, "outflow": arr})

    lak = Package(
        name="gwf-lak",
        parent="gwf-nam",
        blocks={"packagedata": pkg_block},
    )
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    known = spec.dims("gwf-lak")
    return arr, enc_record, lak, known


def test_validate_shape_element_row_level_lookup():
    arr, enc, pkg, known = _lookup_ctx()
    _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, pkg, enc, known)


def test_validate_shape_element_bound_row_level_lookup():
    arr, enc, pkg, known = _lookup_ctx()
    _validate_shape_element("<=packagedata.nlakeconn(lakeno)", arr, pkg, enc, known)


def test_validate_shape_element_on_top_level_array():
    arr, _enc, pkg, known = _lookup_ctx()
    with pytest.raises(ValueError, match="not inside a record"):
        _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, pkg, None, known)


def test_validate_shape_element_unknown_list_block():
    arr, enc, pkg, known = _lookup_ctx()
    with pytest.raises(ValueError, match="not a list block"):
        _validate_shape_element("noblock.nlakeconn(lakeno)", arr, pkg, enc, known)


def test_validate_shape_element_unknown_column():
    arr, enc, pkg, known = _lookup_ctx()
    with pytest.raises(ValueError, match="is not a field"):
        _validate_shape_element("packagedata.nocol(lakeno)", arr, pkg, enc, known)


def test_validate_shape_element_non_integer_column():
    nlakeconn = String(name="nlakeconn")
    lakeno_pk = Integer(name="lakeno", pk=True)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_pk, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})
    fk_lakeno = Integer(name="lakeno", fk="packagedata")
    arr = Array(name="outflow", dtype="double", shape=[])
    enc = Record(name="item", fields={"lakeno": fk_lakeno, "outflow": arr})
    lak = Package(name="gwf-lak", parent="gwf-nam", blocks={"packagedata": pkg_block})
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    known = spec.dims("gwf-lak")
    with pytest.raises(ValueError, match="must be Integer"):
        _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, lak, enc, known)


def test_validate_shape_element_missing_fk_sibling():
    arr, enc, pkg, known = _lookup_ctx()
    with pytest.raises(ValueError, match="not a sibling field"):
        _validate_shape_element("packagedata.nlakeconn(nosuchfield)", arr, pkg, enc, known)


def test_validate_shape_element_fk_not_set():
    nlakeconn = Integer(name="nlakeconn")
    lakeno_pk = Integer(name="lakeno", pk=True)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_pk, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})
    no_fk_lakeno = Integer(name="lakeno")  # fk=None
    arr = Array(name="outflow", dtype="double", shape=[])
    enc = Record(name="item", fields={"lakeno": no_fk_lakeno, "outflow": arr})
    lak = Package(name="gwf-lak", parent="gwf-nam", blocks={"packagedata": pkg_block})
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    known = spec.dims("gwf-lak")
    with pytest.raises(ValueError, match=r"\.fk is not set"):
        _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, lak, enc, known)


def test_validate_shape_element_fk_block_mismatch():
    nlakeconn = Integer(name="nlakeconn")
    lakeno_pk = Integer(name="lakeno", pk=True)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_pk, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})
    fk_lakeno = Integer(name="lakeno", fk="otherblock")  # fk → wrong block
    arr = Array(name="outflow", dtype="double", shape=[])
    enc = Record(name="item", fields={"lakeno": fk_lakeno, "outflow": arr})
    lak = Package(name="gwf-lak", parent="gwf-nam", blocks={"packagedata": pkg_block})
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    known = spec.dims("gwf-lak")
    with pytest.raises(ValueError, match="does not reference block"):
        _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, lak, enc, known)


@pytest.mark.parametrize(
    "element,expected",
    [
        ("nvert", _ShapeRef("dim", "nvert")),
        ("nseg-1", _ShapeRef("dim", "nseg", offset=-1)),
        ("ncol + 1", _ShapeRef("dim", "ncol", offset=1)),
        ("<=maxats", _ShapeRef("dim", "maxats", bound="<=")),
        (">= nper", _ShapeRef("dim", "nper", bound=">=")),
        ("<ncol - 2", _ShapeRef("dim", "ncol", offset=-2, bound="<")),
        (
            "packagedata.ncon(ifno)",
            _ShapeRef("lookup", "ncon", block="packagedata", fk_field="ifno"),
        ),
        (
            "gwf-x.block.col(fk)",
            _ShapeRef("lookup", "col", component="gwf-x", block="block", fk_field="fk"),
        ),
        (
            "<=packagedata.ncon(ifno)",
            _ShapeRef("lookup", "ncon", bound="<=", block="packagedata", fk_field="ifno"),
        ),
    ],
)
def test_parse_shape_element(element, expected):
    assert _parse_shape_element(element) == expected


@pytest.mark.parametrize(
    "element,match",
    [
        ("", "invalid shape element"),
        ("123bad", "invalid shape element"),
        ("nrow * 2", "invalid shape element"),
        ("<=nrow * 2", "invalid shape element"),
        ("len(auxiliary)", "invalid shape element"),
        ("packagedata.ncon", "invalid shape element"),
        ("<=<nrow", "at most one bound operator"),
    ],
)
def test_parse_shape_element_invalid(element, match):
    with pytest.raises(ValueError, match=match):
        _parse_shape_element(element)


def test_parse_shape_element_sibling():
    ncvert = Integer(name="ncvert")
    arr = Array(name="icvert", dtype="integer", shape=["ncvert"])
    enc = Record(name="item", fields={"ncvert": ncvert, "icvert": arr})
    assert _parse_shape_element("ncvert", enc) == _ShapeRef("sibling", "ncvert")
    assert _parse_shape_element("ncvert") == _ShapeRef("dim", "ncvert")
    assert _parse_shape_element("nvert", enc) == _ShapeRef("dim", "nvert")


def test_parse_shape_element_non_integer_not_sibling():
    arr = Array(name="vals", dtype="double", shape=["n"])
    enc = Record(name="item", fields={"n": String(name="n"), "vals": arr})
    assert _parse_shape_element("n", enc).kind == "dim"


def test_validate_shape_element_sibling():
    arr = Array(name="icvert", dtype="integer", shape=[])
    enc = Record(name="item", fields={"ncvert": Integer(name="ncvert"), "icvert": arr})
    _validate_shape_element("ncvert", arr, _pkg("test"), enc, set())


def test_validate_shape_element_sibling_shadows_dim():
    arr = Array(name="icvert", dtype="integer", shape=[])
    enc = Record(name="item", fields={"ncvert": Integer(name="ncvert"), "icvert": arr})
    with pytest.raises(ValueError, match="both a dim and a sibling field"):
        _validate_shape_element("ncvert", arr, _pkg("test"), enc, {"ncvert"})


def _cross_component_lookup_ctx():
    """An array in another component sized by a column of gwf-lak's packagedata."""
    _arr, _enc, lak, _known = _lookup_ctx()
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})
    fk_lakeno = Integer(name="lakeno", fk="packagedata.lakeno")
    arr = Array(name="outflow", dtype="double", shape=[])
    enc = Record(name="item", fields={"lakeno": fk_lakeno, "outflow": arr})
    other = Package(name="gwf-other", parent="gwf-nam", blocks=None)
    return arr, enc, other, spec


def test_validate_shape_element_cross_component_lookup():
    arr, enc, other, spec = _cross_component_lookup_ctx()
    elem = "gwf-lak.packagedata.nlakeconn(lakeno)"
    _validate_shape_element(elem, arr, other, enc, set(), spec)


def test_validate_shape_element_cross_component_lookup_requires_spec():
    arr, enc, other, _spec = _cross_component_lookup_ctx()
    with pytest.raises(ValueError, match="requires a Dfns spec"):
        _validate_shape_element("gwf-lak.packagedata.nlakeconn(lakeno)", arr, other, enc, set())


def test_validate_shape_element_cross_component_lookup_unknown_component():
    arr, enc, other, spec = _cross_component_lookup_ctx()
    with pytest.raises(ValueError, match="not found in spec"):
        _validate_shape_element(
            "gwf-nope.packagedata.nlakeconn(lakeno)", arr, other, enc, set(), spec
        )


def test_validate_list_shape_element_lookup():
    lst = List(name="stress_period_data", item=Record(name="item", fields={}))
    with pytest.raises(ValueError, match="not inside a record"):
        _validate_list_shape_element("packagedata.ncon(ifno)", lst, {"maxbound"})


def test_local_dims():
    block = _dim_block("nlay", "nrow", "ncol")
    pkg = Package(
        name="gwf-dis",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    spec = Dfns(components={"gwf-dis": pkg})
    assert spec.local_dims("gwf-dis") == {"nlay", "nrow", "ncol"}

    # no dims section → empty
    pkg2 = Package(name="gwf-chd", blocks=None, dims=None)
    spec2 = Dfns(components={"gwf-chd": pkg2})
    assert spec2.local_dims("gwf-chd") == set()

    # derived dims included
    pkg3 = Package(
        name="test",
        blocks=None,
        dims={"nodes": InputDim(value="42", scope="component")},
    )
    spec3 = Dfns(components={"test": pkg3})
    assert spec3.local_dims("test") == {"nodes"}

    # runtime dims also included
    pkg4 = Package(
        name="test",
        blocks=None,
        runtime_dims={"nja": RuntimeDim(set_in="ar", scope="component")},
    )
    spec4 = Dfns(components={"test": pkg4})
    assert spec4.local_dims("test") == {"nja"}


def test_input_dims_excludes_runtime():
    # input_dims should include field-backed and derived dims but not runtime dims
    block = _dim_block("nlay", "nrow", "ncol")
    pkg = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
        runtime_dims={"nja": RuntimeDim(set_in="ar", scope="model")},
    )
    spec = Dfns(components={"gwf-dis": pkg})
    assert spec.input_dims("gwf-dis") == {"nlay", "nrow", "ncol", "nodes"}
    assert "nja" not in spec.input_dims("gwf-dis")
    assert "nja" in spec.dims("gwf-dis")

    # an Array whose shape references a runtime dim should fail validation
    runtime_shaped = Package(
        name="test",
        parent="gwf-nam",
        blocks={
            "data": Block(
                name="data",
                fields={
                    "vals": Array(name="vals", dtype="double", shape=["nja"]),
                },
            )
        },
        runtime_dims={"nja": RuntimeDim(set_in="ar", scope="component")},
    )
    with pytest.raises(ValueError, match="does not resolve to a known dim"):
        Dfns(components={"test": runtime_shaped})


def test_resolve_derived_dims():
    block = _dim_block("nlay", "nrow", "ncol")
    pkg = Package(
        name="test",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="component"),
            "nrow": InputDim(value="nrow", scope="component"),
            "ncol": InputDim(value="ncol", scope="component"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="component"),
        },
    )
    order = _resolve_derived_dims(pkg, {"nlay", "nrow", "ncol"})
    assert order[-1] == "nodes"  # nodes depends on the three field-backed dims

    pkg = Package(
        name="test",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="component"),
            "nrow": InputDim(value="nrow", scope="component"),
            "ncol": InputDim(value="ncol", scope="component"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="component"),
            "nodouble": InputDim(value="nodes * 2", scope="component"),
        },
    )
    order = _resolve_derived_dims(pkg, {"nlay", "nrow", "ncol"})
    assert order.index("nodes") < order.index("nodouble")

    pkg = Package(
        name="test",
        blocks=None,
        dims={"derived": InputDim(value="nodes + 1", scope="component")},
    )
    order = _resolve_derived_dims(pkg, {"nodes"})
    assert order == ["derived"]


def test_dim_validation():
    block = _dim_block("nlay", "nrow", "ncol")
    pkg = Package(
        name="gwf-dis",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    spec = Dfns(components={"gwf-dis": pkg})
    assert "gwf-dis" in spec.components


def test_local_dims_model_scoped():
    pkg = Package(name="gwf-chd", blocks=None, dims=None)
    spec = Dfns(components={"gwf-chd": pkg})
    assert spec.local_dims("gwf-chd") == set()

    block = _dim_block("nlay", "nrow", "ncol")
    pkg = Package(
        name="gwf-dis",
        blocks={"dimensions": block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    spec = Dfns(components={"gwf-dis": pkg})
    assert spec.local_dims("gwf-dis") == {"nlay", "nrow", "ncol"}


def test_inherited_dims():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    chd = _pkg("gwf-chd", parent="gwf-nam", blocks=None)
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis, "gwf-chd": chd})

    inherited = spec.inherited_dims("gwf-chd")
    assert "nlay" in inherited
    assert "nrow" in inherited
    assert "ncol" in inherited
    assert "nodes" in inherited  # derived dim from gwf-dis, model-scoped

    disv_block = _dim_block("nlay", "ncpl")
    disv = Package(
        name="gwf-disv",
        parent="gwf-nam",
        blocks={"dimensions": disv_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "ncpl": InputDim(value="ncpl", scope="model"),
        },
    )
    chd = _pkg("gwf-chd", parent="gwf-nam", blocks=None)
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-disv": disv, "gwf-chd": chd})

    inherited = spec.inherited_dims("gwf-chd")
    assert "nlay" in inherited
    assert "ncpl" in inherited

    disu_block = _dim_block("nodes", "nja")
    disu = Package(
        name="gwf-disu",
        parent="gwf-nam",
        blocks={"dimensions": disu_block},
        dims={
            "nodes": InputDim(value="nodes", scope="model"),
            "nja": InputDim(value="nja", scope="model"),
        },
    )
    chd = _pkg("gwf-chd", parent="gwf-nam", blocks=None)
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-disu": disu, "gwf-chd": chd})

    inherited = spec.inherited_dims("gwf-chd")
    assert "nodes" in inherited
    assert "nja" in inherited


def test_inherited_dims_excludes_own():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    chd = Package(
        name="gwf-chd",
        parent="gwf-nam",
        blocks={"dimensions": _dim_block("secret_dim")},
        dims={"secret_dim": InputDim(value="secret_dim", scope="model")},
    )
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis, "gwf-chd": chd})

    inherited = spec.inherited_dims("gwf-chd")
    assert "nlay" in inherited
    assert "secret_dim" not in inherited  # own dim: not in inherited_dims


def _dis_dfns() -> Dfns:
    dis_block = _dim_block("nlay", "nrow", "ncol")
    gwf = Model(name="gwf-nam", blocks=None)
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    return Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})


def test_dims_includes_own():
    spec = _dis_dfns()
    known = spec.dims("gwf-dis")
    assert {"nlay", "nrow", "ncol", "nodes"} <= known


def test_dims_includes_derived():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    gwf = Model(name="gwf-nam", blocks=None)
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})
    known = spec.dims("gwf-dis")
    assert "nodes" in known


def test_dims_includes_model_scoped():
    spec = _dis_dfns()
    chd = _pkg("gwf-chd", parent="gwf-nam")
    spec2 = Dfns(components=dict(spec.components) | {"gwf-chd": chd})
    known = spec2.dims("gwf-chd")
    assert "nodes" in known  # derived dim from gwf-dis, scope="model"
    assert "nlay" in known  # field-backed dim from gwf-dis, scope="model"


def test_top_level_array():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    arr = Array(name="botm", dtype="double", shape=["nlay", "nrow", "ncol"])
    grid_block = Block(name="griddata", fields={"botm": arr})
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block, "griddata": grid_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    gwf = Model(name="gwf-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})
    assert "gwf-dis" in spec.components


def test_array_in_record():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    arr = Array(name="vals", dtype="double", shape=["ncol"])
    rec = Record(name="myrec", fields={"vals": arr})
    opt_block = Block(name="options", fields={"myrec": rec})
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block, "options": opt_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})


def test_row_level_lookup_in_list_item():
    nlakeconn = Integer(name="nlakeconn")
    lakeno_pk = Integer(name="lakeno", pk=True)
    pkg_item = Record(name="item", fields={"lakeno": lakeno_pk, "nlakeconn": nlakeconn})
    pkg_list = List(name="packagedata", item=pkg_item)
    pkg_block = Block(name="packagedata", fields={"packagedata": pkg_list})

    fk_lakeno = Integer(name="lakeno", fk="packagedata")
    outflow = Array(name="outflow", dtype="double", shape=["packagedata.nlakeconn(lakeno)"])
    period_item = Record(name="item", fields={"lakeno": fk_lakeno, "outflow": outflow})
    period_list = List(name="period", item=period_item)
    period_block = Block(name="period", fields={"period": period_list})

    gwf = Model(name="gwf-nam", blocks=None)
    lak = Package(
        name="gwf-lak",
        parent="gwf-nam",
        blocks={"packagedata": pkg_block, "period": period_block},
    )
    Dfns(components={"gwf-nam": gwf, "gwf-lak": lak})


def test_invalid_array_shape():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    arr = Array(name="botm", dtype="double", shape=["nlay", "no_such_dim"])
    grid_block = Block(name="griddata", fields={"botm": arr})
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block, "griddata": grid_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
        },
    )
    gwf = Model(name="gwf-nam", blocks=None)
    with pytest.raises(ValueError, match="does not resolve"):
        Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})


def test_array_shape_resolves_via_derived_dim():
    dis_block = _dim_block("nlay", "nrow", "ncol")
    arr = Array(name="botm", dtype="double", shape=["nodes"])
    grid_block = Block(name="griddata", fields={"botm": arr})
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block, "griddata": grid_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})


def test_array_shape_resolves_sibling_dims():
    """An array in gwf-chd can reference nlay and nodes from sibling gwf-dis."""
    dis_block = _dim_block("nlay", "nrow", "ncol")
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks={"dimensions": dis_block},
        dims={
            "nlay": InputDim(value="nlay", scope="model"),
            "nrow": InputDim(value="nrow", scope="model"),
            "ncol": InputDim(value="ncol", scope="model"),
            "nodes": InputDim(value="nlay * nrow * ncol", scope="model"),
        },
    )
    chd_arr = Array(name="head", dtype="double", shape=["nlay", "nodes"])
    chd_block = Block(name="period", fields={"head": chd_arr})
    chd = Package(name="gwf-chd", parent="gwf-nam", blocks={"period": chd_block})
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-dis": dis, "gwf-chd": chd})


def test_non_rightmost_inline_array_empty_shape_raises():
    arr = Array(name="vals", dtype="double", shape=[])
    extra = Integer(name="extra")
    rec = Record(name="myrec", fields={"vals": arr, "extra": extra})
    block = Block(name="data", fields={"myrec": rec})
    pkg = Package(name="gwf-test", blocks={"data": block})
    gwf = Model(name="gwf-nam", blocks=None)
    with pytest.raises(ValueError, match="rightmost"):
        Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})


def test_rightmost_inline_array_empty_shape_valid():
    arr = Array(name="auxvals", dtype="double", shape=[])
    rec = Record(name="myrec", fields={"auxvals": arr})
    block = Block(name="data", fields={"myrec": rec})
    pkg = Package(name="gwf-test", blocks={"data": block})
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})


def test_rightmost_inline_string_array_empty_shape_valid():
    arr = Array(name="auxname", dtype="string", shape=[])
    rec = Record(name="aux_rec", fields={"auxname": arr})
    block = Block(name="options", fields={"aux_rec": rec})
    pkg = Package(name="gwf-test", blocks={"options": block})
    gwf = Model(name="gwf-nam", blocks=None)
    Dfns(components={"gwf-nam": gwf, "gwf-test": pkg})


def test_input_dims_visible_to_model_component_itself():
    """A model component can see a model-scoped input dim declared by its own child package.

    A model's own `parent` names the simulation, not the model, so without
    _can_share_model's req_name special case a model could never see a dim
    its own DIS package declares.
    """
    dis = Package(
        name="gwf-dis",
        parent="gwf-nam",
        blocks=None,
        dims={"nodesuser": InputDim(value="42", scope="model")},
    )
    gwf = Model(name="gwf-nam", parent="sim-nam", blocks=None)
    spec = Dfns(components={"gwf-nam": gwf, "gwf-dis": dis})
    assert "nodesuser" in spec.input_dims("gwf-nam")


def test_input_dim_must_name_its_own_field():
    pkg = Package(
        name="test",
        blocks={"dimensions": _dim_block("nlay")},
        dims={"nlayers": InputDim(value="nlay", scope="component")},
    )
    with pytest.raises(ValueError, match="must be the dim's own name"):
        Dfns(components={"test": pkg})


_DIS_DIMS = {
    "nlay": "nlay",
    "nrow": "nrow",
    "ncol": "ncol",
    "ncpl": "nrow * ncol",
    "nodes": "nlay * ncpl",
    "ncelldim": "3",
    "naux": "len(auxiliary)",
    "nconn": "sum(packagedata.nlakeconn)",
    "njas": "(nja - nodes) / 2",
}
_DIS_INPUTS = {
    "nlay": 2,
    "nrow": 3,
    "ncol": 4,
    "nja": 30,
    "auxiliary": ["temp", "conc"],
    "packagedata.nlakeconn": [1, 2, 3],
}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("nlay", 2),
        ("ncpl", 12),
        ("nodes", 24),
        ("ncelldim", 3),
        ("naux", 2),
        ("nconn", 6),
        ("njas", 3),
        ("nja", 30),  # not a dim: an input field
    ],
)
def test_dim_value(name, expected):
    assert dim_value(name, _DIS_DIMS, _DIS_INPUTS.get) == expected


@pytest.mark.parametrize("name", ["nlay", "nodes", "naux", "nconn"])
def test_dim_value_unset_input(name):
    assert dim_value(name, _DIS_DIMS, {}.get) is None


def test_dim_value_inexact_division():
    with pytest.raises(ValueError, match="not an integer"):
        dim_value("njas", _DIS_DIMS, {**_DIS_INPUTS, "nja": 31}.get)


def test_dim_value_cycle():
    with pytest.raises(ValueError, match="cycle"):
        dim_value("a", {"a": "b + 1", "b": "a * 2"}, {}.get)


@pytest.mark.parametrize("expr", ["nlay ** 2", "max(nlay, 1)", "nlay if nlay else 1", "1.5"])
def test_dim_value_unsupported(expr):
    with pytest.raises(ValueError, match="unsupported"):
        dim_value("d", {"d": expr}, {"nlay": 2}.get)


class _One(int):
    """1, usable as an Integer field, a self-sizing array, or a list column."""

    def __new__(cls):
        return super().__new__(cls, 1)

    def __len__(self):
        return 1

    def __iter__(self):
        return iter([1])


def test_dim_value_snapshot_dims():
    """Every input dim in the current DFNs evaluates, given its inputs."""
    spec = Dfns.load(_DEV3_SNAPSHOT_DIR)
    dis = spec.components["gwf-dis"]
    dims = {n: d.value for n, d in dis.dims.items()}
    assert dim_value("nodes", dims, {"nlay": 2, "nrow": 3, "ncol": 4}.get) == 24
    for component in spec.components.values():
        dims = {n: d.value for n, d in (component.dims or {}).items()}
        for name in dims:
            assert dim_value(name, dims, lambda _: _One()) is not None


def test_row_varying_array_must_be_rightmost():
    ncvert = Integer(name="ncvert")
    icvert = Array(name="icvert", dtype="integer", shape=["ncvert"])
    xc = Double(name="xc")
    enc = Record(name="item", fields={"ncvert": ncvert, "icvert": icvert, "xc": xc})
    with pytest.raises(ValueError, match="must be the rightmost field"):
        _validate_shape_element("ncvert", icvert, _pkg("test"), enc, set())


def test_row_varying_lookup_must_be_rightmost():
    arr, enc, pkg, known = _lookup_ctx()
    enc = Record(name="item", fields={**enc.fields, "after": Double(name="after")})
    with pytest.raises(ValueError, match="must be the rightmost field"):
        _validate_shape_element("packagedata.nlakeconn(lakeno)", arr, pkg, enc, known)


_WEL_DIMS = {"maxbound": "maxbound", "auxiliary": "len(auxiliary)", "nseg": "nseg"}


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("nseg-1", 3),  # a dim, offset
        ("auxiliary", 2),  # a derived dim
        ("ncvert", 5),  # a field in the row
    ],
)
def test_dim_value_shape_expression(expr, expected):
    package = {"nseg": 4, "auxiliary": ["temp", "conc"]}
    row = {"ncvert": 5}
    assert dim_value(expr, _WEL_DIMS, ChainMap(row, package).get) == expected


def test_dim_value_row_lookup():
    packagedata = {1: {"ncon": 2}, 2: {"ncon": 3}}
    calls = []

    def select(path, key):
        calls.append((path, key))
        return packagedata[key]["ncon"]

    assert dim_value("packagedata.ncon(ifno)", {}, {"ifno": 2}.get, select) == 3
    assert dim_value("gwf-x.packagedata.ncon(ifno)", {}, {"ifno": 1}.get, select) == 2
    assert calls == [("packagedata.ncon", 2), ("gwf-x.packagedata.ncon", 1)]
    assert dim_value("packagedata.ncon(ifno)", {}, {}.get, select) is None


def test_dim_value_row_lookup_needs_select():
    with pytest.raises(ValueError, match="needs select"):
        dim_value("packagedata.ncon(ifno)", {}, {"ifno": 1}.get)


def test_dim_value_bounded():
    with pytest.raises(ValueError, match="split_bound"):
        dim_value("<=maxbound", _WEL_DIMS, {"maxbound": 3}.get)


def test_dim_value_snapshot_shapes():
    """Every array and list shape in the current DFNs evaluates, given its inputs."""
    spec = Dfns.load(_DEV3_SNAPSHOT_DIR)

    def shapes(field):
        if isinstance(field, (Array, List)):
            yield from field.shape
        if isinstance(field, List):
            yield from shapes(field.item)
        children = getattr(field, "fields", None) or getattr(field, "arms", None) or {}
        for child in children.values():
            yield from shapes(child)

    for component in spec.components.values():
        dims = {n: d.value for n, d in (component.dims or {}).items()}
        for block in (component.blocks or {}).values():
            for field in block.fields.values():
                for element in shapes(field):
                    _bound, expr = split_bound(element)
                    value = dim_value(expr, dims, lambda _: _One(), lambda _p, _k: 1)
                    assert value is not None, (component.name, element)


@pytest.mark.parametrize(
    "expr,inputs,length,expected",
    [
        ("ncvert", {}, 5, ("ncvert", 5)),  # a field in the row
        ("numalphaj", {}, 3, ("numalphaj", 3)),  # an input dim
        ("nseg-1", {}, 3, ("nseg", 4)),
        ("1 + nseg", {}, 3, ("nseg", 2)),
        ("10 - nseg", {}, 3, ("nseg", 7)),
        ("-nseg", {}, -3, ("nseg", 3)),
        ("nlay", {}, 2, ("nlay", 2)),
        ("nlayp", {}, 3, ("nlay", 2)),  # through a derived dim
        ("nseg-1", {"nseg": 4}, 3, None),  # nothing unset
        ("auxiliary", {}, 2, None),  # len() can't be undone
        ("nconn", {}, 6, None),  # nor sum()
        ("ncpl", {"nrow": 3}, 12, None),  # nor *
        ("nlay + nseg", {}, 5, None),  # two unset inputs
        ("packagedata.ncon(ifno)", {"ifno": 1}, 2, None),  # nor a row-level lookup
    ],
)
def test_dim_input(expr, inputs, length, expected):
    dims = {
        "numalphaj": "numalphaj",
        "nseg": "nseg",
        "nlay": "nlay",
        "nlayp": "nlay + 1",
        "ncpl": "nrow * ncol",
        "auxiliary": "len(auxiliary)",
        "nconn": "sum(packagedata.nlakeconn)",
    }
    assert dim_input(expr, dims, inputs.get, length=length) == expected


def test_dim_input_snapshot_shapes():
    """Solving any shape in the current DFNs for its sole unset input, then
    evaluating it with that input set, gives back the length."""
    spec = Dfns.load(_DEV3_SNAPSHOT_DIR)
    solved = set()
    for component in spec.components.values():
        dims = {n: d.value for n, d in (component.dims or {}).items()}

        def shapes(field):
            if isinstance(field, (Array, List)):
                yield from field.shape
            if isinstance(field, List):
                yield from shapes(field.item)
            children = getattr(field, "fields", None) or getattr(field, "arms", None) or {}
            for child in children.values():
                yield from shapes(child)

        for block in (component.blocks or {}).values():
            for field in block.fields.values():
                for element in shapes(field):
                    _bound, expr = split_bound(element)
                    if (solution := dim_input(expr, dims, length=7)) is None:
                        continue
                    name, n = solution
                    assert dim_value(expr, dims, {name: n}.get) == 7, (component.name, expr)
                    solved.add(expr)
    assert {"ncvert", "numalphaj", "nseg-1", "maxbound"} <= solved
    assert "auxiliary" not in solved


def test_dim_defaults():
    """Without dims there are none; without a lookup no input is set."""
    assert dim_value("2 * 3") == 6
    assert dim_value("nlay") is None
    assert dim_value("nlayp", {"nlayp": "nlay + 1"}) is None
    assert dim_input("ncvert", length=5) == ("ncvert", 5)
    assert dim_input("nlayp", {"nlayp": "nlay + 1"}, length=3) == ("nlay", 2)
