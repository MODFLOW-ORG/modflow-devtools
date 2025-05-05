# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 (and other) models.

**Note**: While this module leans heavily on [Pooch](https://www.fatiando.org/pooch/latest/index.html), it is an independent layer with opinions about how to train (configure) it.

## `ModelRegistry`

The `ModelRegistry` base class represents a set of models living in a GitHub repository or on the local filesystem. This package provides an "official" GitHub-backed registry. Local registries may be created as needed.

All `ModelRegistry` subclasses expose the following properties:

- `files`: a map of model input files to file-scoped info
- `models`: a map of model names to model input files
- `examples`: a map of example scenarios to models

An *example* is a set of related models which run in a particular order.

Dictionary keys are consistently strings. Dictionary values may vary depending on the type of registry. For instance, values in `PoochRegistry.files` are dictionaries including a hash and url.

### Subclasses

A registry backed by a remote repository is called a `PoochRegistry`. A `PoochRegistry` maintains a persistent index on disk. 

A `LocalRegistry` lives in-memory only. Its purpose is simply to store some knowledge about where model files are on disk, and provide an identical API for accessing them as the official `PoochRegistry`.

Most users will interact only with the default `PoochRegistry`, available at `modflow_devtools.models.DEFAULT_REGISTRY`. A `LocalRegistry` can be useful for developing and debugging MODFLOW and/or MODFLOW models alongside one another.

### Listing models

This module provides convenience functions to access the default registry.

For instance, the `get_models()` function aliases `DEFAULT_REGISTRY.models`.

```python
from pprint import pprint
from modflow_devtools.models import DEFAULT_REGISTRY, get_models

pprint(list(get_models())[:5])
```

```
['mf6/example/ex-gwe-ates',
 'mf6/example/ex-gwe-barends/mf6gwe',
 'mf6/example/ex-gwe-barends/mf6gwf',
 'mf6/example/ex-gwe-danckwerts',
 'mf6/example/ex-gwe-geotherm/mf6gwe']
```

#### Model names

Model names follow a hierarchical addressing scheme.

The leading part identifies the kind of model, e.g. `mf6`, `mf2005`, etc. Subsequent parts may be used to classify the model.

Currently the following prefixes are in use:

- `mf6/example/...`: mf6 example models in https://github.com/MODFLOW-ORG/modflow6-examples
- `mf6/test/...`: mf6 test models in https://github.com/MODFLOW-ORG/modflow6-testmodels
- `mf6/large/...`: large mf6 test models in https://github.com/MODFLOW-ORG/modflow6-largetestmodels
- `mf2005/...`: mf2005 models in https://github.com/MODFLOW-ORG/modflow6-testmodels

The remaining parts may reflect the relative location of the model within the source repository.

**Note**: Until this module stabilizes, model naming conventions may change without notice.

### Using models

To copy model input files to a workspace of your choosing, call `copy_to` on the registry.

```python
from tempfile import TemporaryDirectory
from modflow_devtools.models import copy_to

with TemporaryDirectory() as td:
    workspace = DEFAULT_REGISTRY.copy_to(td, "example/ex-gwe-ates", verbose=True)
    # or, the module provides a shortcut for this too
    workspace = copy_to(td, "example/ex-gwe-ates", verbose=True)
```

If the target directory doesn't exist, it will be created.

## Creating a registry

### Local registries

To prepare a local registry, just create it and call `index` once or more. The `path` to index must be a directory containing model subdirectories at arbitrary depth. Model subdirectories are identified by the presence of a namefile matching `namefile_pattern`. By default `namefile_pattern="mfsim.nam"`, causing only MODFLOW 6 models to be returned.

For instance, to load all MODFLOW models (pre-MF6 as well):

```python
registry = LocalRegistry()
registry.index("path/to/models", namefile_pattern="*.nam")
```

### Pooch registry

The `make_registry.py` script is responsible for generating a registry text file and a mapping between files and models.

The generated registry file and model mapping are used to create a pooch instance for fetching model files, and should be distributed with the package.

The script can be executed with `python -m modflow_devtools.make_registry`. It accepts a single positional argument, specifying the base directory containing model directories. It accepts two named arguments:

- `--append` or `-a`: If specified, the script will append to the existing registry file instead of overwriting it.
- `--url` or `-u`: Specifies the base URL for the registry file. If not provided, the default base URL is used.
- `--model-name-prefix`: Optionally specify a string to prepend to model names. Useful for avoiding collisions.
- `--namefile`: Optionally specify the glob pattern for namefiles. By default, only `mfsim.nam` (MF6) are found.

For example, to create a registry of models in the MF6 examples and test models repositories, assuming each is checked out next to this project:

```shell
python -m modflow_devtools.make_registry ../modflow6-examples/examples --url https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip --model-name-prefix mf6/example
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6 --model-name-prefix mf6/test
python -m modflow_devtools.make_registry ../modflow6-largetestmodels --append --url https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master --model-name-prefix mf6/large
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf5to6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf5to6 --model-name-prefix mf2005 --namefile "*.nam"
```

Above we adopt a convention of prefixing model names with the model type (i.e. the program used to run it), e.g. "mf6/" or "mf2005/". Relative path parts below the initial prefix reflect the model's relative path within its repository.