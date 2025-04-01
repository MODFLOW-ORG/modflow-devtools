# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 example models via [Pooch](https://www.fatiando.org/pooch/latest/index.html). Example usage:

```python
import modflow_devtools.models as models
from flopy.mf6 import MFSimulation

workspace = models.copy_to("some/path", "some_model")
sim = MFSimulation.load(sim_ws=workspace)
```

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
```