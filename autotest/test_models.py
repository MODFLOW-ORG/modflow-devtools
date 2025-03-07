import random
import sys
from pathlib import Path

import pytest
import tomli

import modflow_devtools.models as models

MODELS_TOML_PATH = Path(models.DATA_PATH) / models.MODELMAP_NAME


# TODO: Remove when we drop support for python 3.9 (soon?)
if sys.version_info[:2] == (3, 9):
    pytest.skip("Unsupported for python 3.9", allow_module_level=True)


@pytest.fixture
def models_toml():
    with MODELS_TOML_PATH.open("rb") as f:
        return tomli.load(f)


@pytest.fixture
def temp_cache_dir(tmpdir, monkeypatch):
    temp_dir = tmpdir.mkdir("pooch_cache")
    monkeypatch.setenv("MF_DATA_DIR", str(temp_dir))
    models.FETCHER.path = temp_dir  # Update the fetcher path
    return temp_dir


def test_registry():
    assert models.FETCHER.registry is not None, "Registry was not loaded"
    assert len(models.FETCHER.registry) > 0, "Registry is empty"


def test_model_map(models_toml):
    assert models.model_map()
    for model_name, files in models_toml.items():
        assert model_name in models.model_map().keys(), (
            f"Model {model_name} not found in model map"
        )
        assert files == models.model_map()[model_name], (
            f"Files for model {model_name} do not match"
        )


def test_generated_functions_exist(models_toml):
    for model_name in models_toml.keys():
        assert hasattr(models, model_name), (
            f"Function {model_name} not found in models module"
        )


def test_generated_functions_return_files(models_toml, temp_cache_dir):
    for model_name, files in models_toml.items():
        model_function = getattr(models, model_name)
        fetched_files = model_function()
        cached_files = temp_cache_dir.listdir()
        assert isinstance(fetched_files, list), (
            f"Function {model_name} did not return a list"
        )
        assert len(fetched_files) == len(files), (
            f"Function {model_name} did not return the correct number of files"
        )
        for fetched_file in fetched_files:
            assert Path(fetched_file).exists(), (
                f"Fetched file {fetched_file} does not exist"
            )
            assert Path(temp_cache_dir) / Path(fetched_file).name in cached_files, (
                f"Fetched file {fetched_file} is not in the temp cache directory"
            )
        if random.randint(0, 5) % 5 == 0:
            break  # just the first few so we dont ddos github
