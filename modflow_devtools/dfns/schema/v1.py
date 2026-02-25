from dataclasses import dataclass
from typing import Literal

from modflow_devtools.dfns.schema.field import Field

FieldType = Literal[
    "keyword",
    "integer",
    "double precision",
    "string",
    "record",
    "recarray",
    "keystring",
]

SCALAR_TYPES = ("keyword", "integer", "double precision", "string")


Reader = Literal[
    "urword",
    "u1ddbl",
    "u2ddbl",
    "readarray",
]


@dataclass(kw_only=True)
class FieldV1(Field):
    valid: tuple[str, ...] | None = None
    reader: Reader = "urword"
    tagged: bool = False
    in_record: bool = False
    layered: bool | None = None
    preserve_case: bool = False
    numeric_index: bool = False
    deprecated: bool = False
    removed: bool = False
    mf6internal: str | None = None
    block_variable: bool = False
    just_data: bool = False
    time_series: bool = False

    @classmethod
    def from_dict(cls, d: dict, strict: bool = False) -> "FieldV1":
        """
        Create a FieldV1 instance from a dictionary.

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
