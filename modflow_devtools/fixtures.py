from collections import OrderedDict
from collections.abc import Generator
from itertools import groupby
from os import PathLike, environ
from pathlib import Path
from shutil import copytree, rmtree

from modflow_devtools.imports import import_optional_dependency
from modflow_devtools.misc import get_namefile_paths, get_packages

pytest = import_optional_dependency("pytest")


# fixtures


@pytest.fixture(scope="function")
def function_tmpdir(tmpdir_factory, request) -> Generator[Path, None, None]:
    node_name = (
        request.node.name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("[", "_")
        .replace("]", "_")
    )
    temp = Path(tmpdir_factory.mktemp(node_name))
    yield Path(temp)

    keep = request.config.option.KEEP
    if keep:
        path = Path(keep) / temp.name
        if path.is_dir():
            rmtree(path)
        copytree(temp, path)

    keep_failed = request.config.getoption("--keep-failed")
    if keep_failed and request.node.rep_call.failed:
        path = Path(keep_failed) / temp.name
        if path.is_dir():
            rmtree(path)
        copytree(temp, path)


@pytest.fixture(scope="class")
def class_tmpdir(tmpdir_factory, request) -> Generator[Path, None, None]:
    assert request.cls is not None, (
        "Class-scoped temp dir fixture must be used on class"
    )
    temp = Path(tmpdir_factory.mktemp(request.cls.__name__))
    yield temp

    keep = request.config.option.KEEP
    if keep:
        path = Path(keep) / temp.name
        if path.is_dir():
            rmtree(path)
        copytree(temp, path)


@pytest.fixture(scope="module")
def module_tmpdir(tmpdir_factory, request) -> Generator[Path, None, None]:
    temp = Path(tmpdir_factory.mktemp(request.module.__name__))
    yield temp

    keep = request.config.option.KEEP
    if keep:
        path = Path(keep) / temp.name
        if path.is_dir():
            rmtree(path)
        copytree(temp, path)


@pytest.fixture(scope="session")
def session_tmpdir(tmpdir_factory, request) -> Generator[Path, None, None]:
    temp = Path(tmpdir_factory.mktemp(request.config.rootpath.name))
    yield temp

    keep = request.config.option.KEEP
    if keep:
        path = Path(keep) / temp.name
        if path.is_dir():
            rmtree(path)
        copytree(temp, path)


@pytest.fixture
def repos_path() -> Path | None:
    """Path to directory containing test model and example repositories"""
    path = environ.get("REPOS_PATH", None)
    return Path(path) if path else None


@pytest.fixture
def tabular(request) -> str:
    tab = request.config.option.TABULAR
    if tab not in ["raw", "recarray", "dataframe"]:
        raise ValueError(f"Unsupported value for --tabular: {tab}")
    return tab


# configuration hooks


def pytest_addoption(parser):
    parser.addoption(
        "-K",
        "--keep",
        action="store",
        default=None,
        dest="KEEP",
        help="Move the contents of temporary test directories to "
        "correspondingly named subdirectories at the given "
        "location after tests complete. This option can be used "
        "to exclude test results from automatic cleanup, "
        "e.g. for manual inspection. The provided path is "
        "created if it does not already exist. An error is "
        "thrown if any matching files already exist.",
    )

    parser.addoption(
        "--keep-failed",
        action="store",
        default=None,
        help="Move the contents of temporary test directories to "
        "correspondingly named subdirectories at the given "
        "location if the test case fails. This option saves "
        "the outputs of failed tests in the "
        "given location. The path is created if it doesn't "
        "already exist. An error is thrown if files with the "
        "same names already exist in the given location.",
    )

    parser.addoption(
        "-S",
        "--smoke",
        action="store_true",
        default=False,
        help="Run only smoke tests (should complete in <1 minute).",
    )

    parser.addoption(
        "-M",
        "--meta",
        action="store",
        metavar="NAME",
        help="Indicates a test should only be run by other tests (e.g., "
        "to test framework or fixtures).",
    )

    parser.addoption(
        "--model",
        action="append",
        type=str,
        help="Select a subset of models to run.",
    )

    parser.addoption(
        "--package",
        action="append",
        type=str,
        help="Select a subset of packages to run.",
    )

    parser.addoption(
        "-T",
        "--tabular",
        action="store",
        default="raw",
        dest="TABULAR",
        help="Configure tabular data representation for model input. "
        "Select 'raw', 'recarray', or 'dataframe'.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "meta(name): run only by other tests",
    )


def pytest_runtest_setup(item):
    # skip meta-tests unless specified
    meta = item.config.getoption("--meta")
    metagroups = [mark.args[0] for mark in item.iter_markers(name="meta")]
    if metagroups and meta not in metagroups:
        pytest.skip()

    # smoke tests are \ {slow U example U regression}
    smoke = item.config.getoption("--smoke")
    slow = list(item.iter_markers(name="slow"))
    example = list(item.iter_markers(name="example"))
    regression = list(item.iter_markers(name="regression"))
    if smoke and (slow or example or regression):
        pytest.skip()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    # this is necessary so temp dir fixtures can
    # inspect test results and check for failure
    # (see https://doc.pytest.org/en/latest/example/simple.html#making-test-result-information-available-in-fixtures)
    outcome = yield
    rep = outcome.get_result()

    # report attribute for each phase (setup, call, teardown)
    # we're only interested in result of the function call
    setattr(item, "rep_" + rep.when, rep)


def pytest_generate_tests(metafunc):
    # user can filter by model name or packages the model uses
    models_selected = metafunc.config.getoption("--model", None)
    packages_selected = metafunc.config.getoption("--package", None)

    # user can specify a path to folder containing model repos
    repos_path = environ.get("REPOS_PATH")
    if repos_path is not None:
        repos_path = Path(repos_path)
    else:
        # by default, assume external repositories are
        # level (side-by-side) on the filesystem with
        # the consuming project. also assume tests are
        # run from <proj root>/autotest.
        #
        # external model repo directories are expected
        # to be named identically to the GitHub repos,
        # e.g. "modflow6-testmodels", with an optional
        # ".git" suffix appended to the directory name.
        #
        # if model repositories are not found in either
        # the default location or in REPOS_PATH, tests
        # requesting these fixtures will be skipped.
        repos_path = Path.cwd().parent.parent

    def get_repo_path(repo_name: str) -> Path | None:
        """Get the path for the repository with the given name
        (optionally with .git suffix), or None if not found"""
        repo_path = repos_path / repo_name
        if not repo_path.is_dir():
            repo_path = repos_path / (repo_name + ".git")
        if not repo_path.is_dir():
            repo_path = None
        return repo_path

    key = "test_model_mf6"
    if key in metafunc.fixturenames:
        repo_path = get_repo_path("modflow6-testmodels")
        namefile_paths = (
            get_namefile_paths(
                repo_path / "mf6",
                prefix="test",
                excluded=[],
                selected=models_selected,
                packages=packages_selected,
            )
            if repo_path
            else []
        )
        metafunc.parametrize(key, namefile_paths, ids=[str(m) for m in namefile_paths])

    key = "test_model_mf5to6"
    if key in metafunc.fixturenames:
        repo_path = get_repo_path("modflow6-testmodels")
        namefile_paths = (
            get_namefile_paths(
                repo_path / "mf5to6",
                prefix="test",
                namefile="*.nam",
                excluded=[],
                selected=models_selected,
                packages=packages_selected,
            )
            if repo_path
            else []
        )
        metafunc.parametrize(key, namefile_paths, ids=[str(m) for m in namefile_paths])

    key = "large_test_model"
    if key in metafunc.fixturenames:
        repo_path = get_repo_path("modflow6-largetestmodels")
        namefile_paths = (
            get_namefile_paths(
                repo_path,
                prefix="test",
                namefile="mfsim.nam",
                excluded=[],
                selected=models_selected,
                packages=packages_selected,
            )
            if repo_path
            else []
        )
        metafunc.parametrize(key, namefile_paths, ids=[str(m) for m in namefile_paths])

    key = "example_scenario"
    if key in metafunc.fixturenames:
        repo_path = get_repo_path("modflow6-examples")

        def is_nested(namfile_path: PathLike) -> bool:
            p = Path(namfile_path)
            if not p.is_file() or not p.name.endswith(".nam"):
                raise ValueError(f"Expected namefile path, got {p}")

            return p.parent.parent.name != "examples"

        def example_path_from_namfile_path(path: PathLike) -> Path:
            p = Path(path)
            if not p.is_file() or not p.name.endswith(".nam"):
                raise ValueError(f"Expected namefile path, got {p}")

            return p.parent.parent if is_nested(p) else p.parent

        def example_name_from_namfile_path(path: PathLike) -> str:
            return example_path_from_namfile_path(path).name

        def group_examples(namefile_paths) -> dict[str, list[Path]]:
            d = OrderedDict()
            for name, paths in groupby(
                namefile_paths, key=example_name_from_namfile_path
            ):
                # sort alphabetically (gwf < gwt)
                nfpaths = sorted(paths)

                # skip if no models found
                if len(nfpaths) == 0:
                    continue

                d[name] = nfpaths

            return d

        def get_examples():
            # find MODFLOW 6 namfiles
            examples_path = repo_path / "examples"
            namfiles = (
                list(examples_path.rglob("mfsim.nam")) if examples_path.is_dir() else []
            )

            # group by scenario
            examples = group_examples(namfiles)

            # filter by example name (optional)
            if models_selected:
                examples = {
                    name: nfps
                    for name, nfps in examples.items()
                    if any(s in name for s in models_selected)
                }

            # filter by package (optional)
            if packages_selected:
                filtered = []
                for name, namefiles in examples.items():
                    ftypes = []
                    for namefile in namefiles:
                        ftype = get_packages(namefile)
                        if ftype not in ftypes:
                            ftypes += ftype
                    if len(ftypes) > 0:
                        ftypes = [item.upper() for item in ftypes]
                        for pkg in packages_selected:
                            if pkg in ftypes:
                                filtered.append(name)
                                break
                examples = {
                    name: nfps for name, nfps in examples.items() if name in filtered
                }

            # exclude mf6gwf and mf6gwt subdirs
            examples = {
                name: nfps
                for name, nfps in examples.items()
                if name not in ["mf6gwf", "mf6gwt"]
            }

            return examples

        example_scenarios = get_examples() if repo_path else {}
        metafunc.parametrize(
            key,
            list(example_scenarios.items()),
            ids=list(example_scenarios.keys()),
        )
