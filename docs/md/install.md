# Installation

## Installing `modflow-devtools` from PyPI

Packages are [available on PyPi](https://pypi.org/project/modflow-devtools/) and can be installed with `pip`:

```shell
pip install modflow-devtools
```

## Installing `modflow-devtools` from source

To set up a `modflow-devtools` development environment, first clone the repository:

```shell
git clone https://github.com/MODFLOW-ORG/modflow-devtools.git
```

Then install the local copy as well as testing, linting, and docs dependencies:

```
pip install .
pip install ".[lint, test, docs]"
```

## Using `modflow-devtools` as a `pytest` plugin

Fixtures provided by `modflow-devtools` can be imported into a `pytest` test suite by adding the following to the consuming project's top-level `conftest.py` file:

```python
pytest_plugins = ["modflow_devtools.fixtures"]
```

## Installing external model repositories

`modflow-devtools` provides fixtures to load models from external repositories:

- [`MODFLOW-ORG/modflow6-examples`](https://github.com/MODFLOW-ORG/modflow6-examples)
- [`MODFLOW-ORG/modflow6-testmodels`](https://github.com/MODFLOW-ORG/modflow6-testmodels)
- [`MODFLOW-ORG/modflow6-largetestmodels`](https://github.com/MODFLOW-ORG/modflow6-largetestmodels)

By default, these fixtures expect model repositories to live next to (i.e. in the same parent directory as) the consuming project repository. If the repos are somewhere else, you can set the `REPOS_PATH` environment variable to point to their parent directory.

**Note:** a convenient way to persist environment variables needed for tests is to store them in a `.env` file in the `autotest` folder. Each variable should be defined on a separate line, with format `KEY=VALUE`. The `pytest-dotenv` plugin will then automatically load any variables found in this file into the test process' environment.

### Installing test models

The test model repos can simply be cloned &mdash; ideally, into the parent directory of the `modflow6` repository, so that repositories live side-by-side:

```shell
git clone https://github.com/MODFLOW-ORG/modflow6-testmodels.git
git clone https://github.com/MODFLOW-ORG/modflow6-largetestmodels.git
```

### Installing example models

First clone the example models repo:

```shell
git clone https://github.com/MODFLOW-ORG/modflow6-examples.git
```

The example models require some setup after cloning. Some extra Python dependencies are required to build the examples: 

```shell
cd modflow6-examples/etc
pip install -r requirements.pip.txt
```

Then, from the `autotest` folder, run:

```shell
pytest -v -n auto test_scripts.py --init
```

This will build the examples for subsequent use by the tests. To save time, models will not be run &mdash; to run the models too, omit `--init`.
