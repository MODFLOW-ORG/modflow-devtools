# - support mf2005 models in modflow6-testmodels repo
# - switch modflow6-testmodels and -largetestmodels to
#   fetch zip of the repo instead of individual files?

import hashlib
import importlib.resources as pkg_resources
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import partial
from os import PathLike
from pathlib import Path
from shutil import copy
from typing import ClassVar
from warnings import warn

import pooch
import tomli
import tomli_w
from boltons.iterutils import remap
from filelock import FileLock
from pooch import Pooch

import modflow_devtools
from modflow_devtools.misc import get_model_paths


def _drop_none_or_empty(path, key, value):
    if value is None or value == "":
        return False
    return True


def _sha256(path: Path) -> str:
    """
    Compute the SHA256 hash of the given file.
    Reference: https://stackoverflow.com/a/44873382/6514033
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with path.open("rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


class ModelRegistry(ABC):
    @property
    @abstractmethod
    def path(self) -> Path:
        """The path to the registry's data."""
        ...

    @property
    @abstractmethod
    def files(self) -> dict:
        """
        A map of file name to file-scoped information. Note that
        this map contains no information on which files belong to
        which model; that info is in the `models` dictionary.
        """
        ...

    @property
    @abstractmethod
    def models(self) -> dict:
        """
        A map of model name to the model's input file set.
        """
        ...

    @property
    @abstractmethod
    def examples(self) -> dict:
        """
        A map of example name to model names in the example.
        An *example* is an ordered set of models/simulations.
        """
        ...

    @abstractmethod
    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """Copy a model's input files to the given workspace."""
        ...


class LocalRegistry(ModelRegistry):
    """
    A registry of models in a local directory.

    *Not* persistent &mdash; lives only in memory, unlike `PoochRegistry`.

    The registry is loaded lazily upon first access by recursively scanning
    the given directory for models (located by the presence of a namefile)
    and corresponding input files.

    If model input files change on disk, you can force a reload by calling
    `load()`. The model folder may not be changed after registry creation.
    """

    exclude: ClassVar = [".DS_Store", "compare"]

    def __init__(self, path: str | PathLike, namefile_pattern: str = "mfsim.nam"):
        """
        Create a registry from models under the given
        directory path.

        The `path` may consist of model subdirectories
        at arbitrary depth. Model input subdirectories
        are identified by the presence of a namefile
        matching `namefile_pattern`.
        """
        self._path = Path(path).expanduser().resolve().absolute()
        self._files: dict[str, dict[str, str | None]] = {}
        self._models: dict[str, list[str]] = {}
        self._examples: dict[str, list[str]] = {}
        if not self._path.is_dir():
            raise NotADirectoryError(f"Path {self._path} is not a directory.")
        self.namefile_pattern = namefile_pattern
        self.index()

    def index(self):
        """
        Build the registry from models found under the configured path. This
        method can be called to reload the registry e.g. if model files have
        changed since the registry was created.
        """

        self._files = {}
        self._models = {}
        self._examples = {}
        model_paths = get_model_paths(self._path, namefile=self.namefile_pattern)
        for model_path in model_paths:
            model_path = model_path.expanduser().resolve().absolute()
            rel_path = model_path.relative_to(self._path)
            model_name = "/".join(rel_path.parts)
            self._models[model_name] = []
            if len(rel_path.parts) > 1:
                name = rel_path.parts[0]
                if name not in self._examples:
                    self._examples[name] = []
                self._examples[name].append(model_name)
            for p in model_path.rglob("*"):
                if not p.is_file() or any(e in p.name for e in LocalRegistry.exclude):
                    continue
                relpath = p.expanduser().absolute().relative_to(self._path)
                name = "/".join(relpath.parts)
                hash = _sha256(p)
                self._files[name] = {"hash": hash}
                self._models[model_name].append(name)

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy the model's input files to the given workspace.
        The workspace will be created if it does not exist.
        """

        if not any(files := self.models.get(model_name, [])):
            return None
        # create the workspace if needed
        workspace = Path(workspace).expanduser().absolute()
        if verbose:
            print(f"Creating workspace {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        # copy the files. some might be in nested folders,
        # but the first is guaranteed not to be, so use it
        # to determine relative path in the new workspace.
        base = Path(files[0]).parent
        for file in [Path(self._path) / f for f in files]:
            if verbose:
                print(f"Copying {file} to workspace")
            path = workspace / file.relative_to(base)
            path.parent.mkdir(parents=True, exist_ok=True)
            copy(file, workspace / file.relative_to(base))
        return workspace

    @property
    def path(self) -> Path:
        return self._path

    @property
    def files(self) -> dict:
        return self._files

    @property
    def models(self) -> dict:
        return self._models

    @property
    def examples(self) -> dict:
        return self._examples


class PoochRegistry(ModelRegistry):
    """
    A registry of models living in one or more GitHub repositories, accessible via
    URLs. The registry uses Pooch to fetch models from the remote repos if needed.

    On import, the registry is loaded from a database included as a module resource.
    This consists of TOML files containing file information (as expected by Pooch),
    a map grouping files by model name, and a map grouping model names by example.
    Creating this database is a developer task. It should be checked into version
    control and updated whenever models are added to, removed from, or edited in
    the repositories referenced by the registry.

    Since the registry must change whenever the remote branch does, it should be
    aimed only at stable branches.
    """

    anchor: ClassVar = f"{modflow_devtools.__name__}.registry"
    registry_file_name: ClassVar = "registry.toml"
    models_file_name: ClassVar = "models.toml"
    examples_file_name: ClassVar = "examples.toml"

    def __init__(
        self,
        path: str | PathLike | None = None,
        base_url: str | None = None,
        env: str | None = None,
        retries: int = 3,
    ):
        self._registry_path = Path(__file__).parent / "registry"
        self._registry_path.mkdir(parents=True, exist_ok=True)
        self._registry_file_path = (
            self._registry_path / PoochRegistry.registry_file_name
        )
        self._models_file_path = self._registry_path / PoochRegistry.models_file_name
        self._examples_file_path = (
            self._registry_path / PoochRegistry.examples_file_name
        )
        self._path = (
            Path(path).expanduser().absolute()
            if path
            else pooch.os_cache(modflow_devtools.__name__.replace("_", "-"))
        )
        self._pooch = pooch.create(
            path=self._path,
            base_url=base_url,
            version=modflow_devtools.__version__,
            env=env,
            retry_if_failed=retries,
        )
        self._fetchers: dict = {}
        self._urls: dict = {}
        self._load()

    def _fetcher(self, model_name, file_names) -> Callable:
        def _fetch_files():
            return [Path(self.pooch.fetch(fname)) for fname in file_names]

        def _fetch_zip(zip_name):
            with FileLock(f"{zip_name}.lock"):
                return [
                    Path(f)
                    for f in self.pooch.fetch(
                        zip_name, processor=pooch.Unzip(members=self.models[model_name])
                    )
                ]

        urls = [self.pooch.registry[fname] for fname in file_names]
        if not any(url for url in urls) or set(urls) == {
            f"{_DEFAULT_BASE_URL}/{_DEFAULT_ZIP_NAME}"
        }:
            fetch = partial(_fetch_zip, zip_name=_DEFAULT_ZIP_NAME)
        else:
            fetch = _fetch_files  # type: ignore
        fetch.__name__ = model_name  # type: ignore
        return fetch

    def _load(self):
        try:
            with pkg_resources.open_binary(
                PoochRegistry.anchor, PoochRegistry.registry_file_name
            ) as registry_file:
                registry = tomli.load(registry_file)
                self._files = {
                    k: {"path": self.pooch.path / k, "hash": v.get("hash", None)}
                    for k, v in registry.items()
                }
                # extract urls then drop them. registry directly maps file name to hash
                self.urls = {
                    k: v["url"] for k, v in registry.items() if v.get("url", None)
                }
                self.pooch.registry = {
                    k: v.get("hash", None) for k, v in registry.items()
                }
                self.pooch.urls = self.urls
        except:  # noqa: E722
            self._urls = {}
            self._files = {}
            self.pooch.registry = {}
            warn(
                f"No registry file '{PoochRegistry.registry_file_name}' "
                f"in module '{PoochRegistry.anchor}' resources"
            )

        try:
            with pkg_resources.open_binary(
                PoochRegistry.anchor, PoochRegistry.models_file_name
            ) as models_file:
                self._models = tomli.load(models_file)
                for model_name, registry in self.models.items():
                    self._fetchers[model_name] = self._fetcher(model_name, registry)
        except:  # noqa: E722
            self._models = {}
            warn(
                f"No model mapping file '{PoochRegistry.models_file_name}' "
                f"in module '{PoochRegistry.anchor}' resources"
            )

        try:
            with pkg_resources.open_binary(
                PoochRegistry.anchor, PoochRegistry.examples_file_name
            ) as examples_file:
                self._examples = tomli.load(examples_file)
        except:  # noqa: E722
            self._examples = {}
            warn(
                f"No examples file '{PoochRegistry.examples_file_name}' "
                f"in module '{PoochRegistry.anchor}' resources"
            )

    def index(
        self,
        path: str | PathLike,
        url: str,
        prefix: str = "",
        namefile: str = "mfsim.nam",
    ):
        """
        Add models in the given path to the registry.
        Call this once or more to prepare a registry.

        This function is *not* idempotent. It should
        be called with different arguments each time.

        The `url` must be a remote repository which
        contains models. The registry will be fixed
        to the state of the repository at the given
        URL at the current time.

        The `path` must be the root of, or a folder
        within, a local clone of the repository. The
        branch checked out must match the URL branch.

        The `path` may contain model subdirectories
        at arbitrary depth. Model input subdirectories
        are identified by the presence of a namefile
        matching the provided pattern. A prefix may be
        specified for model names to avoid collisions.

        Parameters
        ----------
        path : str | PathLike
            Path to the directory containing the models.
        url : str
            Base URL for the models.
        prefix : str
            Prefix to add to model names.
        append : bool
            Append to the registry files instead of overwriting them.
        namefile : str
            Namefile pattern to look for in the model directories.
        """
        path = Path(path).expanduser().resolve().absolute()
        if not path.is_dir():
            raise NotADirectoryError(f"Path {path} is not a directory.")

        files: dict[str, dict[str, str | None]] = {}
        models: dict[str, list[str]] = {}
        examples: dict[str, list[str]] = {}
        exclude = [".DS_Store", "compare"]
        if url and (is_zip := url.endswith((".zip", ".tar"))):
            files[url.rpartition("/")[2]] = {"hash": None, "url": url}

        model_paths = get_model_paths(path, namefile=namefile)
        for model_path in model_paths:
            model_path = model_path.expanduser().resolve().absolute()
            rel_path = model_path.relative_to(path)
            parts = [prefix, *list(rel_path.parts)] if prefix else list(rel_path.parts)
            model_name = "/".join(parts)
            models[model_name] = []
            if is_zip:
                name = rel_path.parts[0]
                if name not in examples:
                    examples[name] = []
                examples[name].append(model_name)
            for p in model_path.rglob("*"):
                if not p.is_file() or any(e in p.name for e in exclude):
                    continue
                if is_zip:
                    relpath = p.expanduser().resolve().absolute().relative_to(path)
                    name = "/".join(relpath.parts)
                    url_: str | None = url
                    hash = None
                else:
                    relpath = p.expanduser().resolve().absolute().relative_to(path)
                    name = "/".join(relpath.parts)
                    url_ = f"{url}/{relpath!s}" if url else None
                    hash = _sha256(p)
                files[name] = {"hash": hash, "url": url_}
                models[model_name].append(name)

        with self._registry_file_path.open("ab+") as registry_file:
            tomli_w.dump(
                remap(dict(sorted(files.items())), visit=_drop_none_or_empty),
                registry_file,
            )

        with self._models_file_path.open("ab+") as models_file:
            tomli_w.dump(dict(sorted(models.items())), models_file)

        with self._examples_file_path.open("ab+") as examples_file:
            tomli_w.dump(dict(sorted(examples.items())), examples_file)

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy the model's input files to the given workspace.
        The workspace will be created if it does not exist.
        """

        if (fetch := self._fetchers.get(model_name, None)) is None:
            raise ValueError(f"Model '{model_name}' not in registry")
        if not any(files := fetch()):
            return None
        # create the workspace if needed
        workspace = Path(workspace).expanduser().resolve().absolute()
        if verbose:
            print(f"Creating workspace {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        # copy the files. some might be in nested folders,
        # but the first is guaranteed not to be, so use it
        # to determine relative path in the new workspace.
        base = Path(files[0]).parent
        for file in files:
            if verbose:
                print(f"Copying {file} to workspace")
            path = workspace / file.relative_to(base)
            path.parent.mkdir(parents=True, exist_ok=True)
            copy(file, workspace / file.relative_to(base))
        return workspace

    @property
    def pooch(self) -> Pooch:
        """The registry's Pooch instance."""
        return self._pooch

    @property
    def path(self) -> Path:
        return self.pooch.path

    @property
    def files(self) -> dict:
        return self._files

    @property
    def models(self) -> dict:
        return self._models

    @property
    def examples(self) -> dict:
        return self._examples


_DEFAULT_ENV = "MFMODELS_PATH"
_DEFAULT_BASE_URL = (
    "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current"
)
_DEFAULT_ZIP_NAME = "mf6examples.zip"
DEFAULT_REGISTRY = PoochRegistry(base_url=_DEFAULT_BASE_URL, env=_DEFAULT_ENV)
"""The default model registry."""


def get_examples() -> dict[str, list[str]]:
    """
    Get a map of example names to models in the example.
    """
    return DEFAULT_REGISTRY.examples


def get_models() -> dict[str, str]:
    """Get a map of model names to input files."""
    return DEFAULT_REGISTRY.models


def get_files() -> dict[str, dict[str, str]]:
    """
    Get a map of file names to URLs. Note that this mapping
    contains no information on which files belong to which
    models. For that information, use `get_models()`.
    """
    return DEFAULT_REGISTRY.files


def copy_to(
    workspace: str | PathLike, model_name: str, verbose: bool = False
) -> Path | None:
    """
    Copy the model's input files to the given workspace.
    The workspace will be created if it does not exist.
    """
    return DEFAULT_REGISTRY.copy_to(workspace, model_name, verbose=verbose)
