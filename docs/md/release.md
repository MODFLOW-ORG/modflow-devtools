# Release actions

Shared CI and release tooling for MODFLOW program repositories.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Overview](#overview)
- [Requirements](#requirements)
  - [Build system](#build-system)
  - [Version](#version)
  - [release.toml](#releasetoml)
  - [Release notes](#release-notes)
  - [Repository settings](#repository-settings)
- [Build workflow](#build-workflow)
- [Release workflow](#release-workflow)
  - [Branching models](#branching-models)
  - [Making a release](#making-a-release)
  - [Rerunning a release](#rerunning-a-release)
  - [Adopting the release workflow](#adopting-the-release-workflow)
- [Release assets](#release-assets)
- [Actions](#actions)
- [Versioning](#versioning)
- [Testing](#testing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Overview

`modflow-devtools` provides

- composite actions ([`actions/`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/actions)) for building, checking, packaging and releasing programs
- the `modflow_devtools.release` modules the actions run, for versioning, changelog generation, packaging, and the release workflow's stages
- example workflows ([`docs/examples/`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples)) to copy into program repositories

Each program repository owns its workflows. Builds and tests differ between programs, so the build workflow is the repository's own, and it's short since the involved parts (compiler setup, static runtime linking on macOS, linkage checks, packaging) are actions. The release procedure should be the same everywhere, so its logic lives in the `release-start` and `release-finish` actions (implemented in `modflow_devtools/release/workflow.py`, so it can be tested), and a program's release workflow just wires them up around its build workflow. Conventions every program should share, like the changelog format, static linking and the release asset layout, are fixed rather than configurable.

The actions are meant for the simpler program repos (mfusg, mfnwt, mt3d-usgs, etc). MODFLOW 6 has a more complex release procedure and keeps its own workflows, but can use some of the actions, and its releases should follow the same [asset conventions](#release-assets). Releases following the conventions can be installed with the [Programs API](programs.md).

## Requirements

A program repository must satisfy the following to use the actions.

### Build system

The program should build with [Meson](https://mesonbuild.com/) and [pixi](https://pixi.sh/), and may be written in Fortran, C or C++. `pixi.lock` should be committed.

The program's files (`meson.build`, `pixi.toml`, `release.toml`, `CHANGELOG.md` if generated and `bin/`) are expected at the repository root. If they're in a subdirectory, pass it to every action as `path` (to `check-linkage`, the `bin/` directory). The changelog still covers the whole repository's history.

How the program is built and tested is up to the repository's build workflow. The examples assume pixi tasks like

```toml
[tasks]
setup = "meson setup --prefix=$PIXI_PROJECT_ROOT --bindir=bin"
build = "meson install -C"
test = "meson test --verbose --no-rebuild -C builddir"
```

Executables must install to `bin/` at the repository root. Everything in `bin/` goes in the release archives, so nothing else should be installed there. If the program has a double precision build, its executables must have different names than the single precision ones (e.g. `mfusg` and `mfusgdbl`).

For a Fortran program, gfortran comes from the pixi environment, i.e. from conda-forge, so `pixi.toml` must depend on it:

```toml
[dependencies]
gfortran = "15.*"
```

If gfortran is in another pixi environment, pass it to the `setup` action as `pixi-environment`, and run the build in that environment.

Intel compilers are installed with [setup-fortran](https://github.com/fortran-lang/setup-fortran), which also sets `FC`, `CC` and `CXX`. Releases should be built with Intel `ifx` on Linux and Windows, and with gfortran on macOS.

Executables must link the compiler runtime libraries statically, so users don't need the compiler installed. The `setup` action sets `LDFLAGS` for this: `-static-libgfortran -static-libgcc -static-libquadmath` for gfortran (`-static` on Windows), and `-static-intel -static-libgcc` for Intel on Linux, plus `-static-libstdc++` for either on Linux. On macOS, the C++ runtime (libc++) is a system library. On Windows, Intel builds need Meson's `b_vscrt` option, which `LDFLAGS` can't set, so `meson.build` must have

```meson
default_options: ['b_vscrt=static_from_buildtype', 'buildtype=release'],
```

Don't set `link_language` on executables. With Intel, `'fortran'` makes Meson append `-lifcore -limf` after `-static-intel`, so the executables link the Intel runtime dynamically, and `'cpp'` likewise appends `-lstdc++`. The `check-linkage` action catches this, and any other library the operating system doesn't provide.

Binaries must also run on older systems than the build machines:

- **Linux**: glibc 2.34 (RHEL 9) or older. Binaries built with gfortran from conda-forge link against an old glibc, whatever the build machine has. Intel builds link against the build machine's glibc, so build them on the oldest available runner. `ubuntu-22.04` has glibc 2.35, so its binaries pass only if they don't use a function added in 2.35, which `check-linkage` checks.
- **macOS**: macOS 14.0 or newer, on Apple silicon. The `setup` action sets `MACOSX_DEPLOYMENT_TARGET=14.0`; without it, binaries require the build machine's macOS version.

### Version

The version must be set in `meson.build`'s `project()` call, either directly

```meson
project(
  'mfusg',
  'fortran',
  version: '1.6.0.dev0',
  ...
```

or read from a file with `version: files('version.txt')`.

Release versions are `major.minor.patch`, with plain integers: `release-start` rejects zero padding like `1.12.02` (release it as `1.12.2`), and the development version after `1.0.03` is `1.1.0.dev3`. Between releases, the repository holds the next minor version with a `.devN` suffix, where `N` is the last release's patch number as in MODFLOW 6, e.g. `1.6.0.dev0` after `1.5.0` and `1.6.0.dev2` after `1.5.2`. Programs with `major.minor` versions should switch to `major.minor.0` at their next release.

Only `project()`'s `version` keyword counts, so e.g. a `dependency()`'s `version` doesn't. If `pixi.toml` has a `version`, it is kept in sync with `meson.build`, as are any files listed in [`release.toml`](#releasetoml).

To get or set the version locally:

```shell
python -m modflow_devtools.release.version --root ../mfusg --get
python -m modflow_devtools.release.version --root ../mfusg --set 1.6.0.dev0
python -m modflow_devtools.release.version --root ../mfusg --files
```

Setting the version checks every file before writing any, so if one file has no version, or more than one, nothing changes.

### release.toml

`release.toml` at the repository root names the program, for the source archive, the release title, the changelog header and the release notes. It also says where [curated release notes](#release-notes) are, if any. Other files containing the version, e.g. a version string in the source code, can be listed there too:

```toml
name = "mfusg"
long-name = "MODFLOW-USG"

[[version-files]]
path = "src/mfusg.f"
# exactly one capture group, matching the text to replace
pattern = "PARAMETER \\(VERSION='([^']*)'\\)"
# optional, {version} and {date} (UTC) are available
format = "{version} {date:%m/%d/%Y}"
```

### Release notes

Release notes can be generated or curated.

**Generated** (the default): release notes are generated with [git-cliff](https://git-cliff.org/) from [conventional commits](https://www.conventionalcommits.org/) since the last release into `CHANGELOG.md`, and the version's section becomes the GitHub release's description. Only `feat`, `fix` and `perf` commits are included, and commits scoped `ci` (e.g. `fix(ci)`) are skipped.

Every program uses the [shared git-cliff template](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/modflow_devtools/release/cliff.toml), so changelogs look the same everywhere and the release notes can be found by their `## Version X.Y.Z` headings. Repositories can't supply their own. git-cliff runs at a version pinned in `modflow_devtools/release/changelog.py`, with `pipx run` or `uvx`, so nothing needs installing. If there is no `CHANGELOG.md`, one is created at the first release, from the commits since the last release tag, or the whole history if there is none. Release tags are `vX.Y.Z`, but older `X.Y.Z` tags are recognized too. Entries link the pull request if the commit message ends with its number, e.g. `fix: read the thing (#12)` from a squash merge, and otherwise link the commit.

**Curated**: release notes are written by hand in a Markdown file in the repository, with a `## Version X.Y.Z` section per release, newest first, in the same format as `CHANGELOG.md`. Name the file in `release.toml`:

```toml
[release-notes]
path = "doc/release-notes.md"
# optional, a document built from the notes and attached to the release
asset = "ReleaseNotes.pdf"
```

Then git-cliff doesn't run, and the version's section of the file becomes the GitHub release's description. Write it on the development branch before starting the release, or on the release branch. Commit messages needn't follow a convention, though conventional commits are still recommended.

If the release notes are also published as a document, e.g. a PDF, set `asset` to its file name. Build it from the notes in CI rather than committing it, so it can't go stale: the example [build workflow](#build-workflow) has a job that builds a PDF with pandoc on every build, so reviewers can check it, and uploads it as a `dist-notes` artifact on release builds. List it in `release-finish`'s `extra-assets`. `release-finish` refuses to publish if the asset isn't attached, and the release's description links to it.

### Repository settings

The release actions push branches and create pull requests and releases with the token passed as `github-token` to `release-finish` (and to `actions/checkout`, for the pushes). By default this is the workflow token, which has two drawbacks:

- pull requests it creates don't trigger other workflows, so required checks never run on the release pull requests
- creating pull requests with it must be enabled under *Settings* -> *Actions* -> *General* -> *Allow GitHub Actions to create and approve pull requests*

A [GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow) installation token avoids both, and is recommended for the organization. Create the token with [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token) in the `start` and `finish` jobs, and pass it to `actions/checkout` and `release-finish`. The app needs read and write access to contents and pull requests.

Program repositories should also enable [dependabot](https://docs.github.com/en/code-security/dependabot) for GitHub Actions, since their workflows pin action versions.

## Build workflow

Copy [`docs/examples/build.yml`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples/build.yml) to `.github/workflows/build.yml` and adapt it. It runs on pushes, pull requests and a weekly schedule, and on each matrix entry

- checks out the repository
- sets up the compiler and pixi with the `setup` action
- builds single and double precision
- runs the tests
- checks the executables' linkage with the `check-linkage` action
- packages the executables with the `package` action

With curated release notes published as a document, uncomment the example's `notes` job and adapt it to build the document.

The build workflow must also accept `workflow_call` with inputs `ref` (what to check out) and `release` (whether to upload archives), since the release workflow calls it. In a release build, one job per platform must run the `package` action with `upload: true`. The example marks those matrix entries `release: true`, and packages every build so packaging problems show up before a release.

## Release workflow

Copy [`docs/examples/release.yml`](https://github.com/MODFLOW-ORG/modflow-devtools/blob/develop/docs/examples/release.yml) to `.github/workflows/release.yml`. It has three jobs:

- `start`: the `release-start` action decides what to do, see [Making a release](#making-a-release)
- `build`: calls the repository's build workflow on the release branch or commit
- `finish`: the `release-finish` action opens the release pull request, or publishes the release

`release-start` inputs:

- `version`: pass `${{ inputs.version }}`
- `main-branch`: branch releases are merged into and tagged on (default `main`)
- `develop-branch`: development branch, if not the main branch, see [Branching models](#branching-models)

`release-finish` inputs:

- `stage`, `ref`, `version`: pass `release-start`'s outputs
- `main-branch`, `develop-branch`: as for `release-start`
- `extra-assets`: newline-separated globs of other files to attach to the release, e.g. `doc/*.pdf`, matched relative to the checkout and to the downloaded `dist-*` artifacts. Each must match a file. To attach a file built in another job, e.g. a PDF of the release notes, upload it as an artifact named `dist-<something>` and list it here.

### Branching models

Two branching models are supported:

- **single**: development and releases both happen on `main`. Release branches are created from and merged back into `main`. This is the default.
- **dual**: development happens on `develop`, as in MODFLOW 6. Release branches are created from `develop` and merged into `main`, where the release is tagged. `main` is then merged back into `develop`. Set `develop-branch: develop` on both release actions to use this model.

In the dual model, the pull request that sets the next development version also merges `main` back into `develop`. It must be merged with a merge commit, not squashed, so the release tag is reachable from `develop`. Otherwise the next release's notes would repeat this release's changes, so `release-start` refuses to start a release from `develop` until the last release tag is reachable from it.

### Making a release

To make a release:

1. Run the release workflow from the development branch (*Actions* -> *release* -> *Run workflow*) with the version to release, e.g. `1.5.2`. The workflow
   - checks that `1.5.2` is newer than the last release tag
   - creates branch `release/v1.5.2`, or builds it as is if it exists
   - sets the version
   - updates `CHANGELOG.md`, if the release notes are generated
   - builds and tests on each platform
   - opens a pull request into `main`
2. Review the pull request. The version's section of the release notes (`CHANGELOG.md`, or the curated file) becomes the release's description, so edit it on the release branch if needed. With generated release notes, if there were no `feat`, `fix` or `perf` commits since the last release, the section is empty and the workflow warns. With curated release notes, the workflow warns if the section is missing or empty.
3. Merge the pull request. If the version on `main` is a release version without a tag, the workflow
   - checks that the release notes have a section for the version, failing before the build if not
   - builds and tests on each platform again
   - checks that the release notes asset, if any, is among the extra assets
   - publishes release `v1.5.2` with the archives and any extra assets, targeting the merge commit
   - opens a pull request from branch `post-release/v1.5.2` setting the next development version (e.g. `1.6.0.dev2`) on the development branch
4. Merge that pull request.

On any other push to `main`, `release-start` finds nothing to do and the other jobs are skipped.

**Note:** pull requests created with the workflow token don't trigger other workflows, so the build workflow doesn't run on them. The release workflow already built and tested the release branch in step 1. To run the build workflow anyway, close and reopen the pull request, or use an app token (see [Repository settings](#repository-settings)).

### Rerunning a release

Each step checks whether it's already done, so a failed release can be rerun:

- In step 1, rerunning the workflow, or dispatching it again with the same version, reuses the existing `release/vX.Y.Z` branch, including any fixes pushed to it, and opens the pull request if there isn't one. To start over, delete the branch.
- In step 3, use *Re-run failed jobs*. A published release isn't published again, a draft left by a failed upload is replaced, and the next version pull request is only opened if there isn't an open or merged one from `post-release/vX.Y.Z`. Rerunning *all* jobs does nothing once the tag exists, since `release-start` then finds nothing to release.

### Adopting the release workflow

`release-start` publishes any untagged release version it finds on the main branch, so before adding the release workflow, make sure the version there is either tagged `vX.Y.Z` or a development version. Otherwise the first push to the main branch tries to release it, and fails if the release notes have no section for it. Tag the last release `vX.Y.Z` on the commit it was made from, if it isn't already, so the first changelog only covers changes since then. Two-part tags like `v3.01` aren't recognized, so tag such a release `v3.1.0` too.

## Release assets

Program releases share a common layout, so the [executables](https://github.com/MODFLOW-ORG/executables) distribution and [modflow-devtools](https://github.com/MODFLOW-ORG/modflow-devtools) can treat every program the same way:

- tag `vX.Y.Z`
- one archive per platform, named for the [OS tag](ostags.md): `linux.zip`, `macarm.zip`, and `win64.zip`
- executables at the archive root, no enclosing directory, double precision executables included if any
- optionally, `<name>_source.zip`
- optionally, extra assets like documentation, named differently from the archives
- executables and shared libraries linking only libraries the operating system provides, so no compiler runtime libraries (Intel's, GNU's, the C++ runtime, or the Microsoft Visual C++ runtime): on Linux, libc, libm, libdl, libpthread, librt and the dynamic loader; on macOS, libraries under `/usr/lib` and `/System/Library`; on Windows, core system DLLs (`kernel32`, `ntdll`, the Universal CRT, etc.)
- on Linux, glibc 2.34 or older; on macOS, arm64 binaries supporting macOS 14.0 and later

The `package` action produces this layout the same way on every platform, `check-linkage` enforces the static linking, and `release-finish` refuses to publish missing or unexpected archives.

Intel macOS (`mac`) is not supported.

## Actions

- `actions/setup`: set up the compiler (Intel with setup-fortran, gfortran from pixi), pixi, optionally Xcode, static runtime linking, and on macOS the minimum macOS version
- `actions/check-linkage`: list the shared library dependencies of each binary in a directory and fail on any library the operating system doesn't provide, on a too new glibc (Linux), or on a missing arm64 build or too new minimum macOS version (macOS)
- `actions/package`: zip `bin/` as `<ostag>.zip`, and on Linux the source as `<name>_source.zip`, optionally uploading them as artifact `dist-<ostag>`
- `actions/release-start`: prepare the release branch, or check whether `main` needs releasing
- `actions/release-finish`: open the release pull request, or publish the release with any extra assets and open the next version pull request

See each `action.yml` for inputs and outputs.

## Versioning

The actions are versioned with `modflow-devtools`. Program repositories reference them at a release tag, e.g. `MODFLOW-ORG/modflow-devtools/actions/setup@1.10.0`, and dependabot proposes updates with each `modflow-devtools` release. Breaking changes to the actions (e.g. renamed or removed inputs, or a different asset layout) follow the package's versioning.

## Testing

`.github/workflows/actions.yml` runs the module tests, lints the example workflows, and runs the actions from the commit under test on a small Fortran program in `autotest/release` on each release platform. It runs only on changes to the actions, the modules, the fixture or the examples.

The release workflow's stages are tested against a local bare git repository as `origin` and a fake `gh` that records pull requests and releases, including reruns of each stage. Those tests are skipped on Windows.

To run the script tests locally:

```shell
cd autotest
pytest test_release.py
```

The changelog test runs git-cliff with `pipx` or `uvx`, and is skipped if neither is installed.
