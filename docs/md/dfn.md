# Working with definition files

MODFLOW 6 specifies input components and their variables in configuration files with a custom format. Such files are called definition (DFN) files and conventionally have suffix `.dfn`.

The `modflow_devtools.dfn` module provides some utilities for working with MODFLOW 6 input specification files.

## TOML migration

Work is underway to migrate MODFLOW 6 input specifications to a standard data interchange format, namely TOML.

The `modflow_devtools.dfn` module contains a parser for the legacy DFN format and a command line tool to convert legacy DFN files to TOML.

We envision MODFLOW 6 and FloPy will use these for a short period while migration is underway. This will involve adapting code- and documentation-generating systems to consume TOML. When this is complete, this module can be retired.

### Format differences

The TOML format is structurally different from, but visually similar to, the original DFN format.

Where legacy DFNs are flat lists of variables, with comments demarcating blocks, a TOML input definition is a tree of blocks, each of which contains child variables, each of which can be a scalar or a composite &mdash; composites contain their own child variables.

Block variables are not explicitly marked as such &mdash; rather they are attached directly to the parent and must be identified by their type (i.e., dictionary not scalar). Likewise for a composite variable's children.

A definition may contain other top-level attributes besides blocks, so long as they do not conflict with block names.

Similarly, variables may contain arbitrary attributes so long as these do not conflict with child variable names.

### Conversion script

The `dfn` dependency group is necessary to use the TOML conversion utility.

To convert definition files to TOML, use:

```shell
python -m modflow_devtools.dfn.dfn2toml -i <dfn dir path> -o <output dir path>
```
