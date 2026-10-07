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


@pytest.mark.parametrize("col, optional", [("id", False), ("id2", True)])
def test_migrate_obs_id_union(dfn_dir, col, optional):
    """A v1 string with numeric_index (utl-obs's id/id2) becomes an untagged
    union of a cellid, a 1-based index, and a boundname."""
    component = _migrate_dev3(dfn_dir, "utl-obs")
    item = component.blocks["continuous"].fields["continuous"].item
    field = item.fields[col]
    assert isinstance(field, v2.Union)
    assert (field.tagged, field.optional) == (False, optional)
    cellid, index, boundname = field.arms.values()
    assert isinstance(cellid, v2.Array)
    assert (cellid.shape, cellid.index, cellid.cellid) == (["ncelldim"], True, True)
    assert isinstance(index, v2.Integer) and index.index
    assert isinstance(boundname, v2.String)
    assert not any(arm.tagged for arm in field.arms.values())


def _obs_forms(field) -> list[tuple]:
    """The token sequences an observation field reads, each a tuple of
    columns: ("cellid",), ("boundname",), ("double", name) or ("index", fk)."""
    if isinstance(field, v2.Union):
        return [f for arm in field.arms.values() for f in _obs_forms(arm)]
    if isinstance(field, v2.Record):
        forms: list[tuple] = [()]
        for col in field.fields.values():
            forms = [f + g for f in forms for g in _obs_forms(col)]
        return forms
    if isinstance(field, v2.Array) and field.cellid:
        return [(("cellid",),)]
    if isinstance(field, v2.String):
        return [(("boundname",),)]
    if isinstance(field, v2.Double):
        return [(("double", field.name),)]
    assert isinstance(field, v2.Integer) and field.index
    return [(("index", field.fk),)]


_CELL = ("cellid",)
_NAME = ("boundname",)


@pytest.mark.parametrize(
    "name, obstype, forms",
    [
        # CSUB mixes index- and cellid-keyed obstypes, some without boundnames
        ("gwf-csub", "csub", [(("index", "packagedata.icsubno"),), (_NAME,)]),
        ("gwf-csub", "sk", [(("index", "packagedata.icsubno"),)]),
        ("gwf-csub", "csub-cell", [(_CELL,)]),
        ("gwf-csub", "delay-head", [(("index", "packagedata.icsubno"), ("index", None))]),
        # UZF's water-content depth isn't an id, and follows a boundname too
        (
            "gwf-uzf",
            "water-content",
            [(("index", "packagedata.ifno"), ("double", "depth")), (_NAME, ("double", "depth"))],
        ),
        ("gwf-uzf", "uzet", [(("index", "packagedata.ifno"),), (_NAME,)]),
        # a connection number or a boundname follows a lake/well number,
        # but nothing follows a boundname
        (
            "gwf-lak",
            "lak",
            [
                (("index", "packagedata.ifno"), ("index", None)),
                (("index", "packagedata.ifno"), _NAME),
                (_NAME,),
            ],
        ),
        (
            "gwf-maw",
            "conductance",
            [
                (("index", "packagedata.ifno"), ("index", None)),
                (("index", "packagedata.ifno"), _NAME),
                (_NAME,),
            ],
        ),
        # APT packages read id2 as a number only
        ("gwt-lkt", "lkt", [(("index", "packagedata.ifno"), ("index", None)), (_NAME,)]),
        ("gwf-lak", "outlet", [(("index", "outlets.outletno"),), (_NAME,)]),
        (
            "gwt-lkt",
            "flow-ja-face",
            [(("index", "packagedata.ifno"), ("index", "packagedata.ifno")), (_NAME,)],
        ),
        # MF6 reads no id2 for lke, though its docs list one
        ("gwe-lke", "lke", [(("index", "packagedata.lakeno"),), (_NAME,)]),
        ("gwf-wel", "wel", [(_CELL,), (_NAME,)]),
        ("gwf-nam", "flow-ja-face", [(_CELL, _CELL)]),
        # an exchange id is a row number in exchangedata, which has no pk
        ("exg-gwegwe", "flow-ja-face", [(("index", None),), (_NAME,)]),
    ],
)
def test_migrate_observations(dfn_dir, name, obstype, forms):
    component = _migrate_dev3(dfn_dir, name)
    assert component.observations is not None
    field = component.observations[obstype]
    assert field.name == obstype
    assert _obs_forms(field) == forms


def test_migrate_observations_on_obs_parents(dev3):
    """Every component with an OBS file gets observations, except the
    SWF-GWF exchanges, which MF6 registers no observation types for."""
    out, _ = dev3
    spec = v2.Dfns.load(out)
    obs_parents = {
        name
        for name, c in spec.components.items()
        if isinstance(c, v2.Model)
        or any(
            getattr(f, "component", None) == "utl-obs"
            for f in c.get_fields(recurse=True).values(multi=True)
        )
    }
    with_obs = {name for name, c in spec.components.items() if c.observations}
    assert obs_parents - with_obs == {"exg-chfgwf", "exg-olfgwf", "prt-nam"}
    assert with_obs <= obs_parents


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


def test_migrate_keyword_aliases(dfn_dir):
    component = _migrate_dev3(dfn_dir, "utl-ts")
    record = component.blocks["attributes"].fields["time_series_namerecord"]
    assert record.fields["names"].aliases == ["name"]


# --- component links (File.component) and the parents derived from them ---


@pytest.fixture(scope="module")
def linked_spec(dfn_dir):
    return v2.Dfns.load(dfn_dir)


def _linked_files(component, record: str) -> list:
    """The input Files under the field named ``record``, anywhere."""
    found = [
        f
        for f in component.get_fields(recurse=True).values(multi=True)
        if f.name == record or getattr(getattr(f, "item", None), "name", None) == record
    ]
    assert found, f"{component.name} has no {record!r}"
    return [
        file for f in found for file, _ in v2._iter_files({f.name: f}) if file.direction == "in"
    ]


def _components(component, record: str) -> list:
    return [f.component for f in _linked_files(component, record)]


@pytest.mark.parametrize(
    "name", [f"{m}-{d}" for m in ("gwf", "gwt", "gwe", "prt") for d in ("dis", "disv")]
)
def test_migrate_links_ncf(linked_spec, name):
    assert _components(linked_spec.components[name], "ncf_filerecord") == ["utl-ncf"]


def test_migrate_links_ts_and_obs_everywhere(linked_spec):
    for name, c in linked_spec.components.items():
        fields = c.get_fields(recurse=True)
        for record, target in (("ts_filerecord", "utl-ts"), ("obs_filerecord", "utl-obs")):
            if record in fields:
                assert set(_components(c, record)) == {target}, name


@pytest.mark.parametrize(
    "name, record, target",
    [
        ("gwf-npf", "tvk_filerecord", "utl-tvk"),
        ("gwf-sto", "tvs_filerecord", "utl-tvs"),
        ("sim-tdis", "ats_filerecord", "utl-ats"),
        ("sim-nam", "hpc_filerecord", "utl-hpc"),
        ("gwt-ssm", "fileinput", ["utl-spc", "utl-spca"]),
        ("gwe-ssm", "fileinput", ["utl-spc", "utl-spca"]),
        ("gwf-lak", "tables", "utl-laktab"),
    ],
)
def test_migrate_links_subpackage(linked_spec, name, record, target):
    assert _components(linked_spec.components[name], record) == [target]


def test_migrate_links_sfr_tables(linked_spec):
    files = [
        f
        for f in linked_spec.components["gwf-sfr"].get_fields(recurse=True).values(multi=True)
        if isinstance(f, v2.File) and f.name == "tab6_filename"
    ]
    assert len(files) == 2
    assert {f.component for f in files} == {"utl-sfrtab"}


@pytest.mark.parametrize(
    "field, selector, component_ftype",
    [
        ("tdis6", "sim-tdis", None),
        ("mfname", "model", "mtype"),
        ("exgfile", "exchange", "exgtype"),
        ("slnfname", "solution", "slntype"),
    ],
)
def test_migrate_links_sim_nam(linked_spec, field, selector, component_ftype):
    file = linked_spec.components["sim-nam"].get_fields(recurse=True)[field]
    assert isinstance(file, v2.File)
    assert (file.component, file.component_ftype) == (selector, component_ftype)
    assert file.direction == "in" and not file.mode_keyword
    assert not file.optional


def test_migrate_tdis6_renders_without_filein(linked_spec):
    timing = linked_spec.components["sim-nam"].blocks["timing"]
    assert "TDIS6 <tdis6>" in timing.fields["tdis6"].render()


def test_migrate_links_model_packages(linked_spec):
    models = [c for c in linked_spec.components.values() if isinstance(c, v2.Model)]
    assert models
    for model in models:
        file = model.get_fields(recurse=True)["fname"]
        assert (file.component, file.component_ftype) == ("package", "ftype"), model.name


def test_migrate_link_selectors_resolve(linked_spec):
    for name, c in linked_spec.components.items():
        children = linked_spec.children(name)
        for block in (c.blocks or {}).values():
            for file, _ in v2._iter_files(block.fields):
                if file.component is None:
                    continue
                targets = [n for n, t in children.items() if v2.admits(file.component, t)]
                assert targets, (name, file.name)
                if file.component_ftype is None:
                    ftypes = {linked_spec.components[t].ftype for t in targets}
                    assert len(ftypes) == 1, (name, file.name)


def test_migrate_model_packages_exclude_utilities(linked_spec):
    children = linked_spec.children("gwf-nam")
    assert {"gwf-dis", "gwf-gnc", "gwf-mvr"} <= set(children)
    # but a model with observations reads an OBS6 file
    assert [n for n in children if n.startswith("utl-")] == ["utl-obs"]
    assert linked_spec.ftype_family("OBS6", "gwf-nam") == ["utl-obs"]


def test_migrate_unlinked_files(linked_spec):
    """Output files (grb_filerecord, ...) and NetCDF input aren't links."""
    netcdf = {"nc_filerecord", "nc_mesh2d_filerecord", "nc_structured_filerecord"}
    for name, c in linked_spec.components.items():
        for field in c.get_fields(recurse=True).values(multi=True):
            for file, _ in v2._iter_files({field.name: field}):
                if file.direction == "out" or field.name in netcdf:
                    assert file.component is None, (name, file.name)


@pytest.mark.parametrize(
    "name, parent",
    [
        ("utl-ts", "package"),
        ("utl-obs", ["model", "package"]),
        (
            "utl-ncf",
            [f"{m}-{d}" for m in ("gwe", "gwf", "gwt", "prt") for d in ("dis", "disv")],
        ),
        ("utl-spc", ["gwe-ssm", "gwt-ssm"]),
        ("utl-spca", ["gwe-ssm", "gwt-ssm"]),
        ("utl-tas", ["gwf-evta", "gwf-rcha", "utl-spca"]),
        ("utl-tvk", "gwf-npf"),
        ("utl-tvs", "gwf-sto"),
        ("utl-sfrtab", "gwf-sfr"),
        ("utl-laktab", "gwf-lak"),
        ("utl-ats", "sim-tdis"),
        ("utl-hpc", "sim-nam"),
        ("gwf-gnc", ["exg-gwfgwf", "gwf-nam"]),
        ("gwf-mvr", ["exg-gwfgwf", "gwf-nam"]),
        ("gwt-mvt", ["exg-gwtgwt", "gwt-nam"]),
        ("gwe-mve", ["exg-gwegwe", "gwe-nam"]),
        ("sim-tdis", "sim-nam"),
    ],
)
def test_migrate_derives_parents_from_links(linked_spec, name, parent):
    assert linked_spec.components[name].parent == parent


@pytest.mark.parametrize("name, multi", [("utl-obs", False), ("utl-ts", True)])
def test_migrate_multi_overrides(linked_spec, name, multi):
    # flopy3 marks both multi-package, but MF6 reads one OBS6 per parent
    assert linked_spec.components[name].multi is multi


def test_migrate_obs_keeps_any_model_dims(linked_spec):
    # utl-obs's parent gains `model`; it still sees any model's dims
    assert {"nodes", "nlay"} <= linked_spec.inherited_dims("utl-obs")


def test_migrate_subpackage_keeps_model_dims(linked_spec):
    # tvk's parent is now gwf-npf, not `package`; it must still see grid dims
    assert {"nodes", "nlay"} <= linked_spec.inherited_dims("utl-tvk")


@pytest.mark.parametrize(
    "name, ftype",
    [
        ("sim-nam", None),
        ("gwf-nam", "GWF6"),
        ("gwf-dis", "DIS6"),
        ("gwf-rch", "RCH6"),
        ("gwf-rcha", "RCH6"),
        ("gwf-chdg", "CHD6"),
        ("utl-spca", "SPC6"),
        ("exg-gwfgwf", "GWF6-GWF6"),
        ("exg-gwfprt", "GWF6-PRT6"),
        ("sln-ims", "IMS6"),
        ("sim-tdis", "TDIS6"),
        ("utl-ncf", "NCF6"),
    ],
)
def test_migrate_ftype(linked_spec, name, ftype):
    assert linked_spec.components[name].ftype == ftype


def test_migrate_ftypes_unique_among_name_file_children(linked_spec):
    """Within a name file, one ftype names one component, or a base and its
    array-based variants."""
    for name, c in linked_spec.components.items():
        if not name.endswith("-nam"):
            continue
        by_ftype: dict = {}
        for child, cc in linked_spec.children(name).items():
            by_ftype.setdefault(cc.ftype, []).append(child)
        for ftype, children in by_ftype.items():
            base = min(children, key=len)
            assert all(n in (base, f"{base}a", f"{base}g") for n in children), (name, children)
