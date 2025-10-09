from pathlib import Path

import pytest

from modflow_devtools.dfn import _load_common, load, load_all
from modflow_devtools.dfn.fetch import fetch_dfns
from modflow_devtools.dfn2toml import convert
from modflow_devtools.markers import requires_pkg

PROJ_ROOT = Path(__file__).parents[1]
DFN_DIR = PROJ_ROOT / "autotest" / "temp" / "dfn"
TOML_DIR = DFN_DIR / "toml"
SPEC_DIRS = {1: DFN_DIR, 2: TOML_DIR}
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "develop"


def pytest_generate_tests(metafunc):
    if "dfn_name" in metafunc.fixturenames:
        if not any(DFN_DIR.glob("*.dfn")):
            fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
        dfn_names = [
            dfn.stem
            for dfn in DFN_DIR.glob("*.dfn")
            if dfn.stem not in ["common", "flopy"]
        ]
        metafunc.parametrize("dfn_name", dfn_names, ids=dfn_names)

    if "toml_name" in metafunc.fixturenames:
        convert(DFN_DIR, TOML_DIR)
        expected_toml_paths = [
            dfn for dfn in DFN_DIR.glob("*.dfn") if "common" not in dfn.stem
        ]
        assert all(toml_path.exists() for toml_path in expected_toml_paths)
        toml_names = [toml.stem for toml in TOML_DIR.glob("*.toml")]
        metafunc.parametrize("toml_name", toml_names, ids=toml_names)


@requires_pkg("boltons")
def test_load_v1(dfn_name):
    with (
        (DFN_DIR / "common.dfn").open() as common_file,
        (DFN_DIR / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common, _ = _load_common(common_file)
        dfn = load(dfn_file, name=dfn_name, format="dfn", common=common)
        assert any(dfn.fields)


@requires_pkg("boltons")
def test_load_v2(toml_name):
    with (TOML_DIR / f"{toml_name}.toml").open(mode="rb") as toml_file:
        dfn = load(toml_file, name=toml_name, format="toml")
        assert any(dfn.fields)


@requires_pkg("boltons")
@pytest.mark.parametrize("schema_version", list(SPEC_DIRS.keys()))
def test_load_all(schema_version):
    dfns = load_all(path=SPEC_DIRS[schema_version])
    assert all(any(dfn.fields) for dfn in dfns.values())


@requires_pkg("boltons", "tomli")
def test_convert(function_tmpdir):
    import tomli

    convert(DFN_DIR, function_tmpdir)

    assert (function_tmpdir / "sim-nam.toml").exists()
    assert (function_tmpdir / "gwf-nam.toml").exists()

    with (function_tmpdir / "sim-nam.toml").open("rb") as f:
        sim_data = tomli.load(f)
    assert sim_data["name"] == "sim-nam"
    assert sim_data["schema_version"] == "2"
    assert "parent" not in sim_data

    with (function_tmpdir / "gwf-nam.toml").open("rb") as f:
        gwf_data = tomli.load(f)
    assert gwf_data["name"] == "gwf-nam"
    assert gwf_data["parent"] == "sim-nam"
    assert gwf_data["schema_version"] == "2"

    dfns = load_all(function_tmpdir)
    roots = []
    for dfn in dfns.values():
        if dfn.parent:
            assert dfn.parent in dfns
        else:
            roots.append(dfn.name)
    assert len(roots) == 1
    root = dfns[roots[0]]
    assert root.name == "sim-nam"

    models = root.children or {}
    for mdl in models:
        assert models[mdl].name == mdl
        assert models[mdl].parent == "sim-nam"

    if gwf := models.get("gwf-nam", None):
        pkgs = gwf.children or {}
        pkgs = {
            k: v
            for k, v in pkgs.items()
            if k.startswith("gwf-") and isinstance(v, dict)
        }
        assert len(pkgs) > 0
        if dis := pkgs.get("gwf-dis", None):
            assert dis.name == "gwf-dis"
            assert dis.parent == "gwf"
            assert "options" in (dis.blocks or {})
            assert "dimensions" in (dis.blocks or {})
