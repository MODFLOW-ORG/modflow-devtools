# Programs API

> **Warning**: This API is experimental and may change or be removed in future versions without following normal deprecation procedures. Use at your own risk.
>
> When importing this module programmatically, you will see a `FutureWarning`. To suppress this warning:
> ```python
> import warnings
> warnings.filterwarnings('ignore', message='.*modflow_devtools.programs.*experimental.*')
> ```

The `modflow_devtools.programs` module installs MODFLOW and related program executables and tracks what's installed where. It is a generalized, in-tree successor to flopy's [`get_modflow.py`](https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py) utility: it supports the same three distributions `get_modflow.py` does, plus any other repo that publishes releases in the same shape - including installing directly from an individual program's own repo.

Unlike the [Models API](models.md) and DFNs API, there is no registry to sync here. Program binaries are a solved problem for a real package manager - conda-forge is the natural long-term home for installing MODFLOW programs, and this module isn't trying to compete with or duplicate that. What it does provide, regardless of how a program was installed, is a local **installation ledger**: a record of what's installed, where, at what version, from what source. See [Relationship to get-modflow and conda-forge](#relationship-to-get-modflow-and-conda-forge) below.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Installing a program](#installing-a-program)
- [Program sources](#program-sources)
- [Finding installed programs](#finding-installed-programs)
- [Recording installations from other sources](#recording-installations-from-other-sources)
- [Version management](#version-management)
- [Uninstalling](#uninstalling)
- [Platform support](#platform-support)
- [Cache and ledger layout](#cache-and-ledger-layout)
- [Relationship to get-modflow and conda-forge](#relationship-to-get-modflow-and-conda-forge)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Installing a program

```python
from modflow_devtools.programs import install_program

# Install mf6 from the modflow6 repo's latest release (auto-detects platform,
# auto-selects an installation directory)
installations = install_program("mf6", repo="modflow6")

# Install a specific version to a specific directory
install_program("mf6", repo="modflow6", version="6.8.0", bindir="/usr/local/bin")

# Install several programs from the combined 'executables' distribution
install_program(subset="mfnwt,mf2005", repo="executables", bindir="/usr/local/bin")

# Install everything in a release (no program/subset given)
install_program(repo="executables", bindir="/usr/local/bin")
```

Or via CLI:

```bash
mf programs install mf6 --repo modflow6
mf programs install mf6 --repo modflow6 --version 6.8.0 --bindir /usr/local/bin
mf programs install --repo executables --subset mfnwt,mf2005 --bindir /usr/local/bin
```

## Program sources

`repo` is **not** restricted to a fixed list - any repo under `owner` (default `MODFLOW-ORG`) with a GitHub release and a platform-matching asset works, including installing a single program directly from its own repo:

```python
install_program(repo="mfnwt", bindir="/usr/local/bin")
install_program(repo="gridgen", bindir="/usr/local/bin")
```

Or via CLI:

```bash
mf programs install --repo mfnwt --bindir /usr/local/bin
mf programs install --repo gridgen --bindir /usr/local/bin
```

`KNOWN_REPOS` names the three distributions `get_modflow.py` supports out of the box, which `install_program` still understands specially (see table below) - it's a set of well-known defaults, not an allowlist:

| `repo` | Contents | Versioning |
|---|---|---|
| `executables` (default) | Combined legacy distribution: many programs bundled in one archive, described by an embedded `code.json` manifest | Each program has its own version, read from `code.json` |
| `modflow6` | `mf6`, `zbud6`, `mf5to6`, `libmf6` | All share the release tag as their version |
| `modflow6-nightly-build` | Same programs as `modflow6`, nightly builds | All share the nightly build tag |

A growing number of individual program repos (`mfnwt`, `mt3d-usgs`, `vs2dt`, `gridgen`, `triangle`, `zonbud`, `zonbudusg`, ...) already publish releases in the same single-program shape as `modflow6` - one archive per platform, no `code.json` needed since there's only one program in it. Anything shaped like that just works by passing its repo name.

`owner` defaults to `MODFLOW-ORG`; override it to test against a fork.

## Finding installed programs

```python
from modflow_devtools.programs import get_executable, list_installed

mf6_path = get_executable("mf6")
mf6_path = get_executable("mf6", version="6.8.0")

installed = list_installed()
for program, installations in installed.items():
    for inst in installations:
        print(f"{program} {inst.version} in {inst.bindir}")
```

Or by CLI:

```bash
mf programs list
mf programs list mf6 --verbose
```

## Recording installations from other sources

The ledger isn't tied to `install_program`. Anything that installs a MODFLOW program - a conda-forge package, a manual build, another tool - can register itself so `get_executable`/`list_installed` can find it:

```python
from modflow_devtools.programs import register_installation

register_installation(
    "mf6",
    "6.8.0",
    bindir="/opt/conda/envs/modflow/bin",
    executables=["mf6"],
    source="conda-forge",
)
```

## Version management

Multiple versions can be installed side by side, to different `bindir`s (or the same one, if you don't mind overwriting):

```python
install_program("mf6", repo="modflow6", version="6.8.0", bindir="/opt/mf6-6.8.0")
install_program("mf6", repo="modflow6", version="6.7.0", bindir="/opt/mf6-6.7.0")
```

The downloaded archive is cached (`~/.cache/modflow-devtools/programs/archives/`), so re-installing an already-downloaded version doesn't re-fetch it. Pass `force=True` to force re-download.

## Uninstalling

```python
from modflow_devtools.programs import uninstall_program

uninstall_program("mf6", version="6.7.0", bindir="/opt/mf6-6.7.0")  # deletes the file(s)
uninstall_program(
    "mf6", version="6.7.0", bindir="/opt/mf6-6.7.0", delete_files=False
)  # ledger only
uninstall_program("mf6", all_versions=True)
```

Or via CLI:

```bash
mf programs uninstall mf6@6.7.0 --bindir /opt/mf6-6.7.0
mf programs uninstall mf6 --all
```

## Platform support

Platform is auto-detected as a MODFLOW ostag - `linux`, `mac`, `macarm`, or `win64` - via `modflow_devtools.ostags.get_ostag`. Override with `platform=...` if needed. Programs must publish pre-built binaries for the target platform; building from source is not supported.

## Cache and ledger layout

```
~/.cache/modflow-devtools/programs/
├── archives/{repo}/{tag}/{platform}/{asset name}   # downloaded release archives
└── metadata/{program}.json                          # per-program installation ledger
```

The ledger is a flat list of installations per program name - version, platform, bindir, install time, source, and the executable filename(s) - independent of how the archive was cached or discovered.

## Relationship to get-modflow and conda-forge

This module is meant to eventually replace flopy's `get_modflow.py`: it ports the same download/extract/bindir-selection logic, generalized across all three of `get_modflow.py`'s supported repos (`executables`, `modflow6`, `modflow6-nightly-build`) rather than one at a time, and adds per-program version tracking instead of a single flat "what did I last run" log.

It deliberately does **not** try to be a package manager. An earlier iteration of this API explored a Models/DFNs-style registry (each program repository publishing its own `programs.toml` manifest, synced and cached locally). That was built and later dropped: it duplicates work a real package manager already does well, and in practice no MODFLOW-ORG program repository adopted the registry contract, including `modflow6` itself. If MODFLOW programs become available via conda-forge, that's the better place to get them installed and managed; this module's installation ledger is designed to accept those installs too (via `register_installation`), not to compete with them.
