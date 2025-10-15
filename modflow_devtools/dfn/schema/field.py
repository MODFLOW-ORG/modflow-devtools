from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCALAR_TYPES = ("keyword", "integer", "double precision", "string")

Fields = Mapping[str, "Field"]


@dataclass(kw_only=True)
class Field:
    name: str
    type: str | None = None
    block: str | None = None
    default: Any | None = None
    longname: str | None = None
    description: str | None = None
    children: Fields | None = None
    optional: bool = False
    developmode: bool = False
    shape: str | None = None
    valid: tuple[str, ...] | None = None
