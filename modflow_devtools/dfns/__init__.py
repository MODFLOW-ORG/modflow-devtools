"""Definition file tools"""

import warnings

from modflow_devtools.dfn import FieldType, fetch_dfns
from modflow_devtools.dfns.migrate import migrate
from modflow_devtools.dfns.registry import DfnRegistry, LocalDfnRegistry, RemoteDfnRegistry
from modflow_devtools.dfns.schema import (
    CURRENT_SCHEMA_VERSION,
    Array,
    Block,
    Blocks,
    Component,
    Dfns,
    Double,
    File,
    InputDim,
    InputField,
    InputFieldBase,
    Integer,
    Keyword,
    List,
    MemoryArray,
    MemoryScalar,
    MemoryVariable,
    MemoryVariableBase,
    Model,
    Package,
    Record,
    RuntimeDim,
    Scalar,
    ShapeRef,
    Simulation,
    String,
    Union,
    evaluate_dim,
    parse_shape_element,
    split_bound,
)

# Experimental API warning
warnings.warn(
    "The modflow_devtools.dfns API is experimental and may change or be "
    "removed in future versions without following normal deprecation procedures. "
    "Use at your own risk. To suppress this warning, use:\n"
    "  warnings.filterwarnings('ignore', "
    "message='.*modflow_devtools.dfns.*experimental.*')",
    FutureWarning,
    stacklevel=2,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Array",
    "Block",
    "Blocks",
    "Component",
    "DfnRegistry",
    "Dfns",
    "Double",
    "FieldType",
    "File",
    "InputDim",
    "InputField",
    "InputFieldBase",
    "Integer",
    "Keyword",
    "List",
    "LocalDfnRegistry",
    "MemoryArray",
    "MemoryScalar",
    "MemoryVariable",
    "MemoryVariableBase",
    "Model",
    "Package",
    "Record",
    "RemoteDfnRegistry",
    "RuntimeDim",
    "Scalar",
    "ShapeRef",
    "Simulation",
    "String",
    "Union",
    "evaluate_dim",
    "fetch_dfns",
    "migrate",
    "parse_shape_element",
    "split_bound",
]
