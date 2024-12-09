"""
Pytest markers to toggle tests based on environment conditions.
Occasionally useful to directly assert environment expectations.
"""

from os import environ
from platform import python_version, system
from typing import Optional

from packaging.version import Version

from modflow_devtools.imports import import_optional_dependency
from modflow_devtools.misc import (
    get_current_branch,
    has_exe,
    has_pkg,
    is_connected,
    is_in_ci,
)

pytest = import_optional_dependency("pytest")
py_ver = Version(python_version())


def requires_exe(*exes):
    missing = {exe for exe in exes if not has_exe(exe)}
    return pytest.mark.skipif(
        missing,
        reason=f"missing executable{'s' if len(missing) != 1 else ''}: "
        + ", ".join(missing),
    )


def requires_python(version, bound="lower"):
    if not isinstance(version, str):
        raise ValueError("Version must a string")

    py_tgt = Version(version)
    if bound == "lower":
        return py_ver >= py_tgt
    elif bound == "upper":
        return py_ver <= py_tgt
    elif bound == "exact":
        return py_ver == py_tgt
    else:
        return ValueError(
            f"Invalid bound type: {bound} (use 'upper', 'lower', or 'exact')"
        )


def requires_pkg(*pkgs, name_map: Optional[dict[str, str]] = None):
    missing = {pkg for pkg in pkgs if not has_pkg(pkg, strict=True, name_map=name_map)}
    return pytest.mark.skipif(
        missing,
        reason=f"missing package{'s' if len(missing) != 1 else ''}: "
        + ", ".join(missing),
    )


def requires_platform(platform, ci_only=False):
    return pytest.mark.skipif(
        system().lower() != platform.lower() and (is_in_ci() if ci_only else True),
        reason=f"only compatible with platform: {platform.lower()}",
    )


def excludes_platform(platform, ci_only=False):
    return pytest.mark.skipif(
        system().lower() == platform.lower() and (is_in_ci() if ci_only else True),
        reason=f"not compatible with platform: {platform.lower()}",
    )


def requires_branch(branch):
    current = get_current_branch()
    return pytest.mark.skipif(current != branch, reason=f"must run on branch: {branch}")


def excludes_branch(branch):
    current = get_current_branch()
    return pytest.mark.skipif(
        current == branch, reason=f"can't run on branch: {branch}"
    )


no_parallel = pytest.mark.skipif(
    environ.get("PYTEST_XDIST_WORKER_COUNT"), reason="can't run in parallel"
)


requires_github = pytest.mark.skipif(
    not is_connected("github.com"), reason="github.com is required."
)


requires_spatial_reference = pytest.mark.skipif(
    not is_connected("spatialreference.org"),
    reason="spatialreference.org is required.",
)


# imperative mood renaming, and some aliases

require_exe = requires_exe
require_program = requires_exe
requires_program = requires_exe
require_python = requires_python
require_pkg = requires_pkg
require_package = requires_pkg
requires_package = requires_pkg
require_platform = requires_platform
exclude_platform = excludes_platform
require_branch = requires_branch
exclude_branch = excludes_branch
require_github = requires_github
require_spatial_reference = requires_spatial_reference
