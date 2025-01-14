from pathlib import Path

from modflow_devtools.dfn import Dfn, get_dfns
from modflow_devtools.dfn2toml import convert
from modflow_devtools.markers import requires_pkg

PROJ_ROOT = Path(__file__).parents[1]
DFN_PATH = PROJ_ROOT / "autotest" / "temp" / "dfn"
TOML_PATH = DFN_PATH / "toml"
MF6_OWNER = "MODFLOW-USGS"
MF6_REPO = "modflow6"
MF6_REF = "develop"


def pytest_generate_tests(metafunc):
    if "dfn_name" in metafunc.fixturenames:
        if not any(DFN_PATH.glob("*.dfn")):
            get_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_PATH, verbose=True)
        dfn_names = [
            dfn.stem
            for dfn in DFN_PATH.glob("*.dfn")
            if dfn.stem not in ["common", "flopy"]
        ]
        metafunc.parametrize("dfn_name", dfn_names, ids=dfn_names)

    if "toml_name" in metafunc.fixturenames:
        convert(DFN_PATH, TOML_PATH)
        dfns = list(DFN_PATH.glob("*.dfn"))
        assert all(
            (TOML_PATH / f"{dfn.stem}.toml").is_file()
            for dfn in dfns
            if "common" not in dfn.stem
        )
        toml_names = [toml.stem for toml in TOML_PATH.glob("*.toml")]
        metafunc.parametrize("toml_name", toml_names, ids=toml_names)


@requires_pkg("boltons")
def test_load_v1(dfn_name):
    with (
        (DFN_PATH / "common.dfn").open() as common_file,
        (DFN_PATH / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common, _ = Dfn._load_v1_flat(common_file)
        dfn = Dfn.load(dfn_file, name=dfn_name, common=common)
        assert any(dfn)


@requires_pkg("boltons")
def test_load_all_v1():
    dfns = Dfn.load_all(DFN_PATH)
    assert any(dfns)


@requires_pkg("boltons")
def test_load_v2(toml_name):
    with (TOML_PATH / f"{toml_name}.toml").open(mode="rb") as toml_file:
        toml = Dfn.load(toml_file, name=toml_name, version=2)
        assert any(toml)


@requires_pkg("boltons")
def test_load_all_v2():
    toml = Dfn.load_all(TOML_PATH, version=2)
    assert any(toml)
