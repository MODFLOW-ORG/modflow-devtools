# TODO
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
from modflow_devtools.misc import drop_none_or_empty, get_model_paths

# Best-effort sync flag (to avoid multiple sync attempts)
_SYNC_ATTEMPTED = False


def _model_sort_key(k) -> int:
    if "gwf" in k:
        return 0
    return 1


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
        A map of model name to the model's input files.
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
    A registry of models in one or more local directories.

    *Not* persistent &mdash; lives only in memory, unlike `PoochRegistry`.

    Indexing a directory recursively scans it for models (located by the
    presence of a namefile) and registers corresponding input files.
    """

    exclude: ClassVar = [".DS_Store", "compare"]

    def __init__(self) -> None:
        self._paths: set[Path] = set()
        self._files: dict[str, Path] = {}
        self._models: dict[str, list[Path]] = {}
        self._examples: dict[str, list[str]] = {}

    def index(
        self,
        path: str | PathLike,
        prefix: str | None = None,
        namefile: str = "mfsim.nam",
        excluded: list[str] | None = None,
        model_name_prefix: str = "",
    ):
        """
        Add models found under the given path to the registry.

        Call this once or more to prepare a registry. If called on the same
        `path` again, the models will be reloaded &mdash; thus this method
        is idempotent and may be used to reload the registry e.g. if model
        files have changed since the registry was created.

        The `path` may consist of model subdirectories at arbitrary depth.
        Model subdirectories are identified by the presence of a namefile
        matching `namefile_pattern`. Model subdirectories may be filtered
        inclusively by `prefix` or exclusively by `excluded`

        A `model_name_prefix` may be specified to avoid collisions with
        models indexed from other directories. This prefix will be added
        to the model name, which is derived from the relative path of the
        model subdirectory under `path`.
        """

        path = Path(path).expanduser().resolve().absolute()
        if not path.is_dir():
            raise NotADirectoryError(f"Directory path not found: {path}")
        self._paths.add(path)

        model_paths = get_model_paths(
            path, prefix=prefix, namefile=namefile, excluded=excluded
        )
        for model_path in model_paths:
            model_path = model_path.expanduser().resolve().absolute()
            rel_path = model_path.relative_to(path)
            parts = (
                [model_name_prefix, *list(rel_path.parts)]
                if model_name_prefix
                else list(rel_path.parts)
            )
            model_name = "/".join(parts)
            self._models[model_name] = []
            if len(rel_path.parts) > 1:
                name = rel_path.parts[0]
                if name not in self._examples:
                    self._examples[name] = []
                self._examples[name].append(model_name)
            for p in model_path.rglob("*"):
                if not p.is_file() or any(e in p.name for e in LocalRegistry.exclude):
                    continue
                relpath = p.expanduser().absolute().relative_to(path)
                name = "/".join(relpath.parts)
                self._files[name] = p
                self._models[model_name].append(p)

    def copy_to(
        self, workspace: str | PathLike, model_name: str, verbose: bool = False
    ) -> Path | None:
        """
        Copy the model's input files to the given workspace.
        The workspace will be created if it does not exist.
        """

        if not any(file_paths := self.models.get(model_name, [])):
            return None
        # create the workspace if needed
        workspace = Path(workspace).expanduser().absolute()
        if verbose:
            print(f"Creating workspace {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        # copy the files. some might be in nested folders,
        # but the first is guaranteed not to be, so use it
        # to determine relative path in the new workspace.
        base = Path(file_paths[0]).parent
        for file_path in file_paths:
            if verbose:
                print(f"Copying {file_path} to workspace")
            dest = workspace / file_path.relative_to(base)
            dest.parent.mkdir(parents=True, exist_ok=True)
            copy(file_path, dest)
        return workspace

    @property
    def paths(self) -> set[Path]:
        return self._paths

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
    URLs. The registry uses Pooch to fetch models from the remote(s) where needed.

    On import, the registry is loaded from a database distributed with the package.
    This database consists of TOML files containing file info as expected by Pooch,
    a map grouping files by model name, and a map grouping model names by example.
    Creating this database is a developer task. It should be checked into version
    control and updated whenever models are added to, removed from, or edited in
    the repositories referenced by the registry.

    **Note**: since the registry must change whenever the remote branch does, it
    should be aimed only at stable branches.
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
        self._registry_path = Path(__file__).parent.parent / "registry"
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
        """
        Load registry data.

        Tries to load from cached registries first (if synced),
        falls back to bundled registry with deprecation warning.
        """
        # Try to load from cache first
        loaded_from_cache = self._try_load_from_cache()

        if not loaded_from_cache:
            # Fall back to bundled registry
            self._load_from_bundled()

    def _try_load_from_cache(self) -> bool:
        """
        Try to load registry from cache.

        Returns True if successful, False otherwise.
        """
        try:
            # Import here to avoid circular dependency
            from .cache import list_cached_registries, load_cached_registry

            cached = list_cached_registries()
            if not cached:
                return False

            # Merge all cached registries
            all_files = {}
            all_models = {}
            all_examples = {}

            for source, ref in cached:
                registry = load_cached_registry(source, ref)
                if registry:
                    # Merge files
                    for fname, file_entry in registry.files.items():
                        all_files[fname] = {
                            "path": self.pooch.path / fname,
                            "hash": file_entry.hash,
                            "url": file_entry.url,
                        }

                    # Merge models
                    all_models.update(registry.models)

                    # Merge examples
                    all_examples.update(registry.examples)

            if not all_files:
                return False

            # Set registry data
            self._files = all_files
            self._models = all_models
            self._examples = all_examples

            # Configure Pooch
            self.urls = {
                k: v["url"] for k, v in all_files.items() if v.get("url")
            }
            self.pooch.registry = {
                k: v.get("hash") for k, v in all_files.items()
            }
            self.pooch.urls = self.urls

            # Set up fetchers
            self._fetchers = {}
            for model_name, file_list in self._models.items():
                self._fetchers[model_name] = self._fetcher(model_name, file_list)

            return True

        except Exception:
            return False

    def _load_from_bundled(self):
        """
        Load registry from bundled package resources.

        Shows deprecation warning.
        """
        import warnings

        warnings.warn(
            "Loading bundled registry. This is deprecated and will be removed in v2.0. "
            "Use 'python -m modflow_devtools.models sync' to download the latest registry.",
            DeprecationWarning,
            stacklevel=3,
        )

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
        output_path: str | PathLike | None = None,
        separate: bool = False,
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
        namefile : str
            Namefile pattern to look for in the model directories.
        output_path : str | PathLike | None
            Path to output directory. If None, uses default registry path.
        separate : bool
            If True, generates separate registry.toml, models.toml, examples.toml (for 1.x compatibility).
            If False (default), generates single consolidated registry.toml.
        """
        path = Path(path).expanduser().resolve().absolute()
        if not path.is_dir():
            raise NotADirectoryError(f"Path {path} is not a directory.")

        # Determine output directory
        if output_path is not None:
            output_dir = Path(output_path).expanduser().resolve().absolute()
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = self._registry_path

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

        for example_name in examples.keys():
            examples[example_name] = sorted(examples[example_name], key=_model_sort_key)

        if not separate:
            # Write single consolidated registry.toml (default)
            from datetime import datetime, timezone

            registry_file = output_dir / "registry.toml"

            # Read existing registry if it exists (to support multiple index() calls)
            existing_files = {}
            existing_models = {}
            existing_examples = {}
            if registry_file.exists():
                with registry_file.open("rb") as f:
                    existing_data = tomli.load(f)
                    existing_files = existing_data.get("files", {})
                    existing_models = existing_data.get("models", {})
                    existing_examples = existing_data.get("examples", {})

            # Merge with new data
            existing_files.update(files)
            existing_models.update(models)
            existing_examples.update(examples)

            registry_data = {
                "_meta": {
                    "schema_version": "1.0",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "devtools_version": modflow_devtools.__version__,
                },
                "files": remap(
                    dict(sorted(existing_files.items())), visit=drop_none_or_empty
                ),
                "models": dict(sorted(existing_models.items())),
                "examples": dict(sorted(existing_examples.items())),
            }

            with registry_file.open("wb") as f:
                tomli_w.dump(registry_data, f)
        else:
            # Write separate files (for 1.x compatibility)
            registry_file_path = output_dir / PoochRegistry.registry_file_name
            models_file_path = output_dir / PoochRegistry.models_file_name
            examples_file_path = output_dir / PoochRegistry.examples_file_name

            with registry_file_path.open("ab+") as registry_file:
                tomli_w.dump(
                    remap(dict(sorted(files.items())), visit=drop_none_or_empty),
                    registry_file,
                )

            with models_file_path.open("ab+") as models_file:
                tomli_w.dump(dict(sorted(models.items())), models_file)

            with examples_file_path.open("ab+") as examples_file:
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


def _try_best_effort_sync():
    """
    Attempt to sync registries on first import.

    This is a best-effort operation - if it fails (network issues,
    misconfiguration, etc.), we silently continue and fall back to
    the bundled registry.
    """
    global _SYNC_ATTEMPTED

    if _SYNC_ATTEMPTED:
        return

    _SYNC_ATTEMPTED = True

    try:
        # Import here to avoid circular dependency
        from .sync import sync_registry

        # Try to sync default refs (don't be verbose, don't fail on errors)
        sync_registry(verbose=False)
    except Exception:
        # Silently fail - we'll fall back to bundled registry
        pass


# Try to sync on first import
_try_best_effort_sync()

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
