import os
import re
from pathlib import Path

import pytest
from syrupy.constants import SNAPSHOT_DIRNAME
from syrupy.data import Snapshot, SnapshotCollection
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from modflow_devtools.dfns import fetch_dfns

PROJ_ROOT = Path(__file__).parents[1]


class DfnSnapshotExtension(SingleFileSnapshotExtension):
    """One snapshot file per component per version: __snapshots__/v2.0.0.dev2/chf-cdb.yaml"""

    _write_mode = WriteMode.TEXT
    _file_extension = ""

    @classmethod
    def _version_from_testname(cls, testname: str) -> str:
        m = re.search(r"_v(\d+)_(\d+)_(\d+)_dev(\d+)\[", testname)
        if m:
            return f"v{m.group(1)}.{m.group(2)}.{m.group(3)}.dev{m.group(4)}"
        return "unknown"

    @classmethod
    def _fmt_from_testname(cls, testname: str) -> str:
        m = re.search(r"\[(\w+)\]", testname)
        return m.group(1) if m else "txt"

    @classmethod
    def dirname(cls, *, test_location) -> str:
        test_dir = Path(test_location.filepath).parent
        version = cls._version_from_testname(test_location.testname)
        return str(test_dir / SNAPSHOT_DIRNAME / version)

    @classmethod
    def _get_file_basename(cls, *, test_location, index) -> str:
        fmt = cls._fmt_from_testname(test_location.testname)
        return f"{index}.{fmt}"

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0) -> str:
        if isinstance(index, str):
            return index
        return super().get_snapshot_name(test_location=test_location, index=index)

    def _read_snapshot_collection(self, *, snapshot_location: str) -> SnapshotCollection:
        collection = SnapshotCollection(location=snapshot_location)
        collection.add(Snapshot(name=Path(snapshot_location).stem))
        return collection

    def is_snapshot_location(self, *, location: str) -> bool:
        return Path(location).suffix in {".yaml", ".json", ".toml"}


@pytest.fixture
def snapshot(snapshot):
    return snapshot.with_defaults(extension_class=DfnSnapshotExtension)


DFNS_REPO = os.getenv("TEST_DFNS_REPO", "MODFLOW-ORG/modflow6")
DFNS_REF = os.getenv("TEST_DFNS_REF", "65278c938a0c6e742b52fa7398b35a9aea6c0752")


@pytest.fixture(scope="module")
def dfn_dir(module_tmpdir):
    """
    Path to DFN files: $DFNS_PATH if set, otherwise fetched from develop branch
    to a temp dir (for LocalDfnRegistry tests).
    """
    env_var = "DFNS_PATH"
    if dfns_path := os.getenv(env_var):
        dfn_path = Path(dfns_path).expanduser().resolve()
        assert dfn_path.exists(), f"{env_var}={dfns_path} does not exist"
        assert any(dfn_path.glob("*.dfn")), f"{env_var}={dfns_path} empty"
        return dfn_path

    dfns_path = module_tmpdir / "dfns"
    dfns_path.mkdir()
    owner = DFNS_REPO.split("/")[0]
    repo = DFNS_REPO.split("/")[1]
    fetch_dfns(owner, repo, DFNS_REF, dfns_path, verbose=True)
    return dfns_path
