# Working with definition files

MODFLOW 6 specifies input components and their variables with a custom file format. Input specification files are called definition (DFN) files and conventionally have suffix `.dfn`.

Work is underway to migrate MODFLOW 6 input specifications to a standard data interchange format. TOML has tentatively been selected.

The `modflow_devtools.dfn` module contains a parser for the legacy DFN format, a format-agnostic representation for input specifications, and a TOML conversion utility.

We envision MODFLOW 6 and FloPy will use these utilities for a relatively short period while the TOML migration is underway. This will involve adapting automated code- and documentation-generation systems in both MF6 and FloPy to consume TOML rather than DFN files. When this is complete, these utilities should no longer be necessary.

## TOML conversion

The `dfn` optional dependency group is necessary to use the TOML conversion utility.

To convert definition files to TOML, use:

```shell
python -m modflow_devtools.dfn.dfn2toml -i <path to dfns> -o <output dir path>
```

### Format

The TOML format is structurally different from the original DFN format: where legacy DFNs are flat lists of variables, with comments demarcating blocks, a TOML input definition is a tree of blocks, each of which contains child variables, each of which can be a scalar or a composite &mdash; composites contain their own child variables. The definition may also contain other top-level attributes besides blocks, so long as they do not conflict with block names.

Children are not explicitly marked as such &mdash; rather children are attached directly to the parent and can be identified by their type (i.e., as a dictionary rather than a scalar).

While structurally different, TOML definition files are visually similar to the DFN format, due to the fact that TOML represents hierarchy with headers, rather than indentation as in YAML. 
