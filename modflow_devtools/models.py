from pathlib import Path

import pooch
import tomli

import modflow_devtools

REPO_OWNER = "MODFLOW-ORG"
REPO_NAME = "modflow-devtools"
REPO_REF = "develop"
PROJ_ROOT = Path(__file__).parents[1]
DATA_RELPATH = "data"
DATA_PATH = PROJ_ROOT / REPO_NAME / DATA_RELPATH
REGISTRY_PATH = DATA_PATH / "registry.txt"
MODELS_PATH = DATA_PATH / "models.toml"
BASE_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/raw/{REPO_REF}/{DATA_RELPATH}/"
VERSION = modflow_devtools.__version__.rpartition(".dev")[0]
FETCHER = pooch.create(
    path=pooch.os_cache(REPO_NAME),
    base_url=BASE_URL,
    version=VERSION,
    registry=None,
)

if not REGISTRY_PATH.exists():
    raise FileNotFoundError(f"Registry file {REGISTRY_PATH} not found.")

if not MODELS_PATH.exists():
    raise FileNotFoundError(f"Models file {MODELS_PATH} not found.")

FETCHER.load_registry(REGISTRY_PATH)


def _generate_function(model_name: str, files: list) -> callable:
    def model_function() -> list:
        return [FETCHER.fetch(file) for file in files]

    model_function.__name__ = model_name
    return model_function


def _make_functions(models_path: Path, registry_path: Path):
    with models_path.open("rb") as f:
        models = tomli.load(f)
        for model_name, files in models.items():
            globals()[model_name] = _generate_function(model_name, files)


_make_functions(MODELS_PATH, REGISTRY_PATH)
