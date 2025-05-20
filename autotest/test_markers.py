from os import environ
from platform import python_version, system
from shutil import which

import pytest
from packaging.version import Version

from modflow_devtools.markers import (
    excludes_platform,
    no_parallel,
    require_exe,
    require_package,
    require_platform,
    require_program,
    require_python,
    requires_exe,
    requires_package,
    requires_platform,
    requires_program,
    requires_python,
)

exe = "pytest"
pkg = exe


@requires_exe(exe)
def test_require_exe():
    assert which(exe)
    require_exe(exe)
    require_program(exe)
    requires_program(exe)


exes = [exe, "python"]


@require_exe(*exes)
def test_require_exe_multiple():
    assert all(which(exe) for exe in exes)


@requires_package(pkg)
def test_requires_pkg():
    import numpy

    assert numpy is not None
    require_package(pkg)


@requires_package(pkg, "pluggy")
def test_requires_pkg_multiple():
    import pluggy
    import pytest

    assert pluggy is not None and pytest is not None


@requires_platform("Windows")
def test_requires_platform():
    assert system() == "Windows"
    require_platform("Windows")


@excludes_platform("Darwin", ci_only=True)
def test_requires_platform_ci_only():
    if "CI" in environ:
        assert system() != "Darwin"


py_ver = python_version()


@pytest.mark.parametrize("version", ["3.12", "3.11"])
def test_requires_python(version):
    if Version(py_ver) >= Version(version):
        assert requires_python(version)
        assert require_python(version)


@no_parallel
@requires_package("pytest-xdist", name_map={"pytest-xdist": "xdist"})
def test_no_parallel(worker_id):
    """
    Should only run with xdist disabled, in which case:
        - xdist environment variables are not set
        - worker_id is 'master' (assuming xdist is installed)

    See https://pytest-xdist.readthedocs.io/en/stable/how-to.html#identifying-the-worker-process-during-a-test.
    """

    assert environ.get("PYTEST_XDIST_WORKER") is None
    assert worker_id == "master"
