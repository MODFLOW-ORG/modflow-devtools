import platform
from os import environ
from pathlib import Path

import pytest

from modflow_devtools.build import meson_build
from modflow_devtools.markers import requires_exe

_repos_path = environ.get("REPOS_PATH")
if _repos_path is None:
    _repos_path = Path(__file__).parent.parent.parent.parent
_repos_path = Path(_repos_path).expanduser().absolute()
_project_root_path = Path(__file__).parent.parent.parent.parent
_modflow6_repo_path = _repos_path / "modflow6"
_system = platform.system()
_exe_ext = ".exe" if _system == "Windows" else ""
_lib_ext = (
    ".so" if _system == "Linux" else (".dylib" if _system == "Darwin" else ".dll")
)


@requires_exe("meson", "ninja")
@pytest.mark.skipif(
    not _modflow6_repo_path.is_dir(), reason="modflow6 repository not found"
)
def test_meson_build(tmp_path):
    build_path = tmp_path / "builddir"
    bin_path = tmp_path / "bin"

    meson_build(_modflow6_repo_path, build_path, bin_path)

    assert (bin_path / f"mf6{_exe_ext}").is_file()
    assert (bin_path / f"zbud6{_exe_ext}").is_file()
    assert (bin_path / f"mf5to6{_exe_ext}").is_file()
    assert (bin_path / f"libmf6{_lib_ext}").is_file()
