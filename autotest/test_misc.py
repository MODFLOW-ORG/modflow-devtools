import os
import re
import shutil
from os import environ
from pathlib import Path
from time import sleep

import pytest

from modflow_devtools.misc import (
    get_env,
    get_model_paths,
    get_namefile_paths,
    get_packages,
    has_package,
    has_pkg,
    set_dir,
    set_env,
    timed,
)


def test_set_dir(tmp_path):
    assert Path.cwd() != tmp_path
    with set_dir(tmp_path):
        assert Path.cwd() == tmp_path
    assert Path.cwd() != tmp_path


def test_set_env():
    # test adding a variable
    key = "TEST_ENV"
    val = "test"
    assert environ.get(key) is None
    with set_env(**{key: val}):
        assert environ.get(key) == val
    with set_env(TEST_ENV=val):
        assert environ.get(key) == val

    # test removing a variable
    with set_env(**{key: val}):
        with set_env(key):
            assert environ.get(key) is None


_repos_path_str = environ.get("REPOS_PATH")
if _repos_path_str is None:
    _repos_path: Path = Path(__file__).parent.parent.parent.parent
else:
    _repos_path = Path(_repos_path_str).expanduser().absolute()
_testmodels_repo_path = _repos_path / "modflow6-testmodels"
_testmodels_repo_paths_mf6 = sorted((_testmodels_repo_path / "mf6").glob("test*"))
_testmodels_repo_paths_mf5to6 = sorted((_testmodels_repo_path / "mf5to6").glob("test*"))
_largetestmodels_repo_path = _repos_path / "modflow6-largetestmodels"
_largetestmodel_paths = sorted(_largetestmodels_repo_path.glob("test*"))
_examples_repo_path = _repos_path / "modflow6-examples"
_examples_path = _examples_repo_path / "examples"
_example_paths = sorted(_examples_path.glob("ex-*")) if _examples_path.is_dir() else []


@pytest.mark.skipif(
    not any(_testmodels_repo_paths_mf6), reason="mf6 test models not found"
)
def test_get_packages():
    model_path = _testmodels_repo_paths_mf6[0]

    # simulation namefile
    namefile_path = model_path / "mfsim.nam"
    packages = get_packages(namefile_path)
    assert model_path.name == "test001a_Tharmonic"
    assert set(packages) >= {"tdis", "gwf", "ims", "npf", "chd", "oc", "dis"}

    # model namefile
    namefile_path = model_path / "flow15.nam"
    packages = get_packages(namefile_path)
    assert model_path.name == "test001a_Tharmonic"
    assert set(packages) >= {"npf", "chd", "oc", "dis"}
    assert "tdis" not in packages
    assert "gwf" not in packages
    assert "ims" not in packages


@pytest.mark.skipif(
    not any(_testmodels_repo_paths_mf6), reason="mf6 test models not found"
)
def test_get_packages_fails_on_invalid_namefile(module_tmpdir):
    model_path = _testmodels_repo_paths_mf6[0]
    new_model_path = module_tmpdir / model_path.name
    namefile_path = new_model_path / "mfsim.nam"
    shutil.copytree(model_path, new_model_path)

    # invalid gwf namefile reference:
    # result should only contain packages from mfsim.nam
    lines = []
    for line in namefile_path.read_text().splitlines():
        if "GWF6" in line:
            line = line.replace("GWF6", "GWF6  garbage")
        lines.append(line)
    namefile_path.write_text("\n".join(lines))

    with pytest.warns(UserWarning, match="Invalid namefile format"):
        assert set(get_packages(namefile_path)) == {"gwf", "tdis", "ims"}

    # entirely unparsable namefile - result should be empty
    namefile_path.write_text("garbage\n" * 20)
    assert get_packages(namefile_path) == []


@pytest.mark.skipif(not any(_example_paths), reason="examples not found")
def test_has_package():
    model_path = _testmodels_repo_paths_mf6[0]
    namefile_path = model_path / "mfsim.nam"
    assert model_path.name == "test001a_Tharmonic"
    assert has_package(namefile_path, "tdis")
    assert has_package(namefile_path, "gwf")
    assert has_package(namefile_path, "ims")
    assert has_package(namefile_path, "npf")
    assert has_package(namefile_path, "chd")
    assert has_package(namefile_path, "oc")
    assert has_package(namefile_path, "dis")
    assert not has_package(namefile_path, "gwt")
    assert not has_package(namefile_path, "wel")


def get_expected_model_dirs(path, pattern="mfsim.nam") -> list[Path]:
    folders = []
    for root, dirs, _ in os.walk(path):
        for d in dirs:
            p = Path(root) / d
            if any(p.glob(pattern)):
                folders.append(p)
    return sorted(set(folders))


def get_expected_namefiles(path, pattern="mfsim.nam") -> list[Path]:
    folders: list[Path] = []
    for root, dirs, _ in os.walk(path):
        for d in dirs:
            p = Path(root) / d
            found = list(p.glob(pattern))
            folders = folders + found
    return sorted(set(folders))


@pytest.mark.skipif(not any(_example_paths), reason="modflow6-examples repo not found")
def test_get_model_paths_examples():
    expected_paths = get_expected_model_dirs(_examples_path)
    paths = get_model_paths(_examples_path)
    assert sorted(paths) == sorted(set(paths))  # no duplicates
    assert set(expected_paths) == set(paths)

    expected_paths = get_expected_model_dirs(_examples_path, "*.nam")
    paths = get_model_paths(_examples_path, namefile="*.nam")
    assert sorted(paths) == sorted(set(paths))
    assert set(expected_paths) == set(paths)


@pytest.mark.skipif(
    not any(_largetestmodel_paths), reason="modflow6-largetestmodels not found"
)
def test_get_model_paths_largetestmodels():
    expected_paths = get_expected_model_dirs(_examples_path)
    paths = get_model_paths(_examples_path)
    assert sorted(paths) == sorted(set(paths))
    assert set(expected_paths) == set(paths)

    expected_paths = get_expected_model_dirs(_examples_path)
    paths = get_model_paths(_examples_path)
    assert sorted(paths) == sorted(set(paths))
    assert set(expected_paths) == set(paths)


@pytest.mark.skipif(
    not any(_largetestmodel_paths) or not any(_example_paths),
    reason="repos not found",
)
@pytest.mark.parametrize(
    "models", [(_examples_path, 63), (_largetestmodels_repo_path, 16)]
)
def test_get_model_paths_exclude_patterns(models):
    path, expected_count = models
    paths = get_model_paths(path, excluded=["gwt"])
    assert len(paths) >= expected_count


@pytest.mark.skipif(not any(_example_paths), reason="modflow6-examples repo not found")
def test_get_namefile_paths_examples():
    expected_paths = get_expected_namefiles(_examples_path)
    paths = get_namefile_paths(_examples_path)
    assert paths == sorted(set(paths))
    assert set(expected_paths) == set(paths)

    expected_paths = get_expected_namefiles(_examples_path, "*.nam")
    paths = get_namefile_paths(_examples_path, namefile="*.nam")
    assert paths == sorted(set(paths))
    assert set(expected_paths) == set(paths)


@pytest.mark.skipif(
    not any(_largetestmodel_paths), reason="modflow6-largetestmodels not found"
)
def test_get_namefile_paths_largetestmodels():
    expected_paths = get_expected_namefiles(_largetestmodels_repo_path)
    paths = get_namefile_paths(_largetestmodels_repo_path)
    assert paths == sorted(set(paths))
    assert set(expected_paths) == set(paths)

    expected_paths = get_expected_namefiles(_largetestmodels_repo_path)
    paths = get_namefile_paths(_largetestmodels_repo_path)
    assert paths == sorted(set(paths))
    assert set(expected_paths) == set(paths)


@pytest.mark.skipif(
    not any(_largetestmodel_paths) or not any(_example_paths),
    reason="repos not found",
)
@pytest.mark.parametrize(
    "models", [(_examples_path, 43), (_largetestmodels_repo_path, 19)]
)
def test_get_namefile_paths_exclude_patterns(models):
    path, expected_count = models
    paths = get_namefile_paths(path, excluded=["gwf"])
    assert len(paths) >= expected_count


@pytest.mark.skipif(not any(_example_paths), reason="examples not found")
def test_get_namefile_paths_select_prefix():
    paths = get_namefile_paths(_examples_path, prefix="ex2")
    assert not any(paths)

    paths = get_namefile_paths(_examples_path, prefix="ex")
    assert any(paths)


@pytest.mark.skipif(not any(_example_paths), reason="examples not found")
def test_get_namefile_paths_select_patterns():
    paths = get_namefile_paths(_examples_path, selected=["gwf"])
    assert len(paths) >= 70


@pytest.mark.skipif(not any(_example_paths), reason="examples not found")
def test_get_namefile_paths_select_packages():
    paths = get_namefile_paths(_examples_path, packages=["wel"])
    assert len(paths) >= 43


def test_has_pkg():
    assert has_pkg("pytest")
    assert not has_pkg("notapkg")


def test_timed1(capfd):
    def sleep1():
        sleep(0.001)

    timed(sleep1)()
    cap = capfd.readouterr()
    print(cap.out)
    assert re.match(r"sleep1 took \d+\.\d+ ms", cap.out)


def test_timed2(capfd):
    @timed
    def sleep1dec():
        sleep(0.001)

    sleep1dec()
    cap = capfd.readouterr()
    print(cap.out)
    assert re.match(r"sleep1dec took \d+\.\d+ ms", cap.out)


def test_get_env():
    assert get_env("NO_VALUE") is None

    with set_env(TEST_VALUE=str(True)):
        assert get_env("NO_VALUE", True)
        assert get_env("TEST_VALUE")
        assert get_env("TEST_VALUE", default=False)
        assert get_env("TEST_VALUE", default=1) == 1

    with set_env(TEST_VALUE=str(1)):
        assert get_env("NO_VALUE", 1) == 1
        assert get_env("TEST_VALUE") == 1
        assert get_env("TEST_VALUE", default=2) == 1
        assert get_env("TEST_VALUE", default=2.1) == 2.1

    with set_env(TEST_VALUE=str(1.1)):
        assert get_env("NO_VALUE", 1.1) == 1.1
        assert get_env("TEST_VALUE") == 1.1
        assert get_env("TEST_VALUE", default=2.1) == 1.1
        assert not get_env("TEST_VALUE", default=False)
