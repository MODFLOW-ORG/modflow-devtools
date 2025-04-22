# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 example models via [Pooch](https://www.fatiando.org/pooch/latest/index.html).

## Listing models

The `get_models()` function returns a mapping of model names to model input files.

```python
from pprint import pprint
import modflow_devtools.models as models

pprint(list(models.get_models())[:5])
```

```
['mf6/example/ex-gwe-ates',
 'mf6/example/ex-gwe-barends/mf6gwe',
 'mf6/example/ex-gwe-barends/mf6gwf',
 'mf6/example/ex-gwe-danckwerts',
 'mf6/example/ex-gwe-geotherm/mf6gwe']
```

### Model names

Model names follow a hierarchical addressing scheme.

The leading part identifies the kind of model, e.g. `mf6`, `mf2005`, etc. Subsequent parts may be used to classify the model.

Currently the following prefixes are in use:

- `mf6/example/...`: mf6 example models in https://github.com/MODFLOW-ORG/modflow6-examples
- `mf6/test/...`: mf6 test models in https://github.com/MODFLOW-ORG/modflow6-testmodels
- `mf6/large/...`: large mf6 test models in https://github.com/MODFLOW-ORG/modflow6-largetestmodels
- `mf2005/...`: mf2005 models in https://github.com/MODFLOW-ORG/modflow6-testmodels

The remaining parts may reflect the relative location of the model within the source repository.

**Note**: until this module stabilizes, model naming conventions may change without notice.

## Using models

To copy model input files to a workspace of your choosing:

```python
from tempfile import TemporaryDirectory

with TemporaryDirectory() as td:
    workspace = models.copy_to(td, "example/ex-gwe-ates", verbose=True)
```

If the target directory doesn't exist, it will be created.

## Developers

The `make_registry.py` script is responsible for generating a registry text file and a mapping between files and models. This script should be run in the CI pipeline at release time before the package is built. The generated registry file and model mapping are used to create a pooch instance for fetching model files, and should be distributed with the package.

The script can be executed with `python -m modflow_devtools.make_registry`. It accepts a single positional argument, specifying the base directory containing model directories. It accepts two named arguments:

- `--append` or `-a`: If specified, the script will append to the existing registry file instead of overwriting it.
- `--url` or `-u`: Specifies the base URL for the registry file. If not provided, the default base URL is used.

For example, to create a registry of models in the MF6 examples and test models repositories, assuming each is checked out next to this project:

```shell
python -m modflow_devtools.make_registry ../modflow6-examples/examples --url https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip --prefix mf6/example
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6 --prefix mf6/test
python -m modflow_devtools.make_registry ../modflow6-largetestmodels --append --url https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master --prefix mf6/large
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf5to6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf5to6 --prefix mf2005 --namefile "*.nam"
```

Above we adopt a convention of prefixing model names with the model type (i.e. the program used to run it), e.g. "mf6/" or "mf2005/". Relative path parts below the initial prefix reflect the model's relative path within its repository.