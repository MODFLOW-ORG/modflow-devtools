from itertools import islice
from pathlib import Path

import pytest
import tomli

import modflow_devtools.models as models
from modflow_devtools.misc import is_in_ci

TAKE = 5 if is_in_ci() else None
PROJ_ROOT = Path(__file__).parents[1]
MODELMAP_PATH = PROJ_ROOT / "modflow_devtools" / "registry" / models.MODELMAP_FILE_NAME
with MODELMAP_PATH.open("rb") as f:
    MODELMAP = tomli.load(f)


def test_registry():
    registry = models.get_registry()
    assert registry is not None, "Registry was not loaded"
    assert registry is models.POOCH.registry
    assert any(registry), "Registry is empty"


@pytest.mark.parametrize("model_name, files", MODELMAP.items())
def test_models(model_name, files):
    model_names = models.list_models()
    assert model_name in model_names, f"Model {model_name} not found in model map"
    assert files == models.MODELMAP[model_name], (
        f"Files for model {model_name} do not match"
    )
    assert hasattr(models, model_name), (
        f"Function {model_name} not found in models module"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)


@pytest.mark.parametrize("example_name, model_names", models.get_examples().items())
def test_get_examples(example_name, model_names):
    assert example_name in models.EXAMPLES
    for model_name in model_names:
        assert model_name in models.MODELMAP


@pytest.mark.parametrize("model_name, files", list(islice(MODELMAP.items(), TAKE)))
def test_copy_to(model_name, files, tmp_path):
    workspace = models.copy_to(tmp_path, model_name)
    assert workspace.exists(), f"Model {model_name} was not copied to {tmp_path}"
    assert workspace.is_dir(), f"Model {model_name} is not a directory"
    assert len(list(workspace.iterdir())) == len(files), (
        f"Model {model_name} does not have the correct number of files"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)


@pytest.mark.parametrize("model_name, files", list(islice(MODELMAP.items(), TAKE)))
def test_generated_functions_return_files(model_name, files):
    model_function = getattr(models, model_name)
    fetched_files = model_function()
    assert isinstance(fetched_files, list), (
        f"Function {model_name} did not return a list"
    )
    assert len(fetched_files) == len(files), (
        f"Function {model_name} did not return the correct number of files"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)
    for fetched_file in fetched_files:
        assert Path(fetched_file).exists(), (
            f"Fetched file {fetched_file} does not exist"
        )
