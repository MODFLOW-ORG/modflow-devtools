from dataclasses import dataclass
from typing import Literal

from modflow_devtools.dfn.schema.field import Field

FieldType = Literal[
    "keyword", "integer", "double", "string", "array", "record", "union"
]


@dataclass(kw_only=True)
class FieldV2(Field):
    pass

    @classmethod
    def from_dict(cls, d: dict) -> "FieldV2":
        """Create a FieldV2 instance from a dictionary."""
        keys = list(cls.__annotations__.keys()) + list(Field.__annotations__.keys())
        return cls(**{k: v for k, v in d.items() if k in keys})
