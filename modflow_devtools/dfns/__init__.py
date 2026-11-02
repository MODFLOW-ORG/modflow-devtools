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
    CellID,
    Component,
    Dfns,
    Double,
    File,
    ForeignKey,
    InputDim,
    InputField,
    InputFieldBase,
    Integer,
    KeySet,
    Keyword,
    List,
    MemoryArray,
    MemoryScalar,
    MemoryVariable,
    MemoryVariableBase,
    Model,
    Package,
    PrimaryKey,
    Provide,
    Record,
    RuntimeDim,
    Scalar,
    Simulation,
    String,
    Union,
    dim_input,
    dim_value,
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
    "CellID",
    "Component",
    "DfnRegistry",
    "Dfns",
    "Double",
    "FieldType",
    "File",
    "ForeignKey",
    "InputDim",
    "InputField",
    "InputFieldBase",
    "Integer",
    "KeySet",
    "Keyword",
    "List",
    "LocalDfnRegistry",
    "MemoryArray",
    "MemoryScalar",
    "MemoryVariable",
    "MemoryVariableBase",
    "Model",
    "Package",
    "PrimaryKey",
    "Provide",
    "Record",
    "RemoteDfnRegistry",
    "RuntimeDim",
    "Scalar",
    "Simulation",
    "String",
    "Union",
    "dim_input",
    "dim_value",
    "fetch_dfns",
    "migrate",
    "split_bound",
]
