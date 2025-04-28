from itertools import islice
from pathlib import Path

import pytest
import tomli

import modflow_devtools.models as models
from modflow_devtools.misc import is_in_ci

TAKE = 5 if is_in_ci() else None
PROJ_ROOT = Path(__file__).parents[1]
MODELS_PATH = PROJ_ROOT / "modflow_devtools" / "registry" / "models.toml"
MODELS = tomli.load(MODELS_PATH.open("rb"))
REGISTRY = models._DEFAULT_REGISTRY


def test_files():
    files = models.get_files()
    assert files is not None, "Files not loaded"
    assert files is REGISTRY.files
    assert any(files), "Registry is empty"


@pytest.mark.parametrize(
    "model_name, files", MODELS.items(), ids=list(MODELS.keys())
)
def test_models(model_name, files):
    model_names = list(models.get_models().keys())
    assert model_name in model_names, f"Model {model_name} not found in model map"
    assert files == REGISTRY.models[model_name], (
        f"Files for model {model_name} do not match"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)


@pytest.mark.parametrize(
    "example_name, model_names",
    models.get_examples().items(),
    ids=list(models.get_examples().keys()),
)
def test_examples(example_name, model_names):
    assert example_name in models.get_examples()
    for model_name in model_names:
        assert model_name in REGISTRY.models


@pytest.mark.parametrize(
    "model_name, files",
    list(islice(MODELS.items(), TAKE)),
    ids=list(MODELS.keys())[:TAKE],
)
def test_copy_to(model_name, files, tmp_path):
    workspace = models.copy_to(tmp_path, model_name, verbose=True)
    assert workspace.exists(), f"Model {model_name} was not copied to {tmp_path}"
    assert workspace.is_dir(), f"Model {model_name} is not a directory"
    found = [p for p in workspace.rglob("*") if p.is_file()]
    assert len(found) == len(files), (
        f"Model {model_name} does not have the correct number of files, "
        f"expected {len(files)}, got {len(found)}"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)
