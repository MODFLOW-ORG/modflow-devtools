# Working with definition files

MODFLOW 6 specifies input components and their variables in configuration files with a custom format. Such files are called definition (DFN) files and conventionally have suffix `.dfn`.

The `modflow_devtools.dfns` module provides a structured API for working with MODFLOW 6 input specifications, including typed Python objects representing each component and field type, tools for acquiring, loading and managing specification versions, and a utility to convert `.dfn` files to a revised schema and standard file formats.

The `modflow_devtools.dfn` module provides a limited subset of the same functionality, but is now deprecated. This module will be removed with `modflow-devtools` version 2.x. The `modflow_devtools.dfns` module should in most cases be used instead, however it remains experimental and may change without notice until version 2.x.

A warning to this effect is shown when `modflow_devtools.dfns` is imported. To suppress the warning, use:

```python
import warnings

warnings.filterwarnings("ignore", message=".*modflow_devtools.dfns.*experimental.*")
```

The `ecosystem` optional dependency group is required to use either the `dfn` or `dfns` module.

```shell
pip install modflow-devtools[ecosystem]
```

The `dfn` dependency group is also sufficient, but this group is deprecated and will be removed with `modflow-devtools` version 2.x.

## CLI

A command line interface is available to manage sets of DFN files corresponding to MODFLOW 6 releases.

### Cache management

```shell
# Fetch DFNs from GitHub release assets
python -m modflow_devtools.dfns sync

# Force re-download even if already cached
python -m modflow_devtools.dfns sync --force

# Add (and sync) a specific release
python -m modflow_devtools.dfns add MODFLOW-ORG/modflow6@6.7.0

# Show sync status
python -m modflow_devtools.dfns info

# Clean the cache
python -m modflow_devtools.dfns clean
```

### Migration

The `migrate` subcommand converts `.dfn` files to a new schema version.

```shell
python -m modflow_devtools.dfns migrate -i <dfn path> -o <output path> -s <schema version> [-f <format>]
```

The migration tool may be used on directories or individual files.

Supported schema versions are currently `"2.0.0.dev0"`, `"2.0.0.dev1"`, and `"2.0.0.dev2"` (`CURRENT_SCHEMA_VERSION`). Note that `2.0.0.dev2` is under active development and may change without warning.

The default serialization format is YAML. Use `--format` / `-f` to select `yaml` (default), `toml`, or `json`.

### Configuration

The `modflow-devtools` package ships with a built-in configuration specifying default DFN release versions to support:

```toml
releases = [
    "MODFLOW-ORG/modflow6@latest",
    "MODFLOW-ORG/modflow6-nightly-build@latest"
]
```

**Note:** DFN file sets must be published as a release asset called `dfns.zip` with each configured release.

You can extend or override the default registry configuration by creating an overlay configuration file:

- Linux/macOS: `~/.config/modflow-devtools/dfns.toml` (respects `$XDG_CONFIG_HOME`)
- Windows: `%APPDATA%/modflow-devtools/dfns.toml`

Entries in this file are merged with (and take precedence over) the defaults. The file uses the same format as the bundled configuration file. For instance, to point to DFN releases on your own fork, substitute your GitHub username for "MODFLOW-ORG".

### Cache layout

DFN file sets are cached under:

- Linux/macOS: `$XDG_CACHE_HOME/modflow-devtools/dfns/` (default `~/.cache/`)
- Windows: `%LOCALAPPDATA%/modflow-devtools/dfns/`

The cache is organized by repository and release tag:

```
~/.cache/modflow-devtools/dfns/
└── MODFLOW-ORG/
    └── modflow6/
        ├── 6.6.0/
        │   ├── sim-nam.dfn
        │   ├── gwf-chd.dfn
        │   └── ...
        └── 6.5.0/
            └── ...
```

## Python API

### Schema version

The current schema version is exposed as a constant:

```python
from modflow_devtools.dfns import CURRENT_SCHEMA_VERSION  # "2.0.0.dev2"
```

### Loading DFNs

`Dfns` is a Pydantic model representing a set of component definitions. Load a directory of definition files with `Dfns.load()`:

```python
from modflow_devtools.dfns import Dfns

spec = Dfns.load("/path/to/mf6/doc/mf6io/mf6ivar/dfn")
```

**Note**: Calling `Dfns.load()` on a directory of `.dfn` files will convert to `CURRENT_SCHEMA_VERSION` (`"2.0.0.dev2"`) automatically.

For lower-level access, `fetch_dfns` downloads all `.dfn` files for a specific release to a local directory:

```python
from modflow_devtools.dfns import fetch_dfns

fetch_dfns("MODFLOW-ORG", "modflow6", "6.6.0", "/tmp/dfns")
```

In most cases, using `RemoteDfnRegistry` (see [Managing DFNs](#managing-dfns)) is preferable since it handles caching automatically.

### Inspecting DFNs

```python
spec.schema_version  # e.g. CURRENT_SCHEMA_VERSION ("2.0.0.dev2")
spec.root  # the Simulation component, or None
len(spec.components)  # total number of components

# Dict-like access to components
gwf_chd = spec.components["gwf-chd"]
gwf_chd.name  # "gwf-chd"
gwf_chd.parent  # "gwf-nam"

# Navigate the component hierarchy
sim_children = spec.children("sim-nam")  # {"gwf-nam": ..., ...}
gwf_children = spec.children("gwf-nam")  # {"gwf-chd": ..., "gwf-wel": ..., ...}
```

Each entry in `spec.components` is one of three component types, discriminated by a `type` field:

- `Simulation` — the root component (`sim-nam`)
- `Model` — a hydrologic process model (e.g. `gwf-nam`, `gwt-nam`)
- `Package` — any other input component (e.g. `gwf-chd`, `gwf-wel`)

```python
from modflow_devtools.dfns import Simulation, Model, Package

gwf_nam = spec.components["gwf-nam"]
assert isinstance(gwf_nam, Model)

gwf_chd = spec.components["gwf-chd"]
assert isinstance(gwf_chd, Package)
assert gwf_chd.multi is False
assert gwf_chd.subtype == "stress"
```

Each component has `blocks`, a dict mapping block names to `Block` objects. Each `Block` has a `fields` dict of typed field objects.

```python
from modflow_devtools.dfns import Block, Keyword, Double, List, Record

period = gwf_chd.blocks["period"]
assert period.repeats is True
assert period.header.field.name == "iper"
assert period.header.fill_forward is True

spd = period.fields["stress_period_data"]
assert isinstance(spd, List)
assert isinstance(spd.item, Record)

cellid = spd.item.fields["cellid"]
assert isinstance(cellid, Array)
```

Available field types:

| Class | `type` value | Description |
|---|---|---|
| `Keyword` | `"keyword"` | Boolean presence/absence |
| `String` | `"string"` | String value |
| `Integer` | `"integer"` | Integer value |
| `Double` | `"double"` | Floating-point value |
| `File` | `"file"` | File path |
| `Array` | `"array"` | Fixed or dynamic array |
| `Record` | `"record"` | Single-line product type |
| `Union` | `"union"` | Tagged sum type |
| `List` | `"list"` | Tabular collection |

See [DFN specification](dfnspec.md) for full attribute documentation.

### Rendering block templates

`Block.render()` produces a `BEGIN/END` template string showing the structure of a block — the same format used in the MODFLOW 6 user guide and in tooling such as IDE hover text:

```python
wel = spec.components["gwf-wel"]

print(wel.blocks["options"].render())
# BEGIN OPTIONS
#   [AUXILIARY <auxiliary>]
#   [AUXMULTNAME <auxmultname>]
#   [BOUNDNAMES]
#   [PRINT_INPUT]
#   ...
# END OPTIONS

print(wel.blocks["period"].render())
# BEGIN PERIOD <iper>
#   <cellid(ncelldim)> <q> [<aux(auxiliary)>] [<boundname>]
#   <cellid(ncelldim)> <q> [<aux(auxiliary)>] [<boundname>]
#   ...
# END PERIOD
```

A block whose `header` is set (see [`header`](dfnspec.md#header)) has that field's token attached to the `BEGIN` line rather than rendered as a body row — `<iper>` above comes from `wel.blocks["period"].header.field`, not `.fields`. `header.fill_forward` says whether a missing occurrence of the block means "reuse the prior occurrence's values" — `True` for `period`, since MF6 reuses the prior stress period's data across gaps.

`ComponentBase.render()` renders all blocks joined by blank lines:

```python
print(wel.render())
# BEGIN OPTIONS
#   ...
# END OPTIONS
#
# BEGIN DIMENSIONS
#   ...
# END DIMENSIONS
#
# BEGIN PERIOD <iper>
#   ...
# END PERIOD
```

Rendering rules by field type:

| Field type | Block-level rendering | Inline (inside record row) |
|---|---|---|
| `Keyword` | `KEYWORD` | `KEYWORD` |
| `String` / `Integer` / `Double` (tagged) | `NAME <name>` | `<name>` |
| `String` / `Integer` / `Double` (untagged) | `<name>` | `<name>` |
| `File` (tagged) | `NAME FILEIN\|FILEOUT <name>` | `NAME FILEIN\|FILEOUT <name>` |
| `File` (untagged) | `FILEIN\|FILEOUT <name>` | `FILEIN\|FILEOUT <name>` |
| `Array` with shape (READARRAY) | `NAME\n    <name(shape)> -- READARRAY` | `<name(shape)>` |
| `Array` without shape (inline) | `NAME <name>` | `<name(shape)>` |
| `Record` | children expanded inline | children expanded inline |
| `Union` with `Record` arms | one optional row per arm | `<name>` |
| `Union` with scalar arms | `<name>` repeated + `...` | `<name>` |
| `List` (single row type) | row repeated twice + `...` | — |
| `List` with `Record`-arm `Union` | one row per arm, no `...` | — |
| `List` with scalar-arm `Union` | `<name>` twice + `...` | — |
| `Block.header.field` (any field type) | attached to `BEGIN <NAME>` line, inline form | — |

Optional fields are wrapped in `[...]`. Array shapes use the abstract dimension names from the specification (e.g. `ncelldim`, `naux`) rather than resolved grid-specific values.

The two `Union`-in-`List` cases correspond to different MF6 idioms:

- **Union of Records** (e.g. `gwf-oc` period block): the `output` list accepts either a `SAVE` row or a `PRINT` row — each arm is shown as a distinct optional row with no ellipsis.
- **Union of scalars** (e.g. `prt-prp` period block): the `perioddata` list accepts one of several keywords (`ALL`, `FIRST`, `LAST`, `FREQUENCY`, `STEPS`, `FRACTION`) — the alternatives are collapsed to `<releasesetting>` to avoid noise.

### Managing DFNs

A registry system handles caching and accessing DFN files from MODFLOW 6 releases. `DfnRegistry` is the abstract base class; `LocalDfnRegistry` and `RemoteDfnRegistry` are the two concrete implementations.

For working with DFN files on the local filesystem, there is `LocalDfnRegistry`.

```python
from modflow_devtools.dfns import LocalDfnRegistry

registry = LocalDfnRegistry(path="/path/to/mf6/doc/mf6io/mf6ivar/dfn")
spec = registry.spec()  # Dfns instance
path = registry.get_path("gwf-chd")  # Path to the component file
```

For fetching and caching DFN files from a MODFLOW 6 release, `RemoteDfnRegistry`:

```python
from modflow_devtools.dfns import RemoteDfnRegistry

registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@6.6.0")
registry.sync()  # download and cache DFN files
registry.sync(force=True)  # force re-download

spec = registry.spec()  # get the specification

tag = registry.latest_tag()  # resolve "latest" to actual tag
tag = registry.cached_tag()  # return cached tag
```

The `release_id` takes the form `"owner/repo@tag"`, where `tag` may be a specific version or `"latest"`.

For `@latest`, `latest_tag()` queries the GitHub API once and caches the result.

To load the default registry configuration, i.e. the bundled configuration with user overlay if present:

```python
registries = RemoteDfnRegistry.load_default()
```

To load specific releases:

```python
registries = RemoteDfnRegistry.from_ids(
    "MODFLOW-ORG/modflow6@6.6.0",
    "MODFLOW-ORG/modflow6@6.5.0",
)
```

To get the base cache path programmatically:

```python
RemoteDfnRegistry.base_cache_path()
```

To check whether a release is cached:

```python
from modflow_devtools.dfns.registry import is_cached

is_cached("MODFLOW-ORG/modflow6@6.6.0")
```

### Environment variables

| Variable | Values | Effect |
|---|---|---|
| `MODFLOW_DEVTOOLS_AUTO_SYNC` | `1`, `true`, `yes` | `RemoteDfnRegistry.from_ids()` automatically calls `sync()` for any release ID with no cached files yet. |
