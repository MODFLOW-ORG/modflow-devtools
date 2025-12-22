# Models API Design

This document describes the (re)design of the Models API ([GitHub issue #134](https://github.com/MODFLOW-ORG/modflow-devtools/issues/134)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

This is a living document which will be updated as development proceeds. As the reimplementation nears completion, the scope here will shrink from charting a detailed transition path to simply describing the new design.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Background](#background)
- [Objective](#objective)
- [Motivation](#motivation)
- [Overview](#overview)
- [Architecture](#architecture)
  - [Bootstrap file](#bootstrap-file)
    - [Bootstrap file contents](#bootstrap-file-contents)
    - [Sample bootstrap file](#sample-bootstrap-file)
  - [Registry files](#registry-files)
  - [Registry discovery](#registry-discovery)
    - [Model files under version control](#model-files-under-version-control)
    - [Model files as release assets](#model-files-as-release-assets)
    - [Combining publication schemes](#combining-publication-schemes)
    - [Registry discovery procedure](#registry-discovery-procedure)
  - [Registry/model caching](#registrymodel-caching)
  - [Registry synchronization](#registry-synchronization)
    - [Manual sync](#manual-sync)
    - [Automatic sync](#automatic-sync)
  - [Source model integration](#source-model-integration)
  - [Model Addressing](#model-addressing)
  - [Registry classes](#registry-classes)
  - [Module-Level API](#module-level-api)
- [Migration path](#migration-path)
  - [Implementation plan](#implementation-plan)
    - [Phase 1: Foundation (v1.x)](#phase-1-foundation-v1x)
    - [Phase 2: PoochRegistry Adaptation (v1.x)](#phase-2-poochregistry-adaptation-v1x)
    - [Phase 3: Upstream CI (concurrent with Phase 1-2)](#phase-3-upstream-ci-concurrent-with-phase-1-2)
    - [Phase 4: Testing & Documentation (v1.x)](#phase-4-testing--documentation-v1x)
    - [Phase 5: v2.x Release](#phase-5-v2x-release)
- [Open Questions / Future Enhancements](#open-questions--future-enhancements)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->



## Background

Currently each release of `modflow-devtools` is fixed to a specific state of each model repository. It is incumbent on this package's developers to monitor the status of model repositories and, when models are updated, regenerate the registry and release a new version of this package.

This tight coupling is inconvenient for consumers. It is not currently clear which version of `modflow-devtools` provides access to which versions of each model repository, and users must wait until developers manually re-release `modflow-devtools` for access to updated models. Also, 1.7MB+ in TOML registry files are currently shipped with package, bloating the install time network payload.

The coupling is also burdensome to developers, preventing model repositories and `modflow-devtools` from moving independently.

## Objective

Transition from a static model registry baked into `modflow-devtools` releases to a dynamic, explicitly versioned registry system where model repositories publish catalogs which `modflow-devtools` discovers and synchronizes to on-demand.

## Motivation

-  Uncouple `modflow-devtools` releases from model repositories, allowing access to updated models without package updates
- Make model repository versioning explicit, with generic support for `git` refs (branches, commit hashes, tags, and tagged releases)
- Shrink the package size: ship no large TOML files, only minimal bootstrap information rather than full registries
- Reduce the `modflow-devtools` developer maintenance burden by eliminating the responsibility for (re)generating registries

## Overview

Make model repositories reponsible for publishing their own registries.

Make `modflow-devtools` responsible only for

- defining the registry publication contract;
- providing registry-creation machinery;
- storing bootstrap information locating model repositories;
- discovering remote registries at install time or on demand;
- caching registry data and models input files; and
- exposing a synchronized view of available registries.

Model repository developers can use the `modflow-devtools` registry-creation facilities to generate registry metadata, either manually or in CI.

## Architecture

This will involve a few new components (e.g., bootstrap file, `MergedRegistry` class) as well as modifications to some existing components (e.g., existing registry files, `PoochRegistry`). It should be possible for the `ModelRegistry` contract to remain unchanged.

### Bootstrap file

The **bootstrap** file will tell `modflow-devtools` where to look for remote model repositories. This file will be checked into the repository at `modflow_devtools/models/bootstrap.toml` and distributed with the package.

#### Bootstrap file contents

At the top level, the bootstrap file consists of a table of `sources`, each describing a model repository.

The name of each source is by default inferred from the name of the subsection, i.e. `sources.name`. The name will become part of a prefix by which models can be hierarchically addressed (described below). To override the name (and thus the prefix) a `name` attribute may be provided.

The source repository is identified by a `repo` attribute consisting of the repository owner and name separated by a forward slash.

A `registry_path` attribute identifies the directory in the repository which contains the registry metadata file. This attribute is optional and defaults to `.registry/`. This attribute is only relevant if the repository versions the registry file and model input files, as described below.

#### Sample bootstrap file

```toml
[sources.modflow6-examples]
repo = "MODFLOW-ORG/modflow6-examples"
name = "mf6/example"
refs = ["current"]

[sources.modflow6-testmodels]
repo = "MODFLOW-ORG/modflow6-testmodels"
name = "mf6/test"
refs = [
    "develop",
    "master",
]

[sources.modflow6-largetestmodels]
repo = "MODFLOW-ORG/modflow6-largetestmodels"
name = "mf6/large"
refs = [
    "develop",
    "master",
]
```

Note: The bootstrap refs list indicates default refs to sync at install time. Users can request synchronization to any valid git ref (branch, tag, or commit hash) via the CLI or API.

### Registry files

There are currently three separate registry files:

- `registry.toml`: enumerates invidual files known to the registry. Each file is a section consisting of at minimum a `url` attribute, as well as an optional `hash` attribute. These attributes deliberately provide the information Pooch expects for each file and no more, so that a `pooch.Pooch` instance's `.registry` property may be set directly from the contents of `registry.toml`.
- `models.toml`: groups files appearing in `registry.toml` according to the model they belong to. From the perspective of the Models API, a model consists of an unordered set of input files.
- `examples.toml`: groups models appearing in `models.toml` according to the example scenario they belong to. From the perspective of the Models API, an example scenario consists of an *ordered* set of models &mdash; order is relevant because a flow model, for instance, must run before a transport model. This allows API consumers to run models in the order received.

It seems simplest to consolidate these into a single `registry.toml` file defining sections `files`, `models`, and `examples` corresponding to the contents of each of the current registry files. It remains convenient, I think, for the contents of the `files` section to continue conforming to the expectations of `Pooch.registry`.

Registry files can begin to define a few new items of metadata:

```toml
generated_at = "2025-12-04T14:30:00Z"
devtools_version = "1.9.0"
schema_version = "1.1"
```

Versioning the registry file schema will smooth the migration from the existing state of the API to the proposed design, as well as any further migrations pending future development.

### Registry discovery

Model repositories can publish models to `modflow-devtools` in two ways.

#### Model files under version control

Model input files and registry metadata files may be versioned in the model repository. Under this scheme, registry files are expected by default in a `.registry/` directory &mdash; this location can be overridden by the `registry_path` attribute in the bootstrap file (see above). Registry files are discovered for each of the `refs` specified in the registry bootstrap metadata file, according to the GitHub raw content URL:

```
https://raw.githubusercontent.com/{org}/{repo}/{ref}/.registry/registry.toml
```

On model access, model input files are fetched and cached (by Pooch) individually, also via GitHub raw content URLs.

This mode supports repositories for which model input files live directly in the repository and does not require the repository to publish releases, e.g.

- `MODFLOW-ORG/modflow6-testmodels`
- `MODFLOW-ORG/modflow6-largetestmodels`

#### Model files as release assets

Model input files and the registry metadata file may also be published as release assets. Registry metadata files are again discovered for each of the `refs` specified in the registry bootstrap metadata file. In this scheme, the registry file need not be checked into the repository, and may instead be generated on demand by release automation. Registry files are sought instead under a release asset download URLs:

```
https://github.com/{repo}/releases/download/{ref}/registry.toml
```

Note that only release tags, not other ref types (e.g. commit hashes or branch names), are supported.

This scheme is meant to support repositories which distribute model input files as GitHub releases, and may not version them &mdash; for instance, in the case of `MODFLOW-ORG/modflow6-examples`, only FloPy scripts are under version control, and model input files are built by the release automation.

For models distributed this way, file entries' `url` attribute in the registry file should point to a release asset download URL for a zipfile containing model input files, e.g. for the `MODFLOW-ORG/modflow6-examples` repo:

```toml
["ex-gwe-ates/ex-gwe-ates.tdis"]
url = "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip"
```

On model access, the release asset containing models is fetched from its asset download URL, unzipped, and all models are cached at once (all by Pooch). This means that model input files published in this way will be slower upon first model access (while the zip file is fetched and unzipped) than with the version-controlled model input file approach.

#### Combining publication schemes

A repository may make registry files and model input files available in both ways, as version-controlled files *and* as release assets. In this case, discovery order becomes relevant: **model/registry releases take precedence over models/registries under version-control**. The discovery procedure is described in detail below.

#### Registry discovery procedure

At sync time, `modflow-devtools` attempts to discover remote registries according to the following algorithm for each of the `refs` specified in the bootstrap metadata file:

1. Look for a matching release tag. If one exists, the registry discovery mechanism continues in **release asset** mode, looking for a release asset named `registry.toml`. If no matching release tag can be found, go to step 2. If the matching release contains no asset named `registry.toml`, raise an error indicating that the given release lacks the required registry metadata file asset:

```python
RegistryDiscoveryError(
    f"Registry file 'registry.toml' not found "
    f"as release asset for '{source}@{ref}'"
)
```

2. Look for a commit hash, tag, or branch matching the ref (in that order, matching `git`'s lookup order). If a match exists, registry discovery continues in **version-controlled** mode, looking for a registry metadata file in the location specified in the bootstrap file (or in the default location `.registry/`). If no matching ref is found, raise an error indicating registry discovery has failed:

```python
RegistryDiscoveryError(
    f"Registry discovery failed, "
    f"ref '{source}@{ref}' does not exist"
)
```

If no registry metadata file can be found, raise an error indicating that the given branch or commit lacks a registry metadata file in the expected location:

```python
RegistryDiscoveryError(
    f"Registry file 'registry.toml' not found "
    f"in {registry_path} for '{source}@{ref}'"
)
```

If registry metadata file discovery is successful, it is fetched and parsed to determine the location(s) of model input files.

**Note**: for repositories combining the version-control and release publication schemes, `modflow-devtools` will discover tagged releases *before* tags as mere refs, therefore the Models API will reflect registry files and model input files published as release assets, not files under version control.

### Registry/model caching

A caching approach should support registries for multiple refs simultaneously, enabling fast switching between refs. TBD whether to delegate registry file fetching/caching to Pooch. Model input file fetching/caching can be managed by Pooch as it is already.

Something like the following directory structure should work.

```
~/.cache/modflow-devtools/
├── registries/
│   ├── modflow6-examples/
│   │   ├── 1.2.3/          # release tag (if repo publishes releases)
│   │   │   ├── registry.toml
│   │   │   ├── models.toml
│   │   │   └── examples.toml
│   │   ├── master/         # branch
│   │   │   ├── registry.toml
│   │   │   ├── models.toml
│   │   │   └── examples.toml
│   │   └── develop/        # branch
│   │       ├── registry.toml
│   │       ├── models.toml
│   │       └── examples.toml
│   ├── modflow6-testmodels/
│   │   ├── master/
│   │   │   └── ...
│   │   └── develop/
│   │       └── ...
│   └── modflow6-largetestmodels/
│       └── ...
└── models/  # Actual model files, managed by Pooch
    └── ...
```

### Registry synchronization

Delegating registry responsibilities to model repositories entails deferring the loading of registries &mdash; `modflow-devtools` will no longer ship with information about exactly which models are available, only where to find model repositories and how they make model input files available.

The user should be able to manually trigger synchronization. For a smooth experience it should probably happen automatically at opportune times, though.

#### Manual sync

Synchronization can be exposed as an [executable module](https://peps.python.org/pep-0338/) and as a [command](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts).

The simplest approach would be a single such script/command, e.g. `python -m modflow_devtools.models.sync` aliased to `sync-models`. It seems ideal to support introspection as well. A full models CLI might include:

- `sync`: synchronize registries for all configured source model repositories, or a specific repo
- `info`: show configured registries and their sync status, or a particular registry's sync status
- `list`: list available models for all registries, or for a particular registry

```bash
# Show configured registries and status
python -m modflow_devtools.models info

# Sync all sources to configured refs
python -m modflow_devtools.models sync

# Force re-download even if cached
python -m modflow_devtools.models sync --force

# For a repo publishing models via releases
python -m modflow_devtools.models sync --repo MODFLOW-ORG/modflow6-examples --ref current

# For a repo with models under version control
python -m modflow_devtools.models sync --repo MODFLOW-ORG/modflow6-testmodels --ref develop 
python -m modflow_devtools.models sync --repo MODFLOW-ORG/modflow6-testmodels --ref f3df630  # commit hash works too
```

Or via CLI commands:

```bash
models info
models sync
```

Perhaps leading with a `models` command namespace is too generic, and we need e.g. a leading `mf` namespace on all commands exposed by `modflow-devtools`:

```bash
mf models info
mf models sync
```

#### Automatic sync

At install time, `modflow-devtools` can load the bootstrap file and attempt to sync to all configured repositories/registries. The install should not fail if registry sync fails (due either to network errors or misconfiguration), however &mdash; an informative warning can be shown, and sync retried on subsequent imports and/or manually (see below).

Synchronization involves:

- Loading the bootstrap file
- Discovering/validating remote registries
- Caching registries locally

### Source model integration

Required steps in source model repositories include:

- Install `modflow-devtools` (provides registry generation machinery)
- Generate registries
   ```bash
   python -m modflow_devtools.make_registry \
     --path . \
     --output .registry \
     --url <appropriate-base-url>
   ```
- Commit registry files to `.registry/` directory (for version-controlled model repositories) or post them as release assets (for repositories publishing releases)


### Model Addressing

**Format**: `{source}@{ref}/{subpath}`

Components include:

- `source`: Repository identifier (e.g., `modflow6-examples`, `modflow6-testmodels`)
- `ref`: Git ref (branch or tag, e.g., `v1.2.3`, `master`, `develop`)
- `subpath`: Relative path within repo to model directory

The model directory name, i.e. the rightmost element in the `subpath`, is presumed to be the model name.

For example:

- `modflow6-examples@v1.2.3/ex-gwf-twri`
- `modflow6-testmodels@develop/mf6/test001a_Tharmonic`
- `modflow6-largetestmodels@master/prudic2004t2`

Benefits of this approach:

- Guarantees no name/cache collisions (unique per source + ref + path)
- Model provenance is explicit to users
- Allows multiple refs from same source

### Registry classes

`PoochRegistry` is currently associated with a single state of a single repository. This can continue. Introduce a few properties to (e.g. `source` and `ref`) to make the model source and version explicit.

`PoochRegistry` should be immutable &mdash; to synchronize to a new model source state, create a new one.

Introduce a `MergedRegistry` compositor to merge multiple `PoochRegistry` instances under the same `ModelRegistry` API. The initializer can simply accept a list of pre-constructed `PoochRegistry` instances, and expose a list or dictionary of the registries of which it consists. Properties inherited from `ModelRegistry` (`files`, `models`, `examples`) can return merged views.

Handle synchronization, `MergedRegistry` construction, and similar concerns at the module (i.e. higher) level. Registries don't need to concern themselves with this sort of thing.

Some tentative usage examples:

```python
# Create individual registries
examples_v1 = PoochRegistry("modflow6-examples", "v1.2.3")
testmodels = PoochRegistry("modflow6-testmodels", "develop")

# Merge them
merged = MergedRegistry([examples_v1, testmodels])

# Later: update to new ref
examples_v2 = PoochRegistry("modflow6-examples", "v2.0.0")
merged = MergedRegistry([examples_v2, testmodels])

# Mix multiple refs of same source
examples_stable = PoochRegistry("modflow6-examples", "v1.2.3")
examples_dev = PoochRegistry("modflow6-examples", "develop")
merged = MergedRegistry([examples_stable, examples_dev, testmodels])
```

`LocalRegistry` is unaffected by all this, as it suits a different use case largely aimed at developers. Consider renaming it e.g. to `DeveloperRegistry`.

### Module-Level API

Provide convenient APIs for common use cases, like synchronizing to a particular source or to all known sources, introspecting sync status, etc.

Expose as `DEFAULT_REGISTRY` a `MergedRegistry` with all sources configured in the bootstrap file.

This will break any code checking `isinstance(DEFAULT_REGISTRY, PoochRegistry)`, but it's unlikely anyone is doing that.

## Migration path

Ideally, we can avoid breaking existing code, and provide a gentle migration path for users with clear deprecation warnings and/or error messages where necessary.

For the remainder of the 1.x release series, keep shipping registry metadata with `modflow-devtools` for backwards-compatibility, now with the benefit of explicit model versioning. Allow syncing on demand for access to model updates. Stop shipping registry metadata and begin syncing remote model registry metadata at install time with the release of 2.x, at which point metadata shipped with `modflow-devtools` should be a few KB at most.

For 1.x, show a deprecation warning on import:

```
DeprecationWarning: Bundled registry is deprecated and will be removed in v2.0.
Use `python -m modflow_devtools.models sync` to download the latest registry.
```

### Implementation plan

#### Phase 1: Foundation (v1.x)

1. Add bootstrap metadata file
2. Implement registry schema with Pydantic validation
3. Create cache directory structure utilities
4. Add `sync_registry()` function with download logic
5. Implement branch priority resolution
6. Add CLI subcommands (sync, list, status)

#### Phase 2: PoochRegistry Adaptation (v1.x)

1. Modify `PoochRegistry` to check cache first
2. Add fallback to bundled registry
3. Implement best-effort sync on import
4. Add deprecation warnings for bundled registry

#### Phase 3: Upstream CI (concurrent with Phase 1-2)

1. Add `.github/workflows/registry.yml` to each model repo
2. Test registry generation in CI
3. Commit registry files to `.registry/` directories
4. For repos with releases, add registry as release asset

#### Phase 4: Testing & Documentation (v1.x)

1. Add comprehensive tests for sync mechanism
2. Test network failure scenarios
3. Document new workflow in `models.md`
4. Add migration guide for v2.x

#### Phase 5: v2.x Release

1. Remove bundled registry files (keep bootstrap.toml)
2. Make sync required for PoochRegistry
3. Update documentation
4. Release notes with clear migration instructions

## Open Questions / Future Enhancements

1. **Registry compression**: Zip registry files for faster downloads?
2. **Partial registry updates**: Diff registries and download only changes?
3. **Registry CDN**: Consider hosting registries somewhere for faster access?
4. **Offline mode**: Provide an explicit "offline mode" that never tries to sync?
5. **Registry analytics**: Track which models/examples are most frequently accessed?
