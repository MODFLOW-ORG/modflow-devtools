from dataclasses import dataclass

from modflow_devtools.dfn.schema.field import Field


@dataclass(kw_only=True)
class FieldV1(Field):
    valid: tuple[str, ...] | None = None
    tagged: bool | None = None
    in_record: bool | None = None
    layered: bool | None = None
    longname: str | None = None
    preserve_case: bool | None = None
    numeric_index: bool | None = None
    deprecated: bool = False
    removed: bool = False
    mf6internal: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "FieldV1":
        """Create a FieldV1 instance from a dictionary."""
        keys = list(cls.__annotations__.keys()) + list(Field.__annotations__.keys())
        return cls(**{k: v for k, v in d.items() if k in keys})
