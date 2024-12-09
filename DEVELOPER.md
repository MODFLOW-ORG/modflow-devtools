# Developing `modflow-devtools`

This document provides guidance to set up a development environment and discusses conventions used in this project.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->


- [Requirements](#requirements)
- [Installation](#installation)
- [Testing](#testing)
  - [Environment variables](#environment-variables)
  - [Running the tests](#running-the-tests)
  - [Writing new tests](#writing-new-tests)
    - [Temporary directories](#temporary-directories)
- [Releasing](#releasing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Requirements

Python3.9+ is currently required. This project supports several recent versions of Python, loosely following [NEP 29](https://numpy.org/neps/nep-0029-deprecation_policy.html#implementation) and aiming to stay synchronized with [FloPy](https://github.com/modflowpy/flopy).

## Installation

To get started, first fork and clone this repository. Then install the project and core packages as well as linting and testing dependencies:

```shell
pip install .
pip install ".[lint, test]"
```

## Testing

This repository's tests use [`pytest`](https://docs.pytest.org/en/latest/) and several plugins.

### Environment variables

This repository's tests expect a few environment variables:

- `REPOS_PATH`: the path to MODFLOW 6 example model repositories
- `GITHUB_TOKEN`: a GitHub authentication token

These may be set manually, but the recommended approach is to configure environment variables in a `.env` file in the project root, for instance:

```
REPOS_PATH=/path/to/repos
GITHUB_TOKEN=yourtoken...
```

The tests use [`pytest-dotenv`](https://github.com/quiqua/pytest-dotenv) to detect and load variables from this file.

### Running the tests

Tests should be run from the `autotest` directory. To run the tests in parallel with verbose output:

```shell
pytest -v -n auto
```

### Writing new tests

Tests follow a few conventions for ease of use and maintenance.

#### Temporary directories

Tests which must write to disk use `pytest`'s built-in `temp_dir` fixture or one of this package's own scoped temporary directory fixtures.

## Releasing

The `modflow-devtools` release procedure is automated with GitHub Actions in [`.github/workflows/release.yml`](.github/workflows/release.yml). Making a release involves the following steps:

1. Release from `master` branch
2. Reinitialize the `develop` branch
3. Publish the package to PyPI

To begin an automated release, create a release branch from `develop`. The release branch name should be the version number of with a `v`a prefix (e.g., `v0.0.6`). Pushing the release branch to the `MODFLOW-USGS/modflow-devtools` repository will trigger the release workflow, which begins with the following steps:

- update version strings to match the version number in the release branch name
- generate a changelog since the last release and update `HISTORY.md`
- open a PR from the release branch to `master`

Merging the pull request into `master` triggers another job to draft a release.

**Note:** the PR should be merged, not squashed. Squashing removes the commit history from the `master` branch and causes `develop` and `master` to diverge, which can cause future PRs updating `master` to replay commits from previous releases.

Publishing the release triggers jobs to publish the `modflow-devtools` package to PyPI and open a PR updating `develop` from `master`. This PR also updates version strings, incrementing the patch version number.