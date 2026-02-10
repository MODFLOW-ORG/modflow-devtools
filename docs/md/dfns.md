# Working with definition files

MODFLOW 6 specifies input components and their variables in configuration files with a custom format. Such files are called definition (DFN) files and conventionally have suffix `.dfn`.

The `modflow_devtools.dfn` module provides some utilities for working with MODFLOW 6 input specification files.

## TOML migration

Work is underway to migrate MODFLOW 6 input specifications to a standard data interchange format, namely TOML.

The `modflow_devtools.dfn` module contains a parser for the legacy DFN format and a command line tool to convert legacy DFN files to TOML.

We envision MODFLOW 6 and FloPy will use these for a short period while migration is underway. This will involve adapting code- and documentation-generating systems to consume TOML. When this is complete, this module can be retired.

### Format differences

The TOML format is structurally different from, but visually similar to, the original DFN format.

Where legacy DFNs are flat lists of variables, with comments demarcating blocks, a TOML input definition is a tree of blocks, each of which contains variables. Variables may be scalar or composite &mdash; composites contain fields (if records), choices (if unions), or items (if lists).

### Conversion script

The `dfn` dependency group is necessary to use the TOML conversion utility.

To convert definition files to TOML, use:

```shell
python -m modflow_devtools.dfn.dfn2toml -i <dfn dir path> -o <output dir path>
```
