# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 example models via [Pooch](https://www.fatiando.org/pooch/latest/index.html).

When the module is imported, it checks for the existence of the registry in models files. If they are found, it loads the registry and dynamically generates functions for each model, attaching them to the module namespace.

Each function returns a list of files. Example usage:

```python
import modflow_devtools.models as models

files = models.some_model()
```

## Developers

The `make_registry.py` script is responsible for generating a registry text file and a mapping between files and models. This script should be run in the CI pipeline at release time before the package is built. The generated registry file and model mapping are used to create a pooch instance for fetching model files, and should be distributed with the package.

The script can be executed with `python -m modflow_devtools.make_registry` and accepts the following options:

- `--path` or `-p`: Specifies the directory containing model directories. If not provided, the default path is used.
- `--append` or `-a`: If specified, the script will append to the existing registry file instead of overwriting it.
- `--base-url` or `-b`: Specifies the base URL for the registry file. If not provided, the default base URL is used.

For example, to create a registry of models in the MF6 test models repositories, each of which is checked out in the current working directory:

```shell
python -m modflow_devtools.make_registry -p modflow6-testmodels -b https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master
python -m modflow_devtools.make_registry -a -p modflow6-largetestmodels -b https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master
```