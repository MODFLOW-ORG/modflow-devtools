import inspect
import platform
from pathlib import Path

import pytest
from _pytest.config import ExitCode

system = platform.system()
proj_root = Path(__file__).parents[1]
module_name = inspect.getmodulename(__file__)
assert module_name is not None  # appease mypy
module_path = Path(module_name)


# test temporary directory fixtures


def test_tmpdirs(function_tmpdir, module_tmpdir):
    # function-scoped temporary directory
    assert isinstance(function_tmpdir, Path)
    assert function_tmpdir.is_dir()
    assert inspect.currentframe().f_code.co_name in function_tmpdir.stem

    # module-scoped temp dir (accessible to other tests in the script)
    assert module_tmpdir.is_dir()
    assert "test" in module_tmpdir.stem


def test_function_scoped_tmpdir(function_tmpdir):
    assert isinstance(function_tmpdir, Path)
    assert function_tmpdir.is_dir()
    assert inspect.currentframe().f_code.co_name in function_tmpdir.stem


@pytest.mark.parametrize("name", ["noslash", "forward/slash", "back\\slash"])
def test_function_scoped_tmpdir_slash_in_name(function_tmpdir, name):
    assert isinstance(function_tmpdir, Path)
    assert function_tmpdir.is_dir()

    # node name might have slashes if test function is parametrized
    # (e.g., test_function_scoped_tmpdir_slash_in_name[a/slash])
    replaced1 = (
        name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("[", "")
        .replace("]", "")
    )
    replaced2 = (
        name.replace("/", "_")
        .replace("\\", "__")
        .replace(":", "_")
        .replace("[", "")
        .replace("]", "")
    )
    assert (
        f"{inspect.currentframe().f_code.co_name}_{replaced1}_" in function_tmpdir.stem
        or f"{inspect.currentframe().f_code.co_name}_{replaced2}_"
        in function_tmpdir.stem
    )


class TestClassScopedTmpdir:
    fname = "hello.txt"

    @pytest.fixture(autouse=True)
    def setup(self, class_tmpdir):
        file = class_tmpdir / self.fname
        file.write_text("hello, class-scoped tmpdir")

    def test_class_scoped_tmpdir(self, class_tmpdir):
        assert isinstance(class_tmpdir, Path)
        assert class_tmpdir.is_dir()
        assert self.__class__.__name__ in class_tmpdir.stem
        assert (class_tmpdir / self.fname).is_file()


def test_module_scoped_tmpdir(module_tmpdir):
    assert isinstance(module_tmpdir, Path)
    assert module_tmpdir.is_dir()
    assert module_path.stem in module_tmpdir.name


def test_session_scoped_tmpdir(session_tmpdir):
    assert isinstance(session_tmpdir, Path)
    assert session_tmpdir.is_dir()


# test CLI arguments --keep (-K) and --keep-failed for temp dir fixtures

test_keep_fname = "hello.txt"


@pytest.mark.meta("test_keep")
def test_keep_function_scoped_tmpdir_inner(function_tmpdir):
    file = function_tmpdir / test_keep_fname
    file.write_text("hello, function-scoped tmpdir")


@pytest.mark.meta("test_keep")
class TestKeepClassScopedTmpdirInner:
    def test_keep_class_scoped_tmpdir_inner(self, class_tmpdir):
        file = class_tmpdir / test_keep_fname
        file.write_text("hello, class-scoped tmpdir")


@pytest.mark.meta("test_keep")
def test_keep_module_scoped_tmpdir_inner(module_tmpdir):
    file = module_tmpdir / test_keep_fname
    file.write_text("hello, module-scoped tmpdir")


@pytest.mark.meta("test_keep")
def test_keep_session_scoped_tmpdir_inner(session_tmpdir):
    file = session_tmpdir / test_keep_fname
    file.write_text("hello, session-scoped tmpdir")


@pytest.mark.parametrize("arg", ["--keep", "-K"])
def test_keep_function_scoped_tmpdir(function_tmpdir, arg):
    inner_fn = test_keep_function_scoped_tmpdir_inner.__name__
    file_path = function_tmpdir / f"{inner_fn}0" / test_keep_fname
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        inner_fn,
        "-M",
        "test_keep",
        arg,
        function_tmpdir,
    ]
    assert pytest.main(args) == ExitCode.OK
    assert file_path.is_file()
    first_modified = file_path.stat().st_mtime

    assert pytest.main(args) == ExitCode.OK
    assert file_path.is_file()
    second_modified = file_path.stat().st_mtime

    # make sure contents were overwritten
    assert first_modified < second_modified


@pytest.mark.parametrize("arg", ["--keep", "-K"])
def test_keep_class_scoped_tmpdir(tmp_path, arg):
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        TestKeepClassScopedTmpdirInner.test_keep_class_scoped_tmpdir_inner.__name__,
        "-M",
        "test_keep",
        arg,
        tmp_path,
    ]
    assert pytest.main(args) == ExitCode.OK
    assert (
        tmp_path / f"{TestKeepClassScopedTmpdirInner.__name__}0" / test_keep_fname
    ).is_file()


@pytest.mark.parametrize("arg", ["--keep", "-K"])
def test_keep_module_scoped_tmpdir(tmp_path, arg):
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        test_keep_module_scoped_tmpdir_inner.__name__,
        "-M",
        "test_keep",
        arg,
        tmp_path,
    ]
    assert pytest.main(args) == ExitCode.OK
    this_path = Path(__file__)
    keep_path = tmp_path / f"{this_path.parent.name}.{this_path.stem}0"
    assert test_keep_fname in [f.name for f in keep_path.glob("*")]


@pytest.mark.parametrize("arg", ["--keep", "-K"])
def test_keep_session_scoped_tmpdir(tmp_path, arg, request):
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        test_keep_session_scoped_tmpdir_inner.__name__,
        "-M",
        "test_keep",
        arg,
        tmp_path,
    ]
    assert pytest.main(args) == ExitCode.OK
    assert (tmp_path / f"{request.config.rootpath.name}0" / test_keep_fname).is_file()


@pytest.mark.meta("test_keep_failed")
def test_keep_failed_function_scoped_tmpdir_inner(function_tmpdir):
    file = function_tmpdir / test_keep_fname
    file.write_text("hello, function-scoped tmpdir")

    raise AssertionError("oh no")


@pytest.mark.parametrize("keep", [True, False])
def test_keep_failed_function_scoped_tmpdir(function_tmpdir, keep):
    inner_fn = test_keep_failed_function_scoped_tmpdir_inner.__name__
    args = [__file__, "-v", "-s", "-k", inner_fn, "-M", "test_keep_failed"]
    if keep:
        args += ["--keep-failed", function_tmpdir]
    assert pytest.main(args) == ExitCode.TESTS_FAILED

    kept_file = (function_tmpdir / f"{inner_fn}0" / test_keep_fname).is_file()
    assert kept_file if keep else not kept_file


# test meta-test marker and CLI argument --meta (-M)


@pytest.mark.meta("test_meta")
def test_meta_inner():
    pass


class TestMeta:
    def pytest_terminal_summary(self, terminalreporter):
        stats = terminalreporter.stats
        assert "failed" not in stats

        passed = [test.head_line for test in stats["passed"]]
        assert len(passed) == 1
        assert test_meta_inner.__name__ in passed

        deselected = [fn.name for fn in stats["deselected"]]
        assert len(deselected) > 0


def test_meta():
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        test_meta_inner.__name__,
        "-M",
        "test_meta",
    ]
    assert pytest.main(args, plugins=[TestMeta()]) == ExitCode.OK


# test tabular data format fixture


test_tabular_fname = "tabular.txt"


@pytest.mark.meta("test_tabular")
def test_tabular_inner(function_tmpdir, tabular):
    file = function_tmpdir / test_tabular_fname
    file.write_text(str(tabular))


@pytest.mark.parametrize("tabular", ["raw", "recarray", "dataframe"])
@pytest.mark.parametrize("arg", ["--tabular", "-T"])
def test_tabular(tabular, arg, function_tmpdir):
    inner_fn = test_tabular_inner.__name__
    args = [
        __file__,
        "-v",
        "-s",
        "-k",
        inner_fn,
        arg,
        tabular,
        "--keep",
        function_tmpdir,
        "-M",
        "test_tabular",
    ]
    assert pytest.main(args) == ExitCode.OK
    file = next(function_tmpdir.rglob(test_tabular_fname))
    assert tabular == file.read_text()
