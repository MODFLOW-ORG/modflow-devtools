import inspect
from pathlib import Path

import numpy as np
import pytest
from _pytest.config import ExitCode

proj_root = Path(__file__).parents[1]
module_path = Path(inspect.getmodulename(__file__))
snapshot_array = np.array([1.1, 2.2, 3.3])
snapshots_path = proj_root / "autotest" / "__snapshots__"


def test_binary_array_snapshot(array_snapshot):
    assert array_snapshot == snapshot_array
    snapshot_path = (
        snapshots_path
        / module_path.stem
        / f"{inspect.currentframe().f_code.co_name}.npy"
    )
    assert snapshot_path.is_file()
    assert np.allclose(np.load(snapshot_path), snapshot_array)


# todo: reinstate if/when we support multiple arrays
# def test_binary_array_snapshot_multi(array_snapshot):
#     arrays = {"ascending": snapshot_array, "descending": np.flip(snapshot_array)}
#     assert array_snapshot == arrays
#     snapshot_path = (
#         snapshots_path
#         / module_path.stem
#         / f"{inspect.currentframe().f_code.co_name}.npy"
#     )
#     assert snapshot_path.is_file()
#     assert np.allclose(np.load(snapshot_path)["ascending"], snapshot_array)
#     assert np.allclose(np.load(snapshot_path)["descending"], np.flip(snapshot_array))


def test_text_array_snapshot(text_array_snapshot):
    assert text_array_snapshot == snapshot_array
    snapshot_path = (
        snapshots_path
        / module_path.stem
        / f"{inspect.currentframe().f_code.co_name}.txt"
    )
    assert snapshot_path.is_file()
    assert np.allclose(np.loadtxt(snapshot_path), snapshot_array)


def test_readable_text_array_snapshot(readable_array_snapshot):
    assert readable_array_snapshot == snapshot_array
    snapshot_path = (
        snapshots_path
        / module_path.stem
        / f"{inspect.currentframe().f_code.co_name}.txt"
    )
    assert snapshot_path.is_file()
    assert np.allclose(
        np.fromstring(snapshot_path.read_text().strip("[]\r\n"), sep=" "),
        snapshot_array,
    )


@pytest.mark.meta("test_snapshot_disable")
def test_snapshot_disable_inner(snapshot):
    assert snapshot == "match this!"


@pytest.mark.parametrize("disable", [True, False])
def test_snapshot_disable(disable):
    inner_fn = test_snapshot_disable_inner.__name__
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        inner_fn,
        "-M",
        "test_snapshot_disable",
    ]
    if disable:
        args.append("--snapshot-disable")
    assert pytest.main(args) == (ExitCode.OK if disable else ExitCode.TESTS_FAILED)


@pytest.mark.meta("test_array_snapshot_disable")
def test_array_snapshot_disable_inner(array_snapshot):
    assert array_snapshot == "can you match that?"


@pytest.mark.parametrize("disable", [True, False])
def test_array_snapshot_disable(disable):
    inner_fn = test_array_snapshot_disable_inner.__name__
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        inner_fn,
        "-M",
        "test_array_snapshot_disable",
    ]
    if disable:
        args.append("--snapshot-disable")
    assert pytest.main(args) == (ExitCode.OK if disable else ExitCode.TESTS_FAILED)
