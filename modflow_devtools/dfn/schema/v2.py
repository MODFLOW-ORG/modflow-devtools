from dataclasses import dataclass
from typing import Literal

from modflow_devtools.dfn.schema.field import Field

FieldType = Literal["keyword", "integer", "double", "string", "record", "array", "list"]

SCALAR_TYPES = ("keyword", "integer", "double", "string")


@dataclass(kw_only=True)
class FieldV2(Field):
    pass

    @classmethod
    def from_dict(cls, d: dict, strict: bool = False) -> "FieldV2":
        """
        Create a FieldV2 instance from a dictionary.

        Parameters
        ----------
        d : dict
            Dictionary containing field data
        strict : bool, optional
            If True, raise ValueError if dict contains unrecognized keys.
            If False (default), ignore unrecognized keys.
        """
        keys = set(list(cls.__annotations__.keys()) + list(Field.__annotations__.keys()))
        if strict:
            if extra_keys := set(d.keys()) - keys:
                raise ValueError(f"Unrecognized keys in field data: {extra_keys}")
        return cls(**{k: v for k, v in d.items() if k in keys})
