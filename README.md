# MODFLOW developer tools

[![CI](https://github.com/MODFLOW-ORG/modflow-devtools/actions/workflows/ci.yml/badge.svg)](https://github.com/MODFLOW-ORG/modflow-devtools/actions/workflows/ci.yml)
[![Documentation Status](https://readthedocs.org/projects/modflow-devtools/badge/?version=latest)](https://modflow-devtools.readthedocs.io/en/latest/?badge=latest)
[![GitHub contributors](https://img.shields.io/github/contributors/MODFLOW-ORG/modflow-devtools)](https://img.shields.io/github/contributors/MODFLOW-ORG/modflow-devtools)
[![GitHub tag](https://img.shields.io/github/tag/MODFLOW-ORG/modflow-devtools.svg)](https://github.com/MODFLOW-ORG/modflow-devtools/tags/latest)

[![PyPI License](https://img.shields.io/pypi/l/modflow-devtools)](https://pypi.python.org/pypi/modflow-devtools)
[![PyPI Status](https://img.shields.io/pypi/status/modflow-devtools.png)](https://pypi.python.org/pypi/modflow-devtools)
[![PyPI Format](https://img.shields.io/pypi/format/modflow-devtools)](https://pypi.python.org/pypi/modflow-devtools)
[![PyPI Version](https://img.shields.io/pypi/v/modflow-devtools.png)](https://pypi.python.org/pypi/modflow-devtools)
[![PyPI Versions](https://img.shields.io/pypi/pyversions/modflow-devtools.png)](https://pypi.python.org/pypi/modflow-devtools)

[![Anaconda License](https://anaconda.org/conda-forge/modflow-devtools/badges/license.svg)](https://anaconda.org/conda-forge/modflow-devtools/badges/license.svg)
[![Anaconda Version](https://anaconda.org/conda-forge/modflow-devtools/badges/version.svg)](https://anaconda.org/conda-forge/modflow-devtools)
[![Anaconda Updated](https://anaconda.org/conda-forge/modflow-devtools/badges/latest_release_date.svg)](https://anaconda.org/conda-forge/modflow-devtools)

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

Python development tools for MODFLOW 6 and related projects.

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Documentation](#documentation)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Features

* a minimal GitHub API client for release info/assets
* a `ZipFile` subclass that [preserves file permissions](https://stackoverflow.com/questions/39296101/python-zipfile-removes-execute-permissions-from-binaries) (workaround for [Python #15795](https://bugs.python.org/issue15795))
* pytest fixtures including "keepable" temporary directories and snapshot testing utilities
* pytest markers to skip test cases conditional on operating system, installed packages, or available executables
* a parser for MODFLOW 6 [definition files](https://modflow6.readthedocs.io/en/stable/_dev/dfn.html)
* a models API for streamlined access to MODFLOW 6 (and other) models in
  - [`MODFLOW-ORG/modflow6-examples`](https://github.com/MODFLOW-ORG/modflow6-examples)
  - [`MODFLOW-ORG/modflow6-testmodels`](https://github.com/MODFLOW-ORG/modflow6-testmodels)
  - [`MODFLOW-ORG/modflow6-largetestmodels`](https://github.com/MODFLOW-ORG/modflow6-largetestmodels)

## Requirements

Python3.10+, dependency-free by default.

Two main dependency groups are available, oriented around specific use cases:

- `test`: pytest fixtures, markers, and extensions
- `ecosystem`: program/model management, definition file utilities

## Installation

`modflow-devtools` is available on PyPI and can be installed with pip:

```shell
pip install modflow-devtools
```

To install an optional dependency group:

```shell
pip install "modflow-devtools[test]"
```

To install from source and set up a development environment please see the [developer documentation](DEVELOPER.md).

To use the `pytest` fixtures provided by `modflow-devtools`, add the following to a test file or `conftest.py` file:

```python
pytest_plugins = [ "modflow_devtools.fixtures" ]
```

**Note**: this must be a top-level `conftest.py`, which nested `conftest.py` files may then override or extend.

## Documentation

Docs are available at [modflow-devtools.readthedocs.io](https://modflow-devtools.readthedocs.io/en/latest/).

For more info on MODFLOW 6 see [the USGS overview](https://water.usgs.gov/ogw/modflow/).
