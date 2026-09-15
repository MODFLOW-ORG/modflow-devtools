# Programs API Design

> **Experimental API**
>
> This API is experimental and may change or be removed in future versions without following normal deprecation procedures.

This document describes the design of the Programs API ([GitHub issue #263](https://github.com/MODFLOW-ORG/modflow-devtools/issues/263)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
<!-- END doctoc generated TOC please keep comment here to allow auto update -->

- [Background](#background)
- [First iteration: a registry, mirroring Models/DFNs](#first-iteration-a-registry-mirroring-modelsdfns)
- [Current design](#current-design)
  - [Program sources](#program-sources)
  - [Asset selection](#asset-selection)
  - [Extraction](#extraction)
  - [Installation](#installation)
  - [Installation ledger](#installation-ledger)
  - [Python API](#python-api)
  - [CLI](#cli)
- [Relationship to Models/DFNs APIs](#relationship-to-modelsdfns-apis)
- [Relationship to get-modflow](#relationship-to-get-modflow)
- [Explicitly out of scope](#explicitly-out-of-scope)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Background

Program information (download URLs, versions, build configuration) has historically lived in `pymake`, alongside its actual job of building programs - the database part being accidental, not something pymake set out to own. `modflow-devtools` originally carried a minimal, read-only copy of that same database (`programs.csv`), which shared pymake's problems: static, manually maintained, no install capability.

## First iteration: a registry, mirroring Models/DFNs

The first version of this API (#243, #270, #276-#311) built a full Models/DFNs-style registry: a bootstrap file naming program source repositories, each expected to publish its own `programs.toml` manifest as a release asset, synced and cached locally, with a `ProgramManager` resolving installs against the cached registry.

This was dropped after evaluating it against reality:

- **No adoption.** Of ~13 sources in the bundled bootstrap config, only one (`gridgen`) ever published a conforming `programs.toml`. The flagship repo, `modflow6`, never did - its releases only ever shipped platform zips.
- **The distribution it was meant to unify hadn't moved.** `MODFLOW-ORG/executables` (the actual current distribution mechanism) was still shipping the old bundled `linux.zip`/`macarm.zip`/`win64.zip` format, with no sign of moving to independent per-program releases.
- **It duplicates a solved problem.** Installing versioned, hash-verified, cross-platform binaries is what a real package manager (conda-forge) already does well. Asking every program repository to *also* implement a bespoke registry contract, just for `modflow-devtools`, is redundant infrastructure for a problem domain that isn't ours to own.
- **The one part worth keeping wasn't the registry.** Tracking what's installed, where, and from what source is useful regardless of install mechanism - conda-forge, a manual build, or this module's own installer. That doesn't require owning discovery/sync at all.

The registry/sync/bootstrap layer (`ProgramSourceConfig`, `ProgramSourceRepo`, `ProgramCache.save/load` for registries, `ProgramRegistry`/`ProgramMetadata`/`ProgramDistribution`, `make_registry.py`, the bundled `programs.toml`/`programs.csv`) was removed. See git history prior to this rewrite for the full prior design if it's ever worth resurrecting.

## Current design

Install directly from the three real MODFLOW-ORG release distributions (matching flopy's [`get_modflow.py`](https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py)), and keep one genuinely new piece: a local per-program installation ledger.

### Program sources

No registry, no bootstrap file - `AVAILABLE_REPOS` is a fixed tuple of the three real distributions:

| `repo` | Shape | Versioning |
|---|---|---|
| `executables` (default) | One archive per ostag, bundling many programs, described by an embedded `code.json` manifest (`{key: {version, shared_object, double_switch}}`) | Per-program, from `code.json` |
| `modflow6` | One archive per ostag containing `mf6`/`zbud6`/`mf5to6`/`libmf6`, no `code.json` | Shared release tag |
| `modflow6-nightly-build` | Same shape as `modflow6`, nightly tags | Shared nightly tag |

`get_release`/`get_releases` hit the GitHub API directly (`GET /repos/{owner}/{repo}/releases[/tags/{tag}]`), with retry/backoff on transient failures, mirroring `get_modflow.py`'s own retry logic. `owner` defaults to `MODFLOW-ORG` but is overridable (e.g. to test a fork).

### Asset selection

`_select_asset` matches a release asset to the detected ostag (`linux`/`mac`/`macarm`/`win64`, from `modflow_devtools.ostags.get_ostag`) by regex word-boundary match, not plain substring - `get_modflow.py`'s plain `ostag in asset_name` check is fragile against names like `win64ext.zip` shadowing `win64.zip`; this fixes that while keeping the same asset-naming assumptions.

### Extraction

`extract_release_archive` generalizes `get_modflow.py`'s extraction logic across both archive shapes it needs to handle:

- Gathers files nested under a top-level `bin/` directory if present, falling back to the archive root.
- If a `code.json` manifest is present (the `executables` shape), each program's version comes from it, and `shared_object`/exe-suffix handling follows `code.json`.
- Otherwise (the `modflow6`/`modflow6-nightly-build` shape), every extracted file is versioned as the release tag, keyed by filename stem.
- Detection is based on the presence of `code.json` in the archive, not on which `repo` was requested - so a future distribution that adopts either shape needs no code change here.
- `subset` (a set of program names or filenames) filters what gets extracted from either shape.

Not ported: `code.json`'s legacy `*dbl` double-precision variant handling (a few old MODFLOW-2005-era programs ship both single- and double-precision builds). Scoped out as a niche build variant, not central to installing modern ecosystem programs; a real gap if someone needs those specific programs' double-precision builds through this API.

### Installation

`install_program(program=None, *, repo, owner, version, bindir, platform, subset, force, verbose, tries, delay)`:

1. Resolve platform (`get_platform()`, i.e. `ostags.get_modflow_ostag()`) unless overridden.
2. Resolve the release (`get_release`) and matching asset (`_select_asset`).
3. Resolve `bindir` (explicit path, `:`-prefixed shortcut via `select_bindir`, or auto-selected via `get_bindir_options`) - all adapted from `get_modflow.py`.
4. Download the archive to `~/.cache/modflow-devtools/programs/archives/{repo}/{tag}/{platform}/`, reusing a cached copy unless `force`.
5. Extract directly into `bindir` (no separate binaries-cache tier - the archive cache alone is enough to make version switching fast, since extraction is a local, non-network operation; this is simpler than the first iteration's three-tier archive/binaries/bindir cache and matches `get_modflow.py`'s own model).
6. For each extracted program, record a `ProgramInstallation` in that program's own ledger via `InstallationMetadata`.

Returns one `ProgramInstallation` per installed program (not per file - `executables` bundle installs of several programs in one call each get their own ledger entry).

### Installation ledger

The one piece carried over from the first iteration, unchanged in spirit:

```python
@dataclass
class ProgramInstallation:
    version: str
    platform: str
    bindir: Path
    installed_at: datetime
    source: dict[str, str]  # free-form provenance, not a registry reference
    executables: list[str]


class InstallationMetadata:
    """Ledger for one program name, at ~/.cache/modflow-devtools/programs/metadata/{program}.json"""
    def load(self) -> bool: ...
    def save(self) -> None: ...
    def add_installation(self, installation: ProgramInstallation) -> None: ...
    def remove_installation(self, version: str, bindir: Path) -> None: ...
    def list_installations(self) -> list[ProgramInstallation]: ...
```

**Correctness note**: `add_installation`/`remove_installation` reload from disk before mutating and saving. This matters because both `install_program` and `register_installation` construct a fresh `InstallationMetadata(program)` per call rather than holding a loaded instance across calls - without the internal reload, a second install of a *different* program version (or by a different caller) would silently clobber the first entry instead of merging. (This was a real bug in the initial rewrite, caught by `test_get_executable_filters_by_version` in `autotest/test_programs.py`.)

`register_installation(program, version, bindir, executables, *, source=None, platform=None, installed_at=None)` is the source-agnostic entry point - anything that installs a program (a conda-forge package, a manual build, some other tool) can call it directly to make itself visible to `get_executable`/`list_installed`, without going through `install_program`'s GitHub-release-specific path at all.

### Python API

```python
from modflow_devtools.programs import (
    install_program,
    uninstall_program,
    register_installation,
    get_executable,
    list_installed,
)

install_program("mf6", repo="modflow6", version="6.8.0", bindir="/usr/local/bin")
register_installation("mf6", "6.8.0", "/opt/conda/envs/mf/bin", ["mf6"], source="conda-forge")
get_executable("mf6")  # -> Path | None
list_installed()       # -> dict[str, list[ProgramInstallation]]
uninstall_program("mf6", version="6.8.0", bindir="/usr/local/bin")
```

### CLI

```bash
mf programs install mf6 --repo modflow6 [--version V] [--bindir DIR] [--platform P] [--force]
mf programs install --repo executables --subset mfnwt,mf2005 --bindir DIR
mf programs uninstall mf6@6.8.0 --bindir DIR [--all] [--keep-files]
mf programs list [PROGRAM] [-v]
```

No `sync`/`info` commands - there's nothing to sync. `mf sync` (the top-level "sync everything" command) no longer touches the Programs API for the same reason.

## Relationship to Models/DFNs APIs

The Programs API no longer mirrors the Models/DFNs registry architecture, and that's deliberate now rather than incidental. Models and DFNs registries exist because there's nowhere else that metadata could live - example/test models and MF6 input schemas aren't packages with any existing distribution channel. Program binaries are a solved problem *elsewhere* (conda-forge); the registry/sync/bootstrap pattern that's right for Models/DFNs doesn't transfer just because the module lives in the same package.

What Programs still shares with Models/DFNs: an experimental-API warning, a `~/.cache/modflow-devtools/{api}/` cache root, and a `mf {api} ...` CLI namespace under the shared `mf` entry point.

## Relationship to get-modflow

This module is meant to eventually replace flopy's `get_modflow.py`, and now tracks it much more closely than the first iteration did:

| get_modflow.py | modflow_devtools.programs |
|---|---|
| `run_main(bindir, owner, repo, release_id, ostag, subset, ...)` | `install_program(program, *, repo, owner, version, bindir, platform, subset, ...)` |
| `get_release`/`get_releases` with retry | same, ported directly |
| `code.json`-aware extraction, nested `bin/` detection | `extract_release_archive`, same logic, generalized |
| `get_bindir_options`/interactive `:`-prefixed shortcuts | `get_bindir_options`/`get_bindir_shortcut_map`/`select_bindir`, ported directly |
| Flat metadata list, written only when running inside flopy | `InstallationMetadata`, per-program, always written, one ledger entry per program even within a combined install |

Programs are expected to publish pre-built binaries for all supported platforms; building from source is out of scope, as it was for `get_modflow.py`.

## Explicitly out of scope

1. **Building programs from source.** Programs must publish pre-built binaries.
2. **Cross-platform installs.** No installing Windows binaries on Linux, etc.
3. **A registry contract for program repositories.** See "First iteration" above.
4. **Double-precision (`*dbl`) build variants.** See "Extraction" above.
5. **Semantic version ranges / aliases** (e.g. `mf6@^6.6`, `mf6@latest` as a named alias distinct from the literal release tag `latest`). Could be added later if there's real demand.
