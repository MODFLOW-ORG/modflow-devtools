import importlib
import socket
import sys
import traceback
from _warnings import warn
from ast import literal_eval
from contextlib import contextmanager
from functools import wraps
from importlib import metadata
from os import PathLike, chdir, environ
from pathlib import Path, PurePosixPath
from shutil import which
from subprocess import run
from timeit import timeit
from typing import Optional
from urllib import request
from urllib.error import URLError


@contextmanager
def set_dir(path: PathLike):
    origin = Path.cwd()
    wrkdir = Path(path).expanduser().resolve()

    try:
        chdir(path)
        print(f"Changed to working directory: {wrkdir} (previously: {origin})")
        yield
    finally:
        chdir(origin)
        print(f"Returned to previous directory: {origin}")


class add_sys_path:
    """
    Context manager to add temporarily to the system path.

    Adapted from https://stackoverflow.com/a/39855753/6514033.
    """

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        sys.path.insert(0, self.path)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            sys.path.remove(self.path)
        except ValueError:
            pass


def get_ostag() -> str:
    """
    Determine operating system tag from sys.platform.

    .. deprecated:: 1.1.0
        Use ``ostags.get_modflow_ostag()`` instead.
    """
    if sys.platform.startswith("linux"):
        return "linux"
    elif sys.platform.startswith("win"):
        return "win" + ("64" if sys.maxsize > 2**32 else "32")
    elif sys.platform.startswith("darwin"):
        return "mac"
    raise ValueError(f"platform {sys.platform!r} not supported")


def get_suffixes(ostag) -> tuple[str, str]:
    """
    Returns executable and library suffixes for the
    given OS (as returned by sys.platform)

    .. deprecated:: 1.1.0
        Use ``ostags.get_binary_suffixes()`` instead.
    """

    tag = ostag.lower()

    if tag in ["win32", "win64"]:
        return ".exe", ".dll"
    elif tag == "linux":
        return "", ".so"
    elif tag == "mac" or tag == "darwin":
        return "", ".dylib"
    else:
        raise KeyError(f"unrecognized OS tag: {ostag!r}")


def run_cmd(*args, verbose=False, **kwargs):
    """
    Run any command, return tuple (stdout, stderr, returncode).
    """
    args = [str(g) for g in args]
    if verbose:
        print("running: " + " ".join(args))
    proc = run(args, capture_output=True, text=True, **kwargs)
    stdout = proc.stdout
    stderr = proc.stderr
    returncode = proc.returncode
    if verbose:
        print(f"stdout:\n{stdout}")
        print(f"stderr:\n{stderr}")
        print(f"returncode: {returncode}")
    return stdout, stderr, returncode


def run_py_script(script, *args, verbose=False):
    """Run a Python script, return tuple (stdout, stderr, returncode)."""
    return run_cmd(
        sys.executable, script, *args, verbose=verbose, cwd=Path(script).parent
    )


def get_current_branch() -> str:
    """
    Tries to determine the name of the current branch, first by the GITHUB_REF
    environment variable, then by asking ``git`` if GITHUB_REF is not set.

    Returns
    -------
    str
        name of the current branch

    Raises
    ------
    RuntimeError
        if ``git`` is not available
    ValueError
        if the current branch could not be determined
    """

    # check if on GitHub Actions CI
    if ref := environ.get("GITHUB_REF"):
        return PurePosixPath(ref).name

    # otherwise ask git about it
    if not which("git"):
        raise RuntimeError("'git' required to determine current branch")
    stdout, stderr, code = run_cmd("git", "branch", "--show-current")
    if code == 0 and stdout:
        return stdout.strip()
    raise ValueError(f"Could not determine current branch: {stderr}")


def get_packages(namefile_path: PathLike) -> list[str]:
    """
    Return a list of packages used by the simulation
    or model defined in the given namefile. The namefile
    may be for an entire simulation or  for a GWF or GWT
    model. If a simulation namefile is given, packages
    used in its component  model namefiles will be included.

    Parameters
    ----------
    namefile_path : PathLike
        path to MODFLOW 6 simulation or model name file

    Returns
    -------
    list
        a list of packages used by the simulation or model
    """

    packages = []
    path = Path(namefile_path).expanduser().resolve()
    lines = path.read_text().splitlines()
    gwf_lines = [ln for ln in lines if ln.strip().lower().startswith("gwf6 ")]
    gwt_lines = [ln for ln in lines if ln.strip().lower().startswith("gwt6 ")]

    def parse_model_namefile(line):
        nf_path = [path.parent / s for s in line.split(" ") if s != ""][1]
        if nf_path.suffix != ".nam":
            raise ValueError(
                "Failed to parse GWF or GWT model namefile "
                f"from simulation namefile line: {line}"
            )
        return nf_path

    # load model namefiles
    try:
        for line in gwf_lines:
            packages = packages + get_packages(parse_model_namefile(line)) + ["gwf"]
        for line in gwt_lines:
            packages = packages + get_packages(parse_model_namefile(line)) + ["gwt"]
    except:  # noqa: E722
        warn(f"Invalid namefile format: {traceback.format_exc()}")

    for line in lines:
        # Skip over blank and commented lines
        line = line.strip().split()
        if len(line) < 2:
            continue

        line = line[0].lower()
        if any(line.startswith(c) for c in ["#", "!", "data", "list"]) or line in [
            "begin",
            "end",
            "memory_print_option",
        ]:
            continue

        # strip "6" from package name
        line = line.replace("6", "")

        packages.append(line.lower())

    return list(set(packages))


def has_package(namefile_path: PathLike, package: str) -> bool:
    """
    Determines whether the model with the given namefile contains the selected package.
    """
    packages = get_packages(namefile_path)
    return package.lower() in packages


def get_namefile_paths(
    path: PathLike,
    prefix: Optional[str] = None,
    namefile: str = "mfsim.nam",
    excluded=None,
    selected=None,
    packages=None,
):
    """
    Find namefiles recursively in the given location.
    Namefiles can be filtered or excluded by pattern,
    by parent directory name prefix or pattern, or by
    packages used.
    """
    path = Path(path)

    # if path doesn't exist, return empty list
    if not path.is_dir():
        return []

    # find simulation namefiles
    paths = list(path.rglob(f"{prefix}*/**/{namefile}" if prefix else namefile))

    # remove excluded
    paths = [
        p for p in paths if (not excluded or not any(e in str(p) for e in excluded))
    ]

    # filter by package
    if packages:
        filtered = []
        for nfp in paths:
            nf_pkgs = get_packages(nfp)
            shared = set(nf_pkgs).intersection({p.lower() for p in packages})
            if any(shared):
                filtered.append(nfp)
        paths = filtered

    # filter by model name
    if selected:
        paths = [
            namfile_path
            for (namfile_path, model_path) in zip(paths, [p.parent for p in paths])
            if any(s in model_path.name for s in selected)
        ]

    return sorted(paths)


def get_model_paths(
    path: PathLike,
    prefix: Optional[str] = None,
    namefile: str = "mfsim.nam",
    excluded=None,
    selected=None,
    packages=None,
) -> list[Path]:
    """
    Find model directories recursively in the given location.
    A model directory is any directory containing one or more
    namefiles. Model directories can be filtered or excluded,
    by prefix, pattern, namefile name, or packages used. The
    directories are returned in order within scenario folders
    such that groundwater flow model workspaces precede other
    model types. This allows models which depend on the flow
    model's outputs to consume its head or budget, and models
    should successfully run in the sequence returned provided
    input files (e.g. FMI) refer to output via relative paths.
    """

    def keyfunc(v):
        v = str(v)
        if "gwf" in v:
            return 0
        else:
            return 1

    model_paths = []
    globbed = path.rglob(f"{prefix if prefix else ''}*")
    example_paths = [p for p in globbed if p.is_dir()]
    for p in example_paths:
        for mp in sorted(
            {
                p.parent
                for p in get_namefile_paths(
                    p, prefix, namefile, excluded, selected, packages
                )
            },
            key=keyfunc,
        ):
            if mp not in model_paths:
                model_paths.append(mp)
    return model_paths


def is_connected(hostname):
    """
    Tests whether the given URL is accessible.
    See https://stackoverflow.com/a/20913928/.
    """

    try:
        host = socket.gethostbyname(hostname)
        s = socket.create_connection((host, 80), 2)
        s.close()
        return True
    except Exception:
        pass
    return False


def is_in_ci():
    """
    Determines whether the current process is running GitHub Actions CI
    by checking for the "CI" environment variable.
    """

    # if running in GitHub Actions CI, "CI" variable always set to true
    # https://docs.github.com/en/actions/learn-github-actions/environment-variables#default-environment-variables
    return bool(environ.get("CI", None))


def is_github_rate_limited() -> Optional[bool]:
    """
    Determines if a GitHub API rate limit is applied to the current IP.
    Calling this function will consume an API request!

    Returns
    -------
        True if rate-limiting is applied, otherwise False
        (or None if the connection fails).
    """
    try:
        with request.urlopen("https://api.github.com/users/octocat") as response:
            remaining = int(response.headers["x-ratelimit-remaining"])
            if remaining < 10:
                warn(
                    f"Only {remaining} GitHub API requests "
                    "remaining before rate-limiting"
                )
            return remaining > 0
    except (ValueError, URLError):
        return None


_has_exe_cache = {}
_has_pkg_cache = {}


def has_exe(exe):
    """
    Determines if the given executable is available on the path.

    Originally written by Mike Toews (mwtoews@gmail.com) for FloPy.
    """
    if exe not in _has_exe_cache:
        _has_exe_cache[exe] = bool(which(exe))
    return _has_exe_cache[exe]


def has_pkg(
    pkg: str, strict: bool = False, name_map: Optional[dict[str, str]] = None
) -> bool:
    """
    Determines if the given Python package is installed.

    Parameters
    ----------
    pkg : str
        Name of the package to check.
    strict : bool
        If False, only check if the package is cached or metadata is available.
        If True, try to import the package (all dependencies must be present).
    name_map : dict, optional
        Custom mapping between package names (as provided to `metadata.distribution`)
        and module names (as used in import statements or `importlib.import_module`).
        Useful for packages whose package names do not match the module name, e.g.
        `pytest-xdist` and `xdist`, respectively, or `mfpymake` and `pymake`.

    Returns
    -------
    bool
        True if the package is installed, otherwise False.

    Notes
    -----
    If `strict=True` and a package name differs from its top-level module name, a
    `name_map` must be provided, otherwise this function will return False even if
    the package is installed.

    Originally written by Mike Toews (mwtoews@gmail.com) for FloPy.
    """

    def get_module_name() -> str:
        return pkg if name_map is None else name_map.get(pkg, pkg)

    def try_import() -> bool:
        try:  # import name, e.g. "import shapefile"
            importlib.import_module(get_module_name())
            return True
        except ModuleNotFoundError:
            return False

    def try_metadata() -> bool:
        try:  # package name, e.g. pyshp
            metadata.distribution(pkg)
            return True
        except metadata.PackageNotFoundError:
            return False

    is_cached = pkg in _has_pkg_cache
    has_metadata = try_metadata()
    can_import = try_import()
    if strict:
        found = has_metadata and can_import
    else:
        found = has_metadata or is_cached
    _has_pkg_cache[pkg] = found
    return found


def timed(f):
    """
    Decorator for estimating runtime of any function.
    Prints estimated time to stdout, in milliseconds.

    Parameters
    ----------
    f : function
        Function to time.

    Notes
    -----
    Adapted from https://stackoverflow.com/a/27737385/6514033.
    Uses the built-in timeit module internally.

    Returns
    -------
    function
        The decorated function.
    """

    @wraps(f)
    def _timed(*args, **kw):
        res = None

        def call():
            nonlocal res
            res = f(*args, **kw)

        t = timeit(lambda: call(), number=1)
        if "log_time" in kw:
            name = kw.get("log_name", f.__name__.upper())
            kw["log_time"][name] = int(t * 1000)
        else:
            print(f"{f.__name__} took {t * 1000:.2f} ms")

        return res

    return _timed


def get_env(name: str, default: object = None) -> Optional[object]:
    """
    Try to parse the given environment variable as the type of the given
    default value, if one is provided, otherwise any type is acceptable.
    If the types of the parsed value and default value don't match, the
    default value is returned. The environment variable is parsed as a
    Python literal with `ast.literal_eval()`.

    Parameters
    ----------
    name : str
        The environment variable name
    default : object
        The default value if the environment variable does not exist

    Returns
    -------
    The value of the environment variable, parsed as a Python literal,
    otherwise the default value if the environment variable is not set.
    """
    try:
        v = environ.get(name)
        if isinstance(default, bool):
            v = v.lower().title()
        v = literal_eval(v)
    except (
        AttributeError,
        ValueError,
        TypeError,
        SyntaxError,
        MemoryError,
        RecursionError,
    ):
        return default
    if default is None:
        return v
    return v if isinstance(v, type(default)) else default


@contextmanager
def set_env(*remove, **update):
    """
    Temporarily updates the ``os.environ`` dictionary in-place.

    Referenced from https://stackoverflow.com/a/34333710/6514033.

    The ``os.environ`` dictionary is updated in-place so that the modification
    is sure to work in all situations.

    :param remove: Environment variables to remove.
    :param update: Dictionary of environment variables and values to add/update.
    """
    env = environ
    update = update or {}
    remove = remove or []

    # List of environment variables being updated or removed.
    stomped = (set(update.keys()) | set(remove)) & set(env.keys())
    # Environment variables and values to restore on exit.
    update_after = {k: env[k] for k in stomped}
    # Environment variables and values to remove on exit.
    remove_after = frozenset(k for k in update if k not in env)

    try:
        env.update(update)
        [env.pop(k, None) for k in remove]
        yield
    finally:
        env.update(update_after)
        [env.pop(k) for k in remove_after]
