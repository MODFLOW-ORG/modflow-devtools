import io
import json
import tomllib
from pathlib import Path

import pytest
import yaml

from modflow_devtools.dfn.schema import Dfn
from modflow_devtools.dfns import fetch_dfns, migrate
from modflow_devtools.dfns import schema as v2
from modflow_devtools.dfns.migrate_to_v2_0_0_dev2 import to_v2_0_0_dev2
from modflow_devtools.dfns.migrate_to_v2_0_0_dev3 import to_v2_0_0_dev3

FORMATS = ["yaml", "toml", "json"]
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "6.7.0"


def _load(path: Path, fmt: str) -> dict:
    if fmt == "toml":
        with path.open("rb") as f:
            return tomllib.load(f)
    elif fmt == "json":
        with path.open() as f:
            return json.load(f)
    else:
        with path.open() as f:
            return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dfn_dir(module_tmpdir):
    pytest.importorskip("boltons")
    path = module_tmpdir / "dfn"
    path.mkdir()
    fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, path, verbose=True)
    return path


@pytest.fixture(scope="module", params=FORMATS)
def dev0(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev0-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev0", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev1(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev1-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev1", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev2(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev2-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev2", fmt=fmt)
    return out, fmt


@pytest.fixture(scope="module", params=FORMATS)
def dev3(request, dfn_dir, module_tmpdir):
    fmt = request.param
    out = module_tmpdir / f"dev3-{fmt}"
    migrate(dfn_dir, out, schema_version="2.0.0.dev3", fmt=fmt)
    return out, fmt


def test_migrate_v2_0_0_dev0(dev0, snapshot):
    out, fmt = dev0
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev0"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev1(dev1, snapshot):
    out, fmt = dev1
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev1"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev2(dev2, snapshot):
    out, fmt = dev2
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev2"
        assert snapshot(name=p.stem) == p.read_text()


def test_migrate_v2_0_0_dev3(dev3, snapshot):
    out, fmt = dev3
    files = sorted(out.glob(f"*.{fmt}"))
    assert files
    for p in files:
        data = _load(p, fmt)
        assert data["name"] == p.stem
        assert data["schema_version"] == "2.0.0.dev3"
        assert snapshot(name=p.stem) == p.read_text()


# Minimal synthetic DFN (shaped like gwt-ssm's SOURCES block) exercising the
# write_if_empty tag. No real upstream DFN sets this tag directly yet (it
# isn't derivable from other DFN attributes -- see Block.write_if_empty in
# schema.py), so the general per-field mechanism is covered here against a
# neutral component name rather than via the real-corpus snapshot tests
# above. gwt-ssm/gwe-ssm themselves get write_if_empty from a dedicated
# migration-time fixup (_fix_ssm_sources_write_if_empty) instead, pending
# that DFN tag -- see the tests below that exercise those two names directly.
_SOURCES_DFN = """\
block sources
name sources
type recarray pname srctype auxname
reader urword
optional false
write_if_empty true
longname package list
description

block sources
name pname
in_record true
type string
tagged false
reader urword
longname package name
description pname

block sources
name srctype
in_record true
type string
tagged false
optional false
reader urword
longname source type
description srctype

block sources
name auxname
in_record true
type string
tagged false
optional false
reader urword
longname auxiliary variable name
description auxname
"""


def _load_sources_fields(dfn_text: str = _SOURCES_DFN):
    pytest.importorskip("boltons")
    return Dfn.load_dfn(io.StringIO(dfn_text))


# A neutral name (not gwt-ssm/gwe-ssm) so these general-mechanism tests
# aren't also exercising the SSM-specific fixup below.
_NEUTRAL_NAME = "gwt-tst"


def test_migrate_v2_0_0_dev2_write_if_empty():
    fields, meta = _load_sources_fields()
    component = to_v2_0_0_dev2(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is True


def test_migrate_v2_0_0_dev3_write_if_empty():
    fields, meta = _load_sources_fields()
    component = to_v2_0_0_dev3(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is True


def test_migrate_write_if_empty_absent_defaults_false():
    dfn_without_tag = _SOURCES_DFN.replace("write_if_empty true\n", "")
    fields, meta = _load_sources_fields(dfn_without_tag)
    component = to_v2_0_0_dev2(_NEUTRAL_NAME, fields, meta)
    assert component.blocks["sources"].write_if_empty is False


@pytest.mark.parametrize("name", ["gwt-ssm", "gwe-ssm"])
def test_migrate_ssm_sources_write_if_empty_without_tag(name):
    """
    gwt-ssm/gwe-ssm get write_if_empty from _fix_ssm_sources_write_if_empty
    regardless of whether the DFN sets the tag -- no real DFN does yet.
    """
    dfn_without_tag = _SOURCES_DFN.replace("write_if_empty true\n", "")
    fields, meta = _load_sources_fields(dfn_without_tag)
    component = to_v2_0_0_dev2(name, fields, meta)
    assert component.blocks["sources"].write_if_empty is True


def _migrate_dev3(dfn_dir: Path, name: str):
    from modflow_devtools.dfn import schema as v1

    with (dfn_dir / "common.dfn").open() as f:
        common, _ = v1.Dfn.load_dfn(f)
    with (dfn_dir / f"{name}.dfn").open() as f:
        fields, meta = v1.Dfn.load_dfn(f, common=common)
    return to_v2_0_0_dev3(name, fields, meta)


def _list_shape(component, block: str) -> list[str]:
    return component.blocks[block].fields[block].shape


@pytest.mark.parametrize("name", ["gwf-oc", "gwt-oc", "gwe-oc", "prt-oc"])
def test_migrate_keeps_v1_upper_bound(dfn_dir, name):
    # v1's `shape (<nstp)` means at most nstp, i.e. v2's `<=`
    component = _migrate_dev3(dfn_dir, name)
    shapes = [
        f.shape
        for f in component.get_fields(recurse=True).values(multi=True)
        if isinstance(f, v2.Array) and f.name == "steps"
    ]
    assert shapes and all(shape == ["<=nstp"] for shape in shapes)


def test_migrate_keeps_v1_upper_bound_prp(dfn_dir):
    fields = _migrate_dev3(dfn_dir, "prt-prp").get_fields(recurse=True)
    for name in ("steps", "fraction"):
        shapes = [
            f.shape for f in fields.values(multi=True) if isinstance(f, v2.Array) and f.name == name
        ]
        assert shapes and all(shape == ["<=nstp"] for shape in shapes)


@pytest.mark.parametrize("name", ["gwf-chd", "gwf-wel", "gwt-src", "olf-flw", "utl-spc"])
def test_migrate_maxbound_is_upper_bound(dfn_dir, name):
    component = _migrate_dev3(dfn_dir, name)
    lists = [
        f for b in component.blocks.values() for f in b.fields.values() if isinstance(f, v2.List)
    ]
    assert [f.shape for f in lists if f.shape] == [["<=maxbound"]]


@pytest.mark.parametrize(
    "name,block,shape",
    [
        ("gwf-hfb", "period", ["<=maxhfb"]),
        ("gwf-csub", "period", ["<=maxsig0"]),
        ("utl-ats", "perioddata", ["<=maxats"]),
        ("sim-tdis", "perioddata", ["nper"]),
        ("gwf-mvr", "packages", ["maxpackages"]),
    ],
)
def test_migrate_list_shape_bounds(dfn_dir, name, block, shape):
    component = _migrate_dev3(dfn_dir, name)
    fields = {f.name: f for f in component.blocks[block].fields.values()}
    assert next(f for f in fields.values() if isinstance(f, v2.List)).shape == shape


@pytest.mark.parametrize(
    "name,optional,required",
    [
        (
            "gwf-sfr",
            ["crosssections", "diversions", "initialstages"],
            ["packagedata", "connectiondata"],
        ),
        ("gwf-lak", ["outlets"], ["packagedata", "connectiondata"]),
        ("sln-ims", ["nonlinear", "linear"], []),
    ],
)
def test_migrate_optional_blocks(dfn_dir, name, optional, required):
    # MF6 reads these with blockRequired=.false. though v1 marks fields required
    component = _migrate_dev3(dfn_dir, name)
    assert all(component.blocks[b].optional for b in optional)
    assert not any(component.blocks[b].optional for b in required)


def test_migrate_ts_shapes(dfn_dir):
    component = _migrate_dev3(dfn_dir, "utl-ts")
    attrs = component.blocks["attributes"].fields
    assert component.dims["time_series_names"].value == "len(time_series_names)"
    assert attrs["time_series_namerecord"].fields["time_series_names"].shape == []
    method = attrs["interpolation_methodrecord"].fields["interpolation_method"]
    assert method.shape == ["time_series_names"]
    assert attrs["sfacrecord"].fields["sfacval"].shape == ["time_series_names"]
    assert isinstance(attrs["sfacrecord_single"].fields["sfacval"], v2.Double)
    ts = component.blocks["timeseries"].fields["timeseries"].item.fields["ts_array"]
    assert ts.shape == ["time_series_names"]


@pytest.mark.parametrize("v1_shape", ["(ncon(ifno))", "(:)"])
def test_migrate_sfr_ic_shape(dfn_dir, tmp_path, v1_shape):
    for name in ("common", "gwf-sfr"):
        text = (dfn_dir / f"{name}.dfn").read_text()
        text = text.replace("shape (ncon(ifno))", f"shape {v1_shape}")
        (tmp_path / f"{name}.dfn").write_text(text)
    component = _migrate_dev3(tmp_path, "gwf-sfr")
    conn = component.blocks["connectiondata"].fields["connectiondata"].item
    assert conn.fields["ic"].shape == ["packagedata.ncon(ifno)"]


@pytest.mark.parametrize("v1_shape", ["(sum(nlakeconn))", "(nlakeconn)"])
def test_migrate_lak_connectiondata_shape(dfn_dir, tmp_path, v1_shape):
    for name in ("common", "gwf-lak"):
        text = (dfn_dir / f"{name}.dfn").read_text()
        text = text.replace("shape (sum(nlakeconn))", f"shape {v1_shape}")
        (tmp_path / f"{name}.dfn").write_text(text)
    component = _migrate_dev3(tmp_path, "gwf-lak")
    assert component.blocks["connectiondata"].fields["connectiondata"].shape == ["nlakeconn"]
    assert component.dims["nlakeconn"].value == "sum(packagedata.nlakeconn)"


def test_migrate_auxiliary_stays_self_sizing(dfn_dir):
    component = _migrate_dev3(dfn_dir, "gwf-chd")
    assert component.blocks["options"].fields["auxiliary"].shape == []


def test_migrate_gnc_cellids(dfn_dir):
    component = _migrate_dev3(dfn_dir, "gwf-gnc")
    item = component.blocks["gncdata"].fields["gncdata"].item
    for name, shape in [
        ("cellidn", ["ncelldim"]),
        ("cellidm", ["ncelldim"]),
        ("cellidsj", ["ncelldim", "numalphaj"]),
    ]:
        field = item.fields[name]
        assert isinstance(field, v2.Array)
        assert (field.dtype, field.shape, field.index, field.cellid) == (
            "integer",
            shape,
            True,
            True,
        )
    assert not item.fields["alphasj"].cellid


@pytest.mark.parametrize("name", ["exg-gwfgwf", "exg-gwtgwt"])
def test_migrate_exchange_cellids(dfn_dir, name):
    component = _migrate_dev3(dfn_dir, name)
    item = component.blocks["exchangedata"].fields["exchangedata"].item
    for col in ("cellidm1", "cellidm2"):
        field = item.fields[col]
        assert isinstance(field, v2.Array)
        assert (field.shape, field.index, field.cellid) == (["ncelldim"], True, True)


@pytest.mark.parametrize(
    "name, block, cols",
    [
        ("gwf-chd", "period", ["cellid"]),
        ("gwf-hfb", "period", ["cellid1", "cellid2"]),
        ("gwf-csub", "packagedata", ["cellid"]),
    ],
)
def test_migrate_marks_cellids(dfn_dir, name, block, cols):
    component = _migrate_dev3(dfn_dir, name)
    lst = next(f for f in component.blocks[block].fields.values() if isinstance(f, v2.List))
    for col in cols:
        field = lst.item.fields[col]
        assert (field.shape, field.index, field.cellid) == (["ncelldim"], True, True)


def test_migrate_sfr_ic_is_signed_index(dfn_dir):
    component = _migrate_dev3(dfn_dir, "gwf-sfr")
    item = component.blocks["connectiondata"].fields["connectiondata"].item
    ic = item.fields["ic"]
    assert ic.index == "signed"
    assert ic.fk == "packagedata.ifno"
    # nothing else in the corpus supports negative indices
    signed = [
        f.name
        for f in component.get_fields(recurse=True).values(multi=True)
        if getattr(f, "index", False) == "signed"
    ]
    assert signed == ["ic"]


def test_migrate_package_dims_are_component_scoped(dev3):
    out, _ = dev3
    spec = v2.Dfns.load(out)
    inherited = spec.inherited_dims("gwf-wel")
    assert {"nlay", "nrow", "ncol", "ncpl", "nodes", "ncelldim", "nper"} <= inherited
    assert not inherited & {"nseg", "numgnc", "numalphaj", "maxbound", "nexg", "maxats"}
    shared = {
        (name, dim)
        for name, c in spec.components.items()
        for dim, d in (c.dims or {}).items()
        if d.scope != "component"
    }
    assert {name for name, _ in shared} - {"sim-tdis"} == {
        name for name in spec.components if name.split("-")[1].startswith("dis")
    }
    assert ("sim-tdis", "nper") in shared
