from pathlib import Path

import pytest

from modflow_devtools.dfn import Dfn, get_dfns
from modflow_devtools.dfn2toml import convert
from modflow_devtools.markers import requires_pkg

PROJ_ROOT = Path(__file__).parents[1]
DFN_DIR = PROJ_ROOT / "autotest" / "temp" / "dfn"
TOML_DIR = DFN_DIR / "toml"
VERSIONS = {1: DFN_DIR, 2: TOML_DIR}
MF6_OWNER = "MODFLOW-ORG"
MF6_REPO = "modflow6"
MF6_REF = "develop"


def pytest_generate_tests(metafunc):
    if "dfn_name" in metafunc.fixturenames:
        if not any(DFN_DIR.glob("*.dfn")):
            get_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
        dfn_names = [
            dfn.stem
            for dfn in DFN_DIR.glob("*.dfn")
            if dfn.stem not in ["common", "flopy"]
        ]
        metafunc.parametrize("dfn_name", dfn_names, ids=dfn_names)

    if "toml_name" in metafunc.fixturenames:
        convert(DFN_DIR, TOML_DIR)
        dfn_paths = list(DFN_DIR.glob("*.dfn"))
        assert all(
            (TOML_DIR / f"{dfn.stem.replace('-nam', '')}.toml").is_file()
            for dfn in dfn_paths
            if "common" not in dfn.stem
        )
        toml_names = [toml.stem for toml in TOML_DIR.glob("*.toml")]
        metafunc.parametrize("toml_name", toml_names, ids=toml_names)


@requires_pkg("boltons")
def test_load_v1(dfn_name):
    with (
        (DFN_DIR / "common.dfn").open() as common_file,
        (DFN_DIR / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common, _ = Dfn._load_v1_flat(common_file)
        dfn = Dfn.load(dfn_file, name=dfn_name, common=common)
        assert any(dfn)


@requires_pkg("boltons")
def test_load_v2(toml_name):
    with (TOML_DIR / f"{toml_name}.toml").open(mode="rb") as toml_file:
        toml = Dfn.load(toml_file, name=toml_name, version=2)
        assert any(toml)


@requires_pkg("boltons")
@pytest.mark.parametrize("version", list(VERSIONS.keys()))
def test_load_all(version):
    dfns = Dfn.load_all(VERSIONS[version], version=version)
    assert any(dfns)


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

        # Test hierarchy enforcement and completeness
        dfns = Dfn.load_all(tmp_path, version=2)
        roots = [name for name, dfn in dfns.items() if not dfn.get("parent")]
        assert len(roots) == 1
        assert roots[0] == "sim"

        for dfn in dfns.values():
            parent = dfn.get("parent")
            if parent:
                assert parent in dfns

        # Test tree building and navigation
        tree = Dfn.load_tree(tmp_path, version=2)
        assert "sim" in tree
        assert tree["sim"]["name"] == "sim"

        for model_type in ["gwf", "gwt", "gwe"]:
            if model_type in tree["sim"]:
                assert tree["sim"][model_type]["name"] == model_type
                assert tree["sim"][model_type]["parent"] == "sim"

        if "gwf" in tree["sim"]:
            gwf_packages = [
                k
                for k in tree["sim"]["gwf"].keys()
                if k.startswith("gwf-") and isinstance(tree["sim"]["gwf"][k], dict)
            ]
            assert len(gwf_packages) > 0

            if "gwf-dis" in tree["sim"]["gwf"]:
                dis = tree["sim"]["gwf"]["gwf-dis"]
                assert dis["name"] == "gwf-dis"
                assert dis["parent"] == "gwf"
                assert "options" in dis or "dimensions" in dis
