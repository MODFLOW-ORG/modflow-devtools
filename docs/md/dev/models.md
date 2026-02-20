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
    - [User config overlay](#user-config-overlay)
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
- [Status and Next Steps](#status-and-next-steps)
- [Cross-API Consistency](#cross-api-consistency)
  - [Shared Patterns](#shared-patterns)
  - [Key Differences](#key-differences)
- [Demo & Usage Examples](#demo--usage-examples)
  - [Python API](#python-api)
    - [Basic Workflow](#basic-workflow)
    - [Object-Oriented API](#object-oriented-api)
    - [Cache Management](#cache-management)
  - [CLI Usage](#cli-usage)
    - [Show Registry Status](#show-registry-status)
    - [Sync Registries](#sync-registries)
    - [List Available Models](#list-available-models)
  - [Registry Creation Tool](#registry-creation-tool)
  - [User Config Overlay for Fork Testing](#user-config-overlay-for-fork-testing)
  - [Upstream CI Workflow Examples](#upstream-ci-workflow-examples)
- [Open Questions / Future Enhancements](#open-questions--future-enhancements)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->



## Background

Previously, each release of `modflow-devtools` was fixed to a specific state of each model repository. It was incumbent on this package's developers to monitor the status of model repositories and, when models were updated, regenerate the registry and release a new version of this package.

This tight coupling was inconvenient for consumers. It was not clear which version of `modflow-devtools` provided access to which versions of each model repository, and users had to wait until developers manually re-released `modflow-devtools` for access to updated models. Also, 1.7MB+ in TOML registry files were shipped with package, bloating the install time network payload.

The coupling was also burdensome to developers, preventing model repositories and `modflow-devtools` from moving independently.

## Objective

The Models API has transitioned from a static model registry baked into `modflow-devtools` releases to a dynamic, explicitly versioned registry system where model repositories publish catalogs which `modflow-devtools` discovers and synchronizes on-demand.

## Motivation

-  Uncouple `modflow-devtools` releases from model repositories, allowing access to updated models without package updates
- Make model repository versioning explicit, with generic support for `git` refs (branches, commit hashes, tags, and tagged releases)
- Shrink the package size: ship no large TOML files, only minimal bootstrap information rather than full registries
- Reduce the `modflow-devtools` developer maintenance burden by eliminating the responsibility for (re)generating registries

## Overview

Make model repositories responsible for publishing their own registries.

Make `modflow-devtools` responsible only for

- defining the registry publication contract;
- providing registry-creation machinery;
- storing bootstrap information locating model repositories;
- discovering remote registries at install time or on demand;
- caching registry data and models input files; and
- exposing a synchronized view of available registries.

Model repository developers can use the `modflow-devtools` registry-creation facilities to generate registry metadata, either manually or in CI.

## Architecture

The Models API uses a streamlined object-oriented design consolidated in a single `modflow_devtools/models/__init__.py` file. This makes the code easier to follow and maintain while providing clear separation of concerns through well-defined classes.

Key classes:
- **`ModelCache`**: Manages local caching of registries and model files
- **`ModelSourceRepo`**: Represents a single model source repository with discovery and sync methods
- **`ModelSourceConfig`**: Configuration container managing multiple sources from bootstrap file
- **`ModelRegistry`**: Pydantic model representing a registry's structure (files/models/examples)
- **`PoochRegistry`**: Uses Pooch to fetch and cache models from remote sources
- **`DiscoveredModelRegistry`**: Result of registry discovery with metadata

The design emphasizes encapsulation - each class has clear responsibilities and the overall API remains simple despite the underlying complexity.

### Bootstrap file

The **bootstrap** file will tell `modflow-devtools` where to look for remote model repositories. This file will be checked into the repository at `modflow_devtools/models/models.toml` and distributed with the package.

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

#### User config overlay

Users can customize or extend the bundled bootstrap configuration by creating a user config file at:
- Linux/macOS: `~/.config/modflow-devtools/models.toml` (respects `$XDG_CONFIG_HOME`)
- Windows: `%APPDATA%/modflow-devtools/models.toml`

The user config follows the same format as the bundled bootstrap file. Sources defined in the user config will override or extend those in the bundled config:
- Sources with the same key will be completely replaced by the user version
- New sources will be added to the available sources

This allows users to:
- Add private or custom model repositories
- Point to forks of existing repositories (useful for testing)
- Override default refs for existing sources
- Temporarily disable sources (by overriding with empty refs list)

The user config is automatically loaded and merged when using the default bootstrap location. For testing, a custom user config path can be specified via the `user_config_path` parameter to `load_bootstrap()`.

**Implementation note**: The user config path logic (`get_user_config_path("models")`) is shared across all three APIs (Models, Programs, DFNs) via `modflow_devtools.config`, but each API implements its own `merge_bootstrap()` function using API-specific bootstrap schemas.

### Registry files

Model repositories publish a single consolidated registry file named **`models.toml`** (not `registry.toml` - the specific naming distinguishes it from the Programs and DFNs registries).

The registry file contains:

- **Metadata** (top-level): Version and generation info
- **`files`**: Map of filenames to hashes (URLs constructed dynamically, not stored)
- **`models`**: Map of model names to file lists
- **`examples`**: Map of example names to model lists

Example `models.toml`:

```toml
schema_version = "1.0"

[files]
"ex-gwf-twri01/mfsim.nam" = {hash = "sha256:abc123..."}
"ex-gwf-twri01/gwf.nam" = {hash = "sha256:def456..."}
# ... more files

[models]
"ex-gwf-twri01" = [
    "ex-gwf-twri01/mfsim.nam",
    "ex-gwf-twri01/gwf.nam",
    # ... more files
]

[examples]
"ex-gwf-twri" = ["ex-gwf-twri01"]
```

**Key design decisions**:
- **Consolidated format only**: Always generates a single `models.toml` file with all sections. The deprecated `--separate` option (which generated separate `registry.toml`, `models.toml`, `examples.toml` files) has been removed.
- **No `url` field**: URLs are constructed dynamically from bootstrap metadata (repo, ref, registry_path) + filename. This allows testing against forks by simply changing the bootstrap configuration.
- **Top-level metadata**: Use `schema_version` (not nested under `_meta`) for consistency with Programs and DFNs APIs.
- **Named `models.toml`**: Distinguishes from `programs.toml` and `dfns.toml` in other APIs.

### Registry discovery

Model repositories can publish models to `modflow-devtools` in two ways.

#### Model files under version control

Model input files and registry metadata files may be versioned in the model repository. Under this scheme, registry files are expected by default in a `.registry/` directory &mdash; this location can be overridden by the `registry_path` attribute in the bootstrap file (see above). Registry files are discovered for each of the `refs` specified in the registry bootstrap metadata file, according to the GitHub raw content URL:

```
https://raw.githubusercontent.com/{org}/{repo}/{ref}/.registry/models.toml
```

On model access, model input files are fetched and cached (by Pooch) individually, also via GitHub raw content URLs. File URLs are constructed dynamically from the bootstrap metadata (repo, ref) and filename, not stored in the registry.

This mode supports repositories for which model input files live directly in the repository and does not require the repository to publish releases, e.g.

- `MODFLOW-ORG/modflow6-testmodels`
- `MODFLOW-ORG/modflow6-largetestmodels`

#### Model files as release assets

Model input files and the registry metadata file may also be published as release assets. Registry metadata files are again discovered for each of the `refs` specified in the registry bootstrap metadata file. In this scheme, the registry file need not be checked into the repository, and may instead be generated on demand by release automation. Registry files are sought instead under a release asset download URL:

```
https://github.com/{repo}/releases/download/{ref}/models.toml
```

Note that only release tags, not other ref types (e.g. commit hashes or branch names), are supported.

This scheme is meant to support repositories which distribute model input files as GitHub releases, and may not version them &mdash; for instance, in the case of `MODFLOW-ORG/modflow6-examples`, only FloPy scripts are under version control, and model input files are built by the release automation.

For models distributed this way, the registry file maps filenames to hashes (no `url` stored). The URL for the zipfile containing model input files is constructed dynamically from bootstrap metadata, e.g.:

```toml
# models.toml (for modflow6-examples)
[files]
"ex-gwe-ates/ex-gwe-ates.tdis" = {hash = "sha256:..."}
# URL constructed as: https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip
```

On model access, the release asset containing models is fetched from its asset download URL (constructed at runtime), unzipped, and all models are cached at once (all by Pooch). This means that model input files published this way will be slower upon first model access (while the zip file is fetched and unzipped) than with the version-controlled model input file approach.

#### Combining publication schemes

A repository may make registry files and model input files available in both ways, as version-controlled files *and* as release assets. In this case, discovery order becomes relevant: **model/registry releases take precedence over models/registries under version-control**. The discovery procedure is described in detail below.

#### Registry discovery procedure

At sync time, `modflow-devtools` attempts to discover remote registries according to the following algorithm for each of the `refs` specified in the bootstrap metadata file:

1. Look for a matching release tag. If one exists, the registry discovery mechanism continues in **release asset** mode, looking for a release asset named `models.toml`. If no matching release tag can be found, go to step 2. If the matching release contains no asset named `models.toml`, raise an error indicating that the given release lacks the required registry metadata file asset:

```python
RegistryDiscoveryError(
    f"Registry file 'models.toml' not found "
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
    f"Registry file 'models.toml' not found "
    f"in {registry_path} for '{source}@{ref}'"
)
```

If registry metadata file discovery is successful, it is fetched and parsed. Model input file URLs are constructed dynamically at fetch time from bootstrap metadata (repo, ref) and filenames in the registry.

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
mf models info

# Sync all sources to configured refs
mf models sync

# Force re-download even if cached
mf models sync --force

# For a repo publishing models via releases
mf models sync --repo MODFLOW-ORG/modflow6-examples --ref current

# For a repo with models under version control
mf models sync --repo MODFLOW-ORG/modflow6-testmodels --ref develop
mf models sync --repo MODFLOW-ORG/modflow6-testmodels --ref f3df630  # commit hash works too
```

CLI commands are available in two forms:

```bash
# Using the mf namespace (shorter)
mf models info
mf models sync

# Or using the module form
python -m modflow_devtools.models info
python -m modflow_devtools.models sync
```

The `mf` command provides a unified CLI namespace for all `modflow-devtools` commands.

#### Automatic sync

At install time, `modflow-devtools` can load the bootstrap file and attempt to sync to all configured repositories/registries. The install should not fail if registry sync fails (due either to network errors or misconfiguration), however &mdash; an informative warning can be shown, and sync retried on subsequent imports and/or manually (see below).

Synchronization involves:

- Loading the bootstrap file
- Discovering/validating remote registries
- Caching registries locally

### Source model integration

Required steps in source model repositories include:

- Install `modflow-devtools` (provides registry generation machinery)
- Generate registries using the mode-based interface:

   **For version-controlled models** (files in git):
   ```bash
   # Downloads from remote and indexes subdirectory (recommended)
   python -m modflow_devtools.models.make_registry \
     --repo MODFLOW-ORG/modflow6-testmodels \
     --ref master \
     --name mf6/test \
     --path mf6 \
     --output .registry
   ```

   **For release asset models** (zip published with releases):
   ```bash
   # Downloads from remote (provide --asset-file to index from release asset)
   python -m modflow_devtools.models.make_registry \
     --repo MODFLOW-ORG/modflow6-examples \
     --ref current \
     --asset-file mf6examples.zip \
     --name mf6/example \
     --output .registry
   ```

- Commit registry files to `.registry/` directory (for version-controlled model repositories) or post them as release assets (for repositories publishing releases)

**Note**: The tool operates in **remote-first mode** by default - it downloads the repository from GitHub at the specified ref, ensuring the registry exactly matches the remote state. The `--path` parameter can specify:
- A subdirectory within the repo (e.g., `mf6`) - downloads and navigates to it
- An existing local directory - uses local checkout (for testing only, may not match remote)
- Omitted - downloads and indexes entire repo root

This eliminates local/remote state mismatches and requires no git dependency or local checkout.


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

The registry implementation uses several Pydantic-based classes organized in a single module:

**`ModelRegistry`** (Pydantic base):
- Core data model with `files`, `models`, `examples` fields
- `ModelInputFile` has `hash` for verification (no `url` - constructed dynamically)
- Optional `metadata` field for registry info
- Can be instantiated directly or loaded from TOML
- Provides `copy_to()` method for copying models to a workspace

**`ModelCache`**:
- Manages local caching of registries and model files
- Methods: `save()`, `load()`, `has()`, `list()`, `clear()`
- Platform-appropriate cache locations (`~/.cache/modflow-devtools/` on Linux)
- Stores registries under `registries/{source}/{ref}/`
- Uses Pooch for actual model file caching

**`ModelSourceRepo`** (Pydantic):
- Represents a single source repository
- Fields: `repo`, `name`, `refs`, `registry_path`
- Methods:
  - `discover(ref)` - Discovers registry for a specific ref
  - `sync(ref, force, verbose)` - Syncs registry to cache
  - `is_synced(ref)` - Checks if ref is cached
  - `list_synced_refs()` - Lists all synced refs for this source
- Nested classes:
  - `SyncResult` - Contains synced/skipped/failed lists
  - `SyncStatus` - Shows configured vs cached refs

**`ModelSourceConfig`** (Pydantic):
- Container for multiple `ModelSourceRepo` sources
- Loaded from bootstrap file via `load()` classmethod
- Methods:
  - `status` property - Returns sync status for all sources
  - `sync(source, force, verbose)` - Syncs one or all sources
  - `merge()` classmethod - Merges two configurations

**`PoochRegistry`**:
- Uses Pooch to fetch and cache models from remote
- Constructs URLs dynamically from bootstrap metadata
- Lazy-loads registry from cache on first access
- Attempts auto-sync if registry not cached
- Provides access to the underlying `ModelRegistry`

**`DiscoveredModelRegistry`** (dataclass):
- Result of registry discovery
- Fields: `source`, `ref`, `mode`, `url`, `registry`
- `mode` is either "version_controlled" or "release"

**Design decisions**:
- **Single-module design** - All code in `__init__.py` for easy navigation
- **Pydantic-based** - Type-safe, validation built-in
- **OO encapsulation** - Each class has clear, focused responsibility
- **Dynamic URL construction** - URLs never stored, always computed from bootstrap
- **Method-based API** - Objects have methods for their operations (e.g., `source.sync()`)
- **No separate cache/discovery/sync modules** - Methods live on the classes that use them

### Module-Level API

Provide convenient APIs for common use cases, like synchronizing to a particular source or to all known sources, introspecting sync status, etc.

Expose as `DEFAULT_REGISTRY` a `MergedRegistry` with all sources configured in the bootstrap file.

This will break any code checking `isinstance(DEFAULT_REGISTRY, PoochRegistry)`, but it's unlikely anyone is doing that.

## Status and Next Steps

The dynamic registry system is fully implemented. The package ships only a minimal bootstrap file that tells the system where to find remote model repositories. On first import, `modflow-devtools` attempts to auto-sync the default registries.

The next step is upstream integration: model repositories should automate registry generation in CI workflows.

## Cross-API Consistency

The Models, Programs, and DFNs APIs share a consistent design for ease of use and implementation:

### Shared Patterns

1. **Consolidated single-module design** (Models API implementation):
   - All code in single `__init__.py` file for each API
   - Easier to follow and maintain than split modules
   - Clear separation via well-defined classes
   - Object-oriented API with methods on classes (e.g., `source.sync()`, `cache.load()`)
   - Recommended pattern for Programs and DFNs APIs to follow

2. **Bootstrap files**: Separate files for each API, using identical naming to registry files but distinguished by location
   - Bundled: `modflow_devtools/models/models.toml`, `modflow_devtools/programs/programs.toml`, `modflow_devtools/dfn/dfns.toml`
   - User config: `~/.config/modflow-devtools/models.toml`, `~/.config/modflow-devtools/programs.toml`, `~/.config/modflow-devtools/dfns.toml`

3. **Registry files**: Same naming as bootstrap files, distinguished by location (in source repos)
   - Models: `models.toml`
   - Programs: `programs.toml`
   - DFNs: `dfns.toml`

4. **Registry schema**: All use Pydantic-based base classes (not ABCs)
   - Allows direct instantiation for data-only use
   - Consistent top-level `schema_version` metadata field

5. **Dynamic URL construction**: URLs constructed at runtime from bootstrap metadata, not stored in registry files
   - Enables fork testing by changing bootstrap config
   - Smaller registry files
   - Single source of truth for repository locations

6. **Shared config utility**: `modflow_devtools.config.get_user_config_path(api_name)`
   - Provides platform-appropriate config path
   - Each API implements its own `merge_bootstrap()` with API-specific schemas

7. **Unified CLI operations**:
   - Sync all APIs: `python -m modflow_devtools sync --all`
   - Clean all caches: `python -m modflow_devtools clean --all`
   - Individual API operations: `python -m modflow_devtools.{api} sync|info|list|clean`

8. **MergedRegistry pattern**: Only used where needed
   - Models: Yes (essential for multi-source/multi-ref unified view)
   - Programs: No (program names globally unique, simple merge functions suffice)
   - DFNs: No (users work with one MF6 version at a time)

9. **Core class pattern** (Models API classes as template):
   - **`{API}Cache`**: Cache management (save/load/has/list/clear methods)
   - **`{API}SourceRepo`**: Source repository with discover/sync/is_synced methods
   - **`{API}SourceConfig`**: Configuration container with load/merge/status/sync
   - **`{API}Registry`**: Pydantic data model for registry structure
   - **`Pooch{API}Registry`**: Remote fetching with Pooch integration
   - **`Discovered{API}Registry`**: Discovery result with metadata

### Key Differences

| Aspect | Models | Programs | DFNs |
|--------|--------|----------|------|
| **Discovery** | Release assets or version control | Release assets only | Version control (+ release assets future) |
| **URL type** | Raw content or release download | Release download only | Raw content only |
| **Bootstrap fields** | `repo`, `name`, `refs`, `registry_path` | `repo`, `refs` | `repo`, `refs`, `dfn_path`, `registry_path` |
| **Addressing** | `source@ref/path` | `program@version` | `mf6@ref/component` |
| **MergedRegistry** | Yes | No | No |

## Demo & Usage Examples

This section provides practical examples of using the new Models API.

### Python API

#### Basic Workflow

```python
from modflow_devtools.models import ModelSourceConfig, _DEFAULT_CACHE

# 1. Load bootstrap configuration (with user overlay)
config = ModelSourceConfig.load()

# 2. Discover remote registry
source = config.sources["modflow6-testmodels"]
discovered = source.discover(ref="develop")
# Returns: DiscoveredModelRegistry with mode, URL, and parsed registry

# 3. Sync registry to local cache
result = source.sync(ref="develop", verbose=True)
# Returns: SyncResult(synced=[...], skipped=[], failed=[])

# 4. Load cached registry and use it
registry = _DEFAULT_CACHE.load("mf6/test", "develop")
print(f"Models: {len(registry.models)}")
print(f"Files: {len(registry.files)}")
```

#### Object-Oriented API

```python
# Work with sources directly
source = config.sources["modflow6-testmodels"]

# Check if synced
if source.is_synced("develop"):
    print("Already cached!")

# List synced refs
synced_refs = source.list_synced_refs()

# Sync via source method
result = source.sync(ref="develop", verbose=True)

# Sync all sources
results = config.sync(verbose=True)

# Check status
status = config.status
for source_name, source_status in status.items():
    print(f"{source_name}: {source_status.cached_refs}")
```

#### Cache Management

```python
from modflow_devtools.models import _DEFAULT_CACHE

# Get cache locations
cache_root = _DEFAULT_CACHE.root

# List all cached registries
cached = _DEFAULT_CACHE.list()  # Returns: [(source, ref), ...]

# Check specific cache
is_cached = _DEFAULT_CACHE.has("mf6/test", "develop")

# Load from cache
registry = _DEFAULT_CACHE.load("mf6/test", "develop")

# Save to cache
_DEFAULT_CACHE.save(registry, "mf6/test", "develop")

# Clear cache
_DEFAULT_CACHE.clear()
```

### CLI Usage

#### Show Registry Status

```bash
$ mf models info

Registry sync status:

mf6/test (wpbonelli/modflow6-testmodels)
  Configured refs: registry
  Cached refs: registry

mf6/example (MODFLOW-ORG/modflow6-examples)
  Configured refs: current
  Cached refs: none
  Missing refs: current
```

#### Sync Registries

```bash
# Sync all configured sources/refs
$ mf models sync

# Sync specific source
$ mf models sync --source modflow6-testmodels

# Sync specific ref
$ mf models sync --source modflow6-testmodels --ref develop

# Force re-download
$ mf models sync --force

# Test against a fork
$ mf models sync \
    --source modflow6-testmodels \
    --ref feature-branch \
    --repo myusername/modflow6-testmodels
```

#### List Available Models

```bash
# Summary view
$ mf models list

# Verbose view (show all model names)
$ mf models list --verbose

# Filter by source
$ mf models list --source mf6/test

# Filter by ref
$ mf models list --ref registry

# Combine filters
$ mf models list --source mf6/test --ref registry --verbose
```

#### Clear Cached Registries

```bash
# Clear all cached registries (with confirmation)
$ mf models clear

# Clear specific source
$ mf models clear --source mf6/test

# Clear specific source and ref
$ mf models clear --source mf6/test --ref develop

# Skip confirmation prompt
$ mf models clear --force
```

### Registry Creation Tool

The `make_registry` tool uses a mode-based interface with **remote-first operation** by default:

**Version-controlled models** (downloads from remote):
```bash
# Downloads repo and indexes subdirectory
python -m modflow_devtools.models.make_registry \
  \
  --repo MODFLOW-ORG/modflow6-testmodels \
  --ref master \
  --name mf6/test \
  --path mf6 \
  --output .registry
```

**Release asset models** (downloads from remote):
```bash
# Downloads repo and indexes subdirectory
python -m modflow_devtools.models.make_registry \
  --asset-file mf6examples.zip \
  --repo MODFLOW-ORG/modflow6-examples \
  --ref current \
  --asset-file mf6examples.zip \
  --name mf6/example \
  --path examples \
  --output .registry
```

**No path - indexes entire repo**:
```bash
# Downloads repo and indexes from root
python -m modflow_devtools.models.make_registry \
  \
  --repo MODFLOW-ORG/modflow6-testmodels \
  --ref master \
  --name mf6/test \
  --output .registry
```

**Local testing** (only if path exists locally):
```bash
# Uses existing local checkout
python -m modflow_devtools.models.make_registry \
  \
  --repo MODFLOW-ORG/modflow6-testmodels \
  --ref master \
  --name mf6/test \
  --path /absolute/path/to/modflow6-testmodels/mf6 \
  --output .registry
```

**Key Features**:
- **Remote-first**: Downloads from GitHub by default, ensuring registry matches remote state
- **Intelligent `--path` parameter**:
  - Relative path like `mf6` → downloads and uses as subdirectory
  - Existing local directory → uses local checkout (for testing)
  - Omitted → downloads and indexes repo root
- **Automatic mode detection**: Presence of `--asset-file` indicates release asset mode, otherwise version-controlled mode
- **Automatic URL construction**: No manual URL typing required
- **No git dependency**: Uses GitHub's zipball API
- **Clear naming**: `--name` matches bootstrap file's `name` field
- **Consolidated registry format**: Always generates single `models.toml` file

### User Config Overlay for Fork Testing

Create a user config at `%APPDATA%/modflow-devtools/models.toml` (Windows) or `~/.config/modflow-devtools/models.toml` (Linux/macOS):

```toml
[sources.modflow6-testmodels]
repo = "wpbonelli/modflow6-testmodels"
name = "mf6/test"
refs = ["registry"]

[sources.modflow6-largetestmodels]
repo = "wpbonelli/modflow6-largetestmodels"
name = "mf6/large"
refs = ["registry"]
```

This allows testing against forks without modifying the bundled config!

### Upstream CI Workflow Examples

**For version-controlled models** (e.g., testmodels):
```yaml
- name: Generate registry
  run: |
    python -m modflow_devtools.models.make_registry \
      \
      --repo MODFLOW-ORG/modflow6-testmodels \
      --ref ${{ github.ref_name }} \
      --name mf6/test \
      --path mf6 \
      --output .registry

- name: Commit registry
  run: |
    git add .registry/models.toml
    git commit -m "Update registry [skip ci]"
    git push
```

**For release asset models** (e.g., examples):
```yaml
- name: Generate registry
  run: |
    python -m modflow_devtools.models.make_registry \
      --asset-file mf6examples.zip \
      --repo MODFLOW-ORG/modflow6-examples \
      --ref ${{ github.ref_name }} \
      --asset-file mf6examples.zip \
      --name mf6/example \
      --path examples \
      --output .registry

- name: Upload registry as release asset
  uses: actions/upload-release-asset@v1
  with:
    asset_path: .registry/models.toml
    asset_name: models.toml
```

**Note**: The tool will download from the remote repository at the specified ref, ensuring the generated registry exactly matches what will be available remotely. This eliminates any possibility of local/remote state mismatches.

## Open Questions / Future Enhancements

1. **Registry compression**: Zip registry files for faster downloads?
2. **Partial registry updates**: Diff registries and download only changes?
3. **Registry CDN**: Consider hosting registries somewhere for faster access?
4. **Offline mode**: Provide an explicit "offline mode" that never tries to sync?
5. **Registry analytics**: Track which models/examples are most frequently accessed?
