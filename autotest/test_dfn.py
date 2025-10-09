from pathlib import Path

import pytest

from modflow_devtools.dfn import _load_common, load, load_all, load_tree
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
        dfn_paths = list(DFN_DIR.glob("*.dfn"))
        expected_toml_paths = [
            TOML_DIR / f"{dfn.stem.replace('-nam', '')}.toml"
            for dfn in dfn_paths
            if "common" not in dfn.stem
        ]
        toml_names = [toml.stem for toml in TOML_DIR.glob("*.toml")]
        assert all(toml_path.exists() for toml_path in expected_toml_paths)
        metafunc.parametrize("toml_name", toml_names, ids=toml_names)


@requires_pkg("boltons")
def test_load_v1(dfn_name):
    with (
        (DFN_DIR / "common.dfn").open() as common_file,
        (DFN_DIR / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common, _ = _load_common(common_file)
        dfn = load(dfn_file, name=dfn_name, common=common)
        assert any(dfn.fields)


@requires_pkg("boltons")
def test_load_v2(toml_name):
    with (TOML_DIR / f"{toml_name}.toml").open(mode="rb") as toml_file:
        dfn = load(toml_file, name=toml_name, format="toml")
        assert any(dfn.fields)


@requires_pkg("boltons")
@pytest.mark.parametrize("schema_version", list(SPEC_DIRS.keys()))
def test_load_all(schema_version):
    path = SPEC_DIRS[schema_version]
    dfns = load_all(path)
    assert all(any(dfn.fields) for dfn in dfns.values())


@requires_pkg("boltons")
def test_load_tree():
    import tempfile

    import tomli

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        convert(DFN_DIR, tmp_path)

        # Test file conversion and naming
        assert (tmp_path / "sim.toml").exists()
        assert (tmp_path / "gwf.toml").exists()
        assert not (tmp_path / "sim-nam.toml").exists()

        # Test parent relationships in files
        with (tmp_path / "sim.toml").open("rb") as f:
            sim_data = tomli.load(f)
        assert sim_data["name"] == "sim"
        assert "parent" not in sim_data

        with (tmp_path / "gwf.toml").open("rb") as f:
            gwf_data = tomli.load(f)
        assert gwf_data["name"] == "gwf"
        assert gwf_data["parent"] == "sim"

        dfns = load_all(tmp_path)
        root = load_tree(tmp_path)
        roots = []
        for dfn in dfns.values():
            if dfn.parent:
                assert dfn.parent in dfns
            else:
                roots.append(dfn.name)
        assert len(roots) == 1
        assert root.name == "sim"
        assert root == roots[0]

        model_types = ["gwf", "gwt", "gwe"]
        models = root.children or {}
        for model_type in model_types:
            if model_type in models:
                assert models[model_type].name == model_type
                assert models[model_type].parent == "sim"

        if "gwf" in models:
            pkgs = models["gwf"].children or {}
            gwf_packages = [
                k for k in pkgs if k.startswith("gwf-") and isinstance(pkgs[k], dict)
            ]
            assert len(gwf_packages) > 0

            if dis := pkgs.get("gwf-dis", None):
                assert dis.name == "gwf-dis"
                assert dis.parent == "gwf"
                assert "options" in (dis.blocks or {})
                assert "dimensions" in (dis.blocks or {})
