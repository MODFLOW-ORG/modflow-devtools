from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

SCALAR_TYPES = ("keyword", "integer", "double precision", "string")

Fields = Mapping[str, "Field"]

FieldType = Literal[
    "keyword",
    "integer",
    "double precision",
    "string",
    "record",
    "recarray",
    "keystring",
]


Reader = Literal[
    "urword",
    "u1ddbl",
    "u2ddbl",
    "readarray",
]


@dataclass(kw_only=True)
class Field:
    name: str
    type: str | None = None
    block: str | None = None
    default: Any | None = None
    longname: str | None = None
    description: str | None = None
    children: Fields | None = None
    optional: bool | None = None
    developmode: bool = False
    reader: Reader = "urword"
    shape: str | None = None
    valid: tuple[str, ...] | None = None
