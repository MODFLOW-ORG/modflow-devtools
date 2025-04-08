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
['example/ex-gwe-ates',
 'example/ex-gwe-barends/mf6gwe',
 'example/ex-gwe-barends/mf6gwf',
 'example/ex-gwe-danckwerts',
 'example/ex-gwe-geotherm/mf6gwe']
```

Model names follow a hierarchical addressing scheme.

The leading prefix identifies where the model came from. Currently three prefixes are in use:

- `example/...`: example models in https://github.com/MODFLOW-ORG/modflow6-examples
- `test/...`: test models in https://github.com/MODFLOW-ORG/modflow6-testmodels
- `large/...`: large test models in https://github.com/MODFLOW-ORG/modflow6-largetestmodels

The remaining path parts reflect the relative location of the model within the source repository.

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
python -m modflow_devtools.make_registry ../modflow6-examples/examples --url https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip --prefix example
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6 --prefix test
python -m modflow_devtools.make_registry ../modflow6-largetestmodels --append --url https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master --prefix large
python -m modflow_devtools.make_registry ../modflow6-testmodels/mf5to6 --append --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf5to6 --prefix mf2005 --namefile "*.nam"
```