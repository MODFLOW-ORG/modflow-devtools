# TODO
# - switch modflow6-testmodels and -largetestmodels to
#   fetch zip of the repo instead of individual files?

import importlib.resources as pkg_resources
from collections.abc import Callable
from functools import partial
from os import PathLike
from pathlib import Path
from shutil import copy
from warnings import warn

import pooch
import tomli

import modflow_devtools

REGISTRY_ANCHOR = f"{modflow_devtools.__name__}.registry"
REGISTRY_FILE_NAME = "registry.toml"
MODELMAP_FILE_NAME = "models.toml"
EXAMPLES_FILE_NAME = "examples.toml"

# the mf6 examples release is our base url
BASE_URL = "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current"
ZIP_NAME = "mf6examples.zip"

# set up the pooch
FETCHERS = {}
REGISTRY: dict[str, str] = {}
MODELMAP: dict[str, list[str]] = {}
EXAMPLES: dict[str, list[str]] = {}
POOCH = pooch.create(
    path=pooch.os_cache(modflow_devtools.__name__.replace("_", "-")),
    base_url=BASE_URL,
    version=modflow_devtools.__version__,
    env="MFMODELS",
)


def _fetch(model_name, file_names) -> Callable:
    def _fetch_files():
        return [Path(POOCH.fetch(fname)) for fname in file_names]

    def _fetch_zip(zip_name):
        return [
            Path(f)
            for f in POOCH.fetch(
                zip_name, processor=pooch.Unzip(members=MODELMAP[model_name])
            )
        ]

    urls = [POOCH.registry[fname] for fname in file_names]
    if not any(url for url in urls) or set(urls) == {f"{BASE_URL}/{ZIP_NAME}"}:
        fetch = partial(_fetch_zip, zip_name=ZIP_NAME)
    else:
        fetch = _fetch_files  # type: ignore
    fetch.__name__ = model_name  # type: ignore
    return fetch


try:
    with pkg_resources.open_binary(
        REGISTRY_ANCHOR, REGISTRY_FILE_NAME
    ) as registry_file:
        registry = tomli.load(registry_file)
        urls = {k: v["url"] for k, v in registry.items() if v.get("url", None)}
        registry = {k: v.get("hash", None) for k, v in registry.items()}
        POOCH.registry = registry
        POOCH.urls = urls
except:  # noqa: E722
    warn(
        f"No registry file '{REGISTRY_FILE_NAME}' "
        f"in module '{REGISTRY_ANCHOR}' resources"
    )


try:
    with pkg_resources.open_binary(REGISTRY_ANCHOR, MODELMAP_FILE_NAME) as models_file:
        MODELMAP = tomli.load(models_file)
        for model_name, files in MODELMAP.items():
            fetch = _fetch(model_name, files)
            FETCHERS[model_name] = fetch
            globals()[model_name] = fetch
except:  # noqa: E722
    warn(
        f"No model mapping file '{MODELMAP_FILE_NAME}' "
        f"in module '{REGISTRY_ANCHOR}' resources"
    )


try:
    with pkg_resources.open_binary(
        REGISTRY_ANCHOR, EXAMPLES_FILE_NAME
    ) as examples_file:
        EXAMPLES = tomli.load(examples_file)
except:  # noqa: E722
    warn(
        f"No examples file '{EXAMPLES_FILE_NAME}' "
        f"in module '{REGISTRY_ANCHOR}' resources"
    )


def get_examples() -> dict[str, list[str]]:
    return EXAMPLES


def get_registry() -> dict[str, str]:
    return POOCH.registry


def list_models() -> list[str]:
    return list(MODELMAP.keys())


def copy_to(
    workspace: str | PathLike, model_name: str, verbose: bool = False
) -> Path | None:
    if not any(files := FETCHERS[model_name]()):
        return None
    workspace = Path(workspace).expanduser().absolute()
    if verbose:
        print(f"Creating workspace {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    for file in files:
        if verbose:
            print(f"Copying {file} to workspace")
        copy(file, workspace)
    return workspace
