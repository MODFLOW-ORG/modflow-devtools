from pathlib import Path

from modflow_devtools.dfn import Dfn, get_dfns

PROJ_ROOT = Path(__file__).parents[1]
DFN_PATH = PROJ_ROOT / "autotest" / "temp" / "dfn"
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


def test_dfn_load(dfn_name):
    with (
        (DFN_PATH / "common.dfn").open() as common_file,
        (DFN_PATH / f"{dfn_name}.dfn").open() as dfn_file,
    ):
        common, _ = Dfn._load_v1_flat(common_file)
        dfn = Dfn.load(dfn_file, name=dfn_name, common=common)
        assert any(dfn)
