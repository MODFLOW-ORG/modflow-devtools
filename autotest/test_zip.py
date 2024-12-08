import os
import shutil
import sys
import zipfile
from pathlib import Path
from pprint import pprint
from shutil import which
from zipfile import ZipFile

import pytest

from modflow_devtools.markers import excludes_platform
from modflow_devtools.misc import get_suffixes, set_dir
from modflow_devtools.zip import MFZipFile

ext, _ = get_suffixes(sys.platform)
exe_stem = "pytest"
exe_path = Path(which(exe_stem))
exe_name = f"{exe_stem}{ext}"


def test_compressall(function_tmpdir):
    zip_file = function_tmpdir / "output.zip"
    input_dir = function_tmpdir / "input"
    input_dir.mkdir()
    file = input_dir / "data.txt"
    file.write_text("hello world")

    MFZipFile.compressall(str(zip_file), dir_pths=str(input_dir))
    pprint(list(function_tmpdir.iterdir()))
    assert zip_file.exists()

    output_dir = function_tmpdir / "output"
    output_dir.mkdir()
    ZipFile(zip_file).extractall(path=str(output_dir))
    pprint(list(output_dir.iterdir()))
    assert (output_dir / "data.txt").is_file()


@pytest.fixture(scope="module")
def empty_archive(module_tmpdir) -> Path:
    # https://stackoverflow.com/a/25195628/6514033
    data = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"  # noqa: E501
    path = module_tmpdir / "empty.zip"
    path.write_bytes(data)
    yield path


def test_extractall_empty(empty_archive, function_tmpdir):
    zf = MFZipFile(empty_archive, "r")
    zf.extractall(str(function_tmpdir))
    assert not any(function_tmpdir.iterdir())


@pytest.fixture(scope="module")
def archive(module_tmpdir) -> Path:
    zip_path = module_tmpdir / "nonempty.zip"
    shutil.copy(exe_path, module_tmpdir)
    with set_dir(module_tmpdir):
        zip = MFZipFile(zip_path.name, "w")
        zip.write(exe_path.name, compress_type=zipfile.ZIP_DEFLATED)
        zip.close()
    yield zip_path


@pytest.mark.parametrize("mf", [True, False])
@excludes_platform("Windows")
def test_extractall_preserves_execute_permission(function_tmpdir, archive, mf):
    zip = MFZipFile(archive) if mf else ZipFile(archive)
    zip.extractall(path=str(function_tmpdir))
    path = function_tmpdir / exe_name
    assert path.is_file()
    assert os.access(path, os.X_OK) == mf
