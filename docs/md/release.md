# Release actions

Shared CI and release tooling for MODFLOW program repositories.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Overview](#overview)
- [Requirements](#requirements)
  - [Build system](#build-system)
  - [Version](#version)
  - [Commits](#commits)
  - [Repository settings](#repository-settings)
- [Build workflow](#build-workflow)
- [Release workflow](#release-workflow)
  - [Branching models](#branching-models)
  - [Making a release](#making-a-release)
- [Release assets](#release-assets)
- [Actions](#actions)
- [Versioning](#versioning)
- [Testing](#testing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Overview

`modflow-devtools` provides

- composite actions ([`actions/`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/actions)) for building, checking, packaging and releasing programs
- the `modflow_devtools.release` modules the actions run, for versioning and changelog generation
- example workflows ([`docs/examples/`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples)) to copy into program repositories

Each program repository owns its workflows. Builds and tests differ between programs, so the build workflow is the repository's own, and it's short since the involved parts (compiler setup, static runtime linking on macOS, linkage checks, packaging) are actions. The release procedure should be the same everywhere, so its logic lives in the `release-start` and `release-finish` actions, and a program's release workflow just wires them up around its build workflow.

The actions are meant for the simpler program repos (mfusg, mfnwt, mt3d-usgs, etc). MODFLOW 6 has a more complex release procedure and keeps its own workflows, but can use some of the actions, and its releases should follow the same [asset conventions](#release-assets). Releases following the conventions can be installed with the [Programs API](programs.md).

## Requirements

A program repository must satisfy the following to use the actions.

### Build system

The program should build with [Meson](https://mesonbuild.com/) and [pixi](https://pixi.sh/). Programs in Fortran, C, or C++ are supported. `pixi.toml` must be at the repository root, and `pixi.lock` should be committed.

How the program is built and tested is up to the repository's build workflow. The examples assume pixi tasks like

```toml
[tasks]
setup = "meson setup --prefix=$PIXI_PROJECT_ROOT --bindir=bin"
build = "meson install -C"
test = "meson test --verbose --no-rebuild -C builddir"
```

Executables must install to `bin/` at the repository root. Everything in `bin/` goes in the release archives, so nothing else should be installed there. If the program has a double precision build, its executables must have different names than the single precision ones (e.g. `mfusg` and `mfusgdbl`).

Don't set `link_language: 'fortran'` on executables. With Intel, it makes Meson append `-lifcore -limf` after `-static-intel`, so the executables link the Intel runtime dynamically. The `check-linkage` action catches this.

Compilers are installed with [setup-fortran](https://github.com/fortran-lang/setup-fortran), which also sets `CC` and `CXX`. Releases should be built with Intel `ifx` on Linux and Windows, and with GNU Fortran on macOS.

### Version

The version must be set in `meson.build`, either directly

```meson
project(
  'mfusg',
  'fortran',
  version: '1.6.0.dev0',
  ...
```

or read from a file with `version: files('version.txt')`.

Release versions are `major.minor.patch`. Between releases, the repository holds the next minor version with a `.devN` suffix, where `N` is the last release's patch number as in MODFLOW 6, e.g. `1.6.0.dev0` after `1.5.0` and `1.6.0.dev2` after `1.5.2`. Programs with `major.minor` versions should switch to `major.minor.0` at their next release.

If `pixi.toml` has a `version`, it is kept in sync with `meson.build`. Other files containing the version, e.g. a version string in the source code, can be listed in `release.toml` at the repository root:

```toml
[[version-files]]
path = "src/mfusg.f"
# exactly one capture group, matching the text to replace
pattern = "PARAMETER \\(VERSION='([^']*)'\\)"
# optional, {version} and {date} (UTC) are available
format = "{version} {date:%m/%d/%Y}"
```

To get or set the version locally:

```shell
python -m modflow_devtools.release.version --root ../mfusg --get
python -m modflow_devtools.release.version --root ../mfusg --set 1.6.0.dev0
```

### Commits

Release notes are generated with [git-cliff](https://git-cliff.org/) from [conventional commits](https://www.conventionalcommits.org/) since the last release. Only `feat`, `fix` and `perf` commits are included, and commits scoped `ci` (e.g. `fix(ci)`) are skipped.

The repository may provide its own `cliff.toml`, otherwise the [shared one](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/modflow_devtools/release/cliff.toml) is used. If there is no `CHANGELOG.md`, one is created at the first release.

### Repository settings

The release actions create pull requests with the workflow token. This must be enabled under *Settings* -> *Actions* -> *General* -> *Allow GitHub Actions to create and approve pull requests*.

Program repositories should also enable [dependabot](https://docs.github.com/en/code-security/dependabot) for GitHub Actions, since their workflows pin action versions.

## Build workflow

Copy [`docs/examples/build.yml`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples/build.yml) to `.github/workflows/build.yml` and adapt it. It runs on pushes, pull requests and a weekly schedule, and on each matrix entry

- checks out the repository
- sets up the compiler and pixi with the `setup` action
- builds single and double precision
- runs the tests
- checks the executables' linkage with the `check-linkage` action

The build workflow must also accept `workflow_call` with inputs `ref` (what to check out) and `release` (whether to upload archives), since the release workflow calls it. In a release build, one job per platform must run the `package` action with `upload: true`. The example marks those matrix entries `release: true`.

## Release workflow

Copy [`docs/examples/release.yml`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples/release.yml) to `.github/workflows/release.yml` and set the program's name and long name. It has three jobs:

- `start`: the `release-start` action decides what to do, see [Making a release](#making-a-release)
- `build`: calls the repository's build workflow on the release branch or commit
- `finish`: the `release-finish` action opens the release pull request, or publishes the release

`release-start` inputs:

- `version`: pass `${{ inputs.version }}`
- `long-name`: program long name, used in the shared changelog header (required)
- `main-branch`: branch releases are merged into and tagged on (default `main`)
- `develop-branch`: development branch, if not the main branch, see [Branching models](#branching-models)

`release-finish` inputs:

- `stage`, `ref`, `version`: pass `release-start`'s outputs
- `name`: program name, used for the source archive and release title (required)
- `long-name`: program long name, used in the release notes (required)
- `main-branch`, `develop-branch`: as for `release-start`
- `platforms`: OS tags that must each have an archive (default `linux macarm win64`)

### Branching models

Two branching models are supported:

- **single**: development and releases both happen on `main`. Release branches are created from and merged back into `main`. This is the default.
- **dual**: development happens on `develop`, as in MODFLOW 6. Release branches are created from `develop` and merged into `main`, where the release is tagged. `main` is then merged back into `develop`. Set `develop-branch: develop` on both release actions to use this model.

In the dual model, the pull request that sets the next development version also merges `main` back into `develop`. It must be merged with a merge commit, not squashed, so the release tag is reachable from `develop`. Otherwise the next release's notes will repeat this release's changes.

### Making a release

To make a release:

1. Run the release workflow from the development branch (*Actions* -> *release* -> *Run workflow*) with the version to release, e.g. `1.5.2`. The workflow
   - creates branch `release/v1.5.2`
   - sets the version
   - updates `CHANGELOG.md`
   - builds and tests on each platform
   - opens a pull request into `main`
2. Review the pull request. The version's section in `CHANGELOG.md` becomes the release notes, so edit it on the release branch if needed.
3. Merge the pull request. If the version on `main` is a release version without a tag, the workflow
   - builds and tests on each platform again
   - publishes release `v1.5.2` with the archives, targeting the merge commit
   - opens a pull request setting the next development version (e.g. `1.6.0.dev2`) on the development branch
4. Merge that pull request.

On any other push to `main`, `release-start` finds nothing to do and the other jobs are skipped.

**Note:** pull requests created with the workflow token don't trigger other workflows, so the build workflow doesn't run on them. The release workflow already built and tested the release branch in step 1. To run the build workflow anyway, close and reopen the pull request.

## Release assets

Program releases share a common layout, so the [executables](https://github.com/MODFLOW-ORG/executables) distribution and [modflow-devtools](https://github.com/MODFLOW-ORG/modflow-devtools) can treat every program the same way:

- tag `vX.Y.Z`
- one archive per platform, named for the [OS tag](ostags.md): `linux.zip`, `macarm.zip`, and `win64.zip`
- executables at the archive root, no enclosing directory, double precision executables included if any
- optionally, `<name>_source.zip`
- no dynamic linking to compiler runtime libraries, i.e. Intel's on Linux or GNU's on macOS

The `package` action produces this layout, and `release-finish` refuses to publish missing or unexpected archives.

Intel macOS (`mac`) is no longer supported.

## Actions

- `actions/setup`: set up the compiler and pixi, and on macOS, Xcode and static GCC runtime linking
- `actions/check-linkage`: list each executable's shared library dependencies and fail on compiler runtime libraries, and on macOS, check for arm64
- `actions/package`: zip `bin/` as `<ostag>.zip`, and on Linux the source as `<name>_source.zip`, optionally uploading them as artifact `dist-<ostag>`
- `actions/release-start`: prepare the release branch, or check whether `main` needs releasing
- `actions/release-finish`: open the release pull request, or publish the release and open the next version pull request
- `actions/version`: get or set the version, or get the next development version
- `actions/changelog`: update `CHANGELOG.md` with git-cliff, or get a version's release notes

See each `action.yml` for inputs and outputs.

## Versioning

The actions are versioned with `modflow-devtools`. Program repositories reference them at a release tag, e.g. `MODFLOW-ORG/modflow-devtools/actions/setup@1.10.0`, and dependabot proposes updates with each `modflow-devtools` release. Breaking changes to the actions (e.g. renamed or removed inputs, or a different asset layout) follow the package's versioning.

## Testing

`.github/workflows/actions.yml` runs the script tests, lints the example workflows, and runs the actions from the commit under test on a small Fortran program in `autotest/release` on each release platform. It runs only on changes to the actions, the scripts, the fixture or the examples.

To run the script tests locally:

```shell
cd autotest
pytest test_release.py
```

The changelog tests require `git-cliff` and are skipped if it's not installed.
