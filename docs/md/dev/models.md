# Models API Design

This document describes the (re)design of the Models API ([GitHub issue #134](https://github.com/MODFLOW-ORG/modflow-devtools/issues/134)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

This is a living document which will be updated as development proceeds. As the reimplementation nears completion, the scope here will shrink from charting a detailed transition path to simply describing the new design.

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



TODO clean up robot slop below


### Registry synchronization

#### Install-Time Behavior
- **Best-effort sync** on package install (via `setup.py` or similar)
- **Warn if unsuccessful** but allow install to succeed
- **Retry on first import** if sync failed during install
- **Clear user messaging**: "Registry sync failed, remote models unavailable. Run `python -m modflow_devtools.models sync` to retry."

#### Manual Sync Command

**CLI**: `python -m modflow_devtools.models`

**Subcommands**:
```bash
# Sync all sources to default refs (latest release tag → master → develop)
python -m modflow_devtools.models sync

# Sync all sources to specific ref (branch or tag)
python -m modflow_devtools.models sync --ref develop
python -m modflow_devtools.models sync --ref v1.2.3

# Sync specific source
python -m modflow_devtools.models sync --source modflow6-examples

# Sync specific source to specific ref
python -m modflow_devtools.models sync --source modflow6-examples --ref develop
python -m modflow_devtools.models sync --source modflow6-examples --ref v1.2.3

# Force re-download even if cached
python -m modflow_devtools.models sync --force

# List available registries and their status
python -m modflow_devtools.models list

# Show sync status
python -m modflow_devtools.models status
```

**Error handling for unsupported refs**:
```bash
# Commit SHA not supported - clear error message
python -m modflow_devtools.models sync --ref abc123def
# Error: Commit SHAs are not supported. Registries are only generated for branches and release tags.
#        Please use a branch name (e.g., 'master', 'develop') or release tag (e.g., 'v1.2.3').
```

**Programmatic API**:
```python
from modflow_devtools.models import sync_registry, get_registry

# Sync and use default (latest release tag → master → develop)
sync_registry()
registry = get_registry()

# Sync to specific ref (branch or tag)
sync_registry(ref="develop")
sync_registry(ref="v1.2.3")

# Use specific ref without syncing
registry = get_registry(ref="develop")  # uses cached, syncs if missing
registry = get_registry(ref="v1.2.3")   # uses cached release tag

# Use specific source and ref
registry = get_registry(source="modflow6-examples", ref="develop")
registry = get_registry(source="modflow6-examples", ref="v1.2.3")

# Error on commit SHA
try:
    registry = get_registry(ref="abc123def")
except ValueError as e:
    print(e)  # "Commit SHAs are not supported..."
```

#### Sync Implementation
- **For release tags**: Download registry files from GitHub release assets
- **For branches**: Download registry files from GitHub raw URLs (e.g., `https://raw.githubusercontent.com/MODFLOW-ORG/modflow6-examples/{branch}/.registry/registry.toml`)
- Validate schema version and structure
- Cache to local directory (named by ref - tag or branch)
- Merge multiple sources at API level (keep files separate on disk)
- **Ref detection**: Use GitHub API to determine if ref is a tag or branch

### Registry generation

**Required changes in each model repo** (modflow6-examples, modflow6-testmodels, modflow6-largetestmodels):

#### CI Workflow
**File**: `.github/workflows/registry.yml`

**Trigger**: Push to master/develop branches, or release tag creation

**Steps**:
1. Install `modflow-devtools` (provides registry generation machinery)
2. Run registry generation:
   ```bash
   python -m modflow_devtools.make_registry \
     --path . \
     --output .registry \
     --url <appropriate-base-url>
   ```
3. Commit registry files to `.registry/` directory (for branches)
4. For release tags: Attach registry files as release assets

**Notes**:
- Registry generation machinery remains in `modflow-devtools`
- Model repos consume it as a dependency
- Keeps single source of truth for registry format

#### Directory Structure
```
modflow6-examples/
├── .registry/
│   ├── registry.toml
│   ├── models.toml
│   └── examples.toml
├── examples/
│   └── ...
└── .github/
    └── workflows/
        └── registry.yml
```

### Registry classes

#### Core Principle: Separation of Concerns

- **`PoochRegistry`**: Single source, single ref - knows nothing about other sources
- **`MergedRegistry`**: Pure compositor - just merges existing registries, no construction logic
- **Module-level functions**: Handle sync, construction, and convenience APIs

#### Model Naming Convention

**Format**: `{source}@{ref}/{subpath}`

**Components**:
- `source`: Repository identifier (e.g., `modflow6-examples`, `modflow6-testmodels`)
- `ref`: Git ref (branch or tag, e.g., `v1.2.3`, `master`, `develop`)
- `subpath`: Relative path within repo to model directory

**Examples**:
- `modflow6-examples@v1.2.3/ex-gwf-twri`
- `modflow6-testmodels@develop/mf6/test001a_Tharmonic`
- `modflow6-largetestmodels@master/prudic2004t2`

**Benefits**:
- Guarantees no name collisions (unique per source + ref + path)
- Makes model provenance explicit to users
- Allows mixing multiple refs of same source
- Simplifies cache key generation

#### PoochRegistry (Single Source)

**Purpose**: Represent a single source repository at a specific ref

**Constructor**: Takes `source` (repo name) and `ref` (branch/tag)

```python
class PoochRegistry(ModelRegistry):
    def __init__(self, source: str, ref: str | None = None, cache_path: PathLike | None = None):
        """Create registry for a single source repository

        Args:
            source: Source repository name (e.g., "modflow6-examples")
            ref: Git ref - branch name or release tag
                 (default: latest release tag → master → develop)
                 Commit SHAs not supported.
            cache_path: Override default cache location

        Raises:
            ValueError: If ref is a commit SHA
            FileNotFoundError: If registry not cached and sync fails
        """
        self._source = source
        self._ref = self._resolve_ref(ref)  # Applies default priority
        self._cache_path = cache_path or self._default_cache_path()
        self._load()  # Load from cache, auto-sync if missing

    @property
    def source(self) -> str:
        """Source repository name"""
        return self._source

    @property
    def ref(self) -> str:
        """Git ref (branch or tag)"""
        return self._ref

    def sync(self, force: bool = False) -> None:
        """Sync this registry from upstream

        Automatically discovers registry location and mode:
        1. If ref is a tag: Try release assets first
        2. Fallback: Try .registry/ directory in repository
        3. After loading: Inspect metadata to determine fetch strategy

        Args:
            force: Re-download even if cached

        Raises:
            FileNotFoundError: If registry not found in either location
        """
        # Try release assets if ref is a tag
        if self._is_tag(self._ref):
            try:
                self._sync_from_release_assets()
                self._setup_pooch()  # Configure based on metadata
                return
            except ReleaseNotFound:
                pass  # Fall through to repository

        # Try .registry/ directory in repository
        try:
            self._sync_from_repository()
            self._setup_pooch()  # Configure based on metadata
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Registry for '{self._source}@{self._ref}' not found. "
                f"Tried: release assets (if tag) and repository .registry/ directory."
            )

    def _setup_pooch(self) -> None:
        """Configure Pooch based on registry metadata (mode detection)"""
        meta = self._meta

        if "release_asset" in meta:
            # Mode 2, Option A: Single zip with registry + models
            self._fetch_mode = "single_zip"
            self._asset_name = meta["release_asset"]

        elif "models_asset" in meta:
            # Mode 2, Option B: Separate registry and model assets
            self._fetch_mode = "models_zip"
            self._asset_name = meta["models_asset"]

        else:
            # Mode 1: In-repo individual files
            self._fetch_mode = "individual_files"
            # URLs already in registry from make_registry.py

    def is_synced(self) -> bool:
        """Check if registry is cached for this source/ref"""
        ...

    # Inherited from ModelRegistry abstract class
    @property
    def files(self) -> dict:
        """Map of file names to file info (with source@ref prefix)"""
        ...

    @property
    def models(self) -> dict:
        """Map of model names to file lists (with source@ref prefix)"""
        ...

    @property
    def examples(self) -> dict:
        """Map of example names to model lists (with source@ref prefix)"""
        ...
```

**Key changes from current**:
- Loads from cache by default (not package resources)
- Auto-syncs if cache missing (best-effort on first access)
- All keys prefixed with `{source}@{ref}/` in returned dicts

#### MergedRegistry (Compositor)

**Purpose**: Merge multiple `ModelRegistry` instances into unified API

**Constructor**: Takes list of pre-constructed registry instances

```python
class MergedRegistry(ModelRegistry):
    def __init__(self, registries: list[ModelRegistry]):
        """Merge multiple registries into unified API

        Args:
            registries: List of ModelRegistry instances (typically PoochRegistry)
                        Caller is responsible for constructing these with desired
                        sources and refs.

        Note:
            This class is a pure compositor - it knows nothing about sources,
            refs, syncing, or construction. All that logic happens before
            MergedRegistry is created.
        """
        self._registries = list(registries)

    @property
    def registries(self) -> list[ModelRegistry]:
        """The underlying registries being merged"""
        return list(self._registries)  # Return copy

    # Inherited from ModelRegistry - merge results from all registries
    @property
    def files(self) -> dict:
        """Merged files from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.files)
        return merged

    @property
    def models(self) -> dict:
        """Merged models from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.models)
        return merged

    @property
    def examples(self) -> dict:
        """Merged examples from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.examples)
        return merged
```

**Why no factory methods?**
- Construction is trivial: `MergedRegistry([reg1, reg2])`
- Users can easily create new instances when refs change
- Keeps the class focused and simple
- Avoids coupling MergedRegistry to PoochRegistry

**Usage examples**:
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

### Module-Level API

**Purpose**: Provide convenient access for common use cases

```python
# Module: modflow_devtools.models

def get_registry(
    source: str | None = None,
    ref: str | None = None,
    sources: dict[str, str] | None = None
) -> ModelRegistry:
    """Get a registry (single source or merged)

    Args:
        source: Single source name (returns PoochRegistry)
        ref: Git ref to use (applies to single source or all sources)
        sources: Dict mapping source names to refs for mixed-ref merged registry
                 e.g., {"modflow6-examples": "v1.2.3", "modflow6-testmodels": "develop"}

    Returns:
        PoochRegistry if source specified, otherwise MergedRegistry

    Examples:
        # Single source
        reg = get_registry(source="modflow6-examples", ref="v1.2.3")

        # All sources, same ref
        reg = get_registry(ref="develop")

        # All sources, default refs (latest release → master → develop)
        reg = get_registry()

        # All sources, mixed refs
        reg = get_registry(sources={
            "modflow6-examples": "v1.2.3",
            "modflow6-testmodels": "develop"
        })
    """
    if source:
        return PoochRegistry(source, ref)

    if sources:
        registries = [PoochRegistry(src, r) for src, r in sources.items()]
    else:
        # Load all from bootstrap, apply same ref to all
        bootstrap = load_bootstrap()
        registries = [PoochRegistry(src, ref) for src in bootstrap.sources.keys()]

    return MergedRegistry(registries)


def sync_registry(source: str | None = None, ref: str | None = None, force: bool = False) -> None:
    """Sync registry from upstream

    Args:
        source: Specific source to sync (default: all sources from bootstrap)
        ref: Git ref to sync (default: latest release → master → develop)
        force: Force re-download even if cached
    """
    if source:
        registry = PoochRegistry(source, ref)
        registry.sync(force=force)
    else:
        bootstrap = load_bootstrap()
        for src in bootstrap.sources.keys():
            registry = PoochRegistry(src, ref)
            registry.sync(force=force)


# DEFAULT_REGISTRY is now a MergedRegistry
DEFAULT_REGISTRY = get_registry()  # All sources, default refs
```

## Migration path

Ideally, we can avoid breaking existing code, and provide a gentle migration path for users with clear deprecation warnings and/or error messages where necessary.

For the remainder of the 1.x release series, keep shipping registry metadata with `modflow-devtools` for backwards-compatibility, now with the benefit of explicit model versioning. Allow syncing on demand for access to model updates. Stop shipping registry metadata and begin syncing remote model registry metadata at install time with the release of 2.x.

Then metadata shipped with `modflow-devtools` should be a few KB at most.

**Approach**:
1. Continue shipping full registry in v1.x
2. Add sync functionality as optional enhancement
3. Emit deprecation warning on import:
   ```
   DeprecationWarning: Bundled registry is deprecated and will be removed in v2.0.
   Use `python -m modflow_devtools.models sync` to download the latest registry.
   ```
4. Provide migration guide in docs

**Breaking changes in v2.x**:
- Remove bundled registry files (except bootstrap.toml)
- Require sync for remote registry access (LocalRegistry unaffected)
- Document migration clearly in CHANGELOG

### Implementation Plan

#### Phase 1: Foundation (v1.x)
1. Add bootstrap metadata file
2. Implement registry schema with Pydantic validation
3. Create cache directory structure utilities
4. Add `sync_registry()` function with download logic
5. Implement branch priority resolution
6. Add CLI subcommands (sync, list, status)

#### Phase 2: PoochRegistry Adaptation (v1.x)
1. Modify `PoochRegistry.__init__()` to check cache first
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

## Key Design Decisions

1. **Install-time sync**: Best-effort, warn on failure, allow install to proceed
2. **Registry location**: `.registry/` directory on each branch in model repos; also as release assets for tagged releases
3. **Bootstrap format**: Minimal TOML with just repo identifiers - no hints about location or fetch strategy
4. **Registry modes**: Self-describing via metadata attributes
   - Mode 1 (in-repo): No asset attributes → individual file fetching
   - Mode 2 (release-only): `release_asset`, `registry_asset`, or `models_asset` → zip fetching
   - Mode discovered automatically during sync
5. **Multi-ref caching**: Support simultaneous caching of multiple refs (tags and branches)
6. **Schema versioning**: Use Pydantic, include `_meta` section in registries
7. **Ref priority**: Latest release tag → master branch → develop branch (when user doesn't specify)
8. **Ref support**: Branch names and release tags supported; commit SHAs not supported (with clear error message)
9. **CLI parameter**: Use `--ref` (not `--branch`) to clarify support for both tags and branches
10. **Transition**: Optional in v1.x with deprecation warning, required in v2.x
11. **Registry architecture**: Clear separation of concerns
    - `PoochRegistry`: Single source, single ref - no knowledge of other sources
    - `MergedRegistry`: Pure compositor - takes pre-built registries, no construction logic
    - Module functions: Handle sync, construction, convenience APIs
12. **Model naming**: `{source}@{ref}/{subpath}` format guarantees collision-free names and explicit provenance
13. **Registry merging**: Keep separate on disk and in separate `PoochRegistry` instances, merge via `MergedRegistry`
14. **No factory methods**: `MergedRegistry` construction is trivial, users create new instances directly
15. **Mixed refs**: Supported naturally via naming scheme - can mix multiple refs of same source
16. **LocalRegistry**: Remains independent, serves different purpose (local development)

### Name Collisions
**Risk**: Models from different sources could have identical names.

**Mitigation**: Systematic naming scheme `{source}@{ref}/{subpath}` guarantees uniqueness:
- Each source has distinct identifier
- Refs are included in name
- Subpaths are unique within a source

**Example**: `modflow6-examples@v1.2.3/ex-gwf-twri` cannot collide with `modflow6-testmodels@develop/ex-gwf-twri`

### Partial Sync State
**Risk**: User syncs some sources but not others, leading to incomplete `MergedRegistry`.

**Mitigation**:
- `MergedRegistry` is transparent - only merges what it's given
- Module-level `get_registry()` handles ensuring sources are synced
- `PoochRegistry` auto-syncs on first access (best-effort)
- Clear error messages if sync fails

### Performance
**Risk**: Loading multiple registry files could be slow.

**Analysis**: Not a concern - TOML files load instantly (even 1.7MB registry is trivial). Model files download lazily via Pooch only when accessed.

**Decision**: No lazy loading needed for registries themselves.

### Error Propagation
**Risk**: One source failing to sync could break entire `MergedRegistry`.

**Mitigation**:
- `PoochRegistry` constructor fails fast if sync fails
- Caller (module functions) can handle errors before constructing `MergedRegistry`
- `MergedRegistry` itself is simple - no error handling needed (operates on valid registries)

### Backward Compatibility
**Risk**: Changing `DEFAULT_REGISTRY` from `PoochRegistry` to `MergedRegistry` breaks code checking `isinstance(DEFAULT_REGISTRY, PoochRegistry)`.

**Mitigation**:
- Both implement `ModelRegistry` abstract class
- API is identical for common operations
- Breaking change acceptable for v2.x with clear migration guide
- v1.x maintains current behavior with deprecation warnings

### Cache Invalidation
**Risk**: Registry instance doesn't reflect newly synced data.

**Mitigation**:
- Document that registries are immutable per ref
- To use new data, create new instance: `get_registry(ref="new-ref")`
- Construction is cheap (just loading TOML), so recreating is fine

## Open Questions / Future Enhancements

1. **Registry compression**: Should we gzip registry files for faster downloads?
2. **Partial registry updates**: Could we diff registries and download only changes?
3. **Registry CDN**: Should we consider hosting registries on a CDN for faster access?
4. **Offline mode**: Should we provide an explicit "offline mode" that never tries to sync?
5. **Registry analytics**: Track which models are most frequently accessed?
6. **Naming scheme refinement**: Keep current verbose prefixes (`mf6/example/`, `mf6/test/`) or simplify to `{repo-name}/{subpath}`?
