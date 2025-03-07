import importlib.resources as pkg_resources
from io import IOBase
from pathlib import Path

import pooch
import tomli

import modflow_devtools

PROJ_ROOT = Path(__file__).parents[1]
PROJ_OWNER = "MODFLOW-ORG"
PROJ_NAME = "modflow-devtools"
MODULE_NAME = PROJ_NAME.replace("-", "_")
PROJ_REF = "develop"
DATA_RELPATH = "data"
DATA_PATH = PROJ_ROOT / MODULE_NAME / DATA_RELPATH
DATA_ANCHOR = f"{MODULE_NAME}.{DATA_RELPATH}"
REGISTRY_NAME = "registry.txt"
MODELMAP_NAME = "models.toml"
BASE_URL = f"https://github.com/{PROJ_OWNER}/{PROJ_NAME}/raw/{PROJ_REF}/{DATA_RELPATH}/"
VERSION = modflow_devtools.__version__.rpartition(".dev")[0]
CACHE_VAR_NAME = "MF_DATA_DIR"
FETCHER = pooch.create(
    path=pooch.os_cache(PROJ_NAME),
    base_url=BASE_URL,
    version=VERSION,
    registry=None,
    env=CACHE_VAR_NAME,
)

try:
    with pkg_resources.open_text(DATA_ANCHOR, REGISTRY_NAME) as f:
        FETCHER.load_registry(f)
except:  # noqa: E722
    print(f"Could not load registry from {DATA_PATH}/{REGISTRY_NAME}.")


def _generate_function(model_name, files) -> callable:
    def model_function():
        return [Path(FETCHER.fetch(file)) for file in files]

    model_function.__name__ = model_name
    return model_function


def _attach_functions(models):
    if isinstance(models, IOBase):
        models = tomli.load(models)
    else:
        with Path(models).open("rb") as f:
            models = tomli.load(f)
    globals()["_models"] = models
    for name, files in models.items():
        globals()[name] = _generate_function(name, files)


def model_map() -> dict[str, list[Path]]:
    return globals().get("_models", {})


try:
    with pkg_resources.open_binary(DATA_ANCHOR, MODELMAP_NAME) as f:
        _attach_functions(f)
except:  # noqa: E722
    print(f"Could not load model mapping from {DATA_PATH}/{MODELMAP_NAME}.")
