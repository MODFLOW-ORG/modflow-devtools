"""Utilities for accessing the program database"""

from csv import DictReader
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from modflow_devtools.misc import try_literal_eval

DB_NAME = "programs.csv"
DB_PATH = Path(__file__).parent / DB_NAME


@dataclass
class Program:
    target: str
    version: str
    current: bool
    url: str
    dirname: str
    srcdir: str
    standard_switch: bool
    double_switch: bool
    shared_object: bool

    @classmethod
    def from_dict(cls, d: dict, strict: bool = False) -> "Program":
        """
        Create a Program instance from a dictionary.

        Parameters
        ----------
        d : dict
            Dictionary containing program data
        strict : bool, optional
            If True, raise ValueError if dict contains unrecognized keys.
            If False (default), ignore unrecognized keys.
        """
        keys = set(cls.__annotations__.keys())
        if strict:
            dkeys = {k.strip() for k in d.keys()}
            if extra_keys := dkeys - keys:
                raise ValueError(f"Unrecognized keys in program data: {extra_keys}")
        return cls(
            **{k.strip(): try_literal_eval(v.strip()) for k, v in d.items() if k.strip() in keys}
        )


def load_programs(path: str | PathLike, strict: bool = False) -> dict[str, Program]:
    """Load the program database from the CSV file."""

    path = Path(path).expanduser().resolve()
    with path.open() as csvfile:
        # assumes the first row is the header!
        reader = DictReader(csvfile, skipinitialspace=True)
        programs = [Program.from_dict(row, strict) for row in reader]
        return {program.target: program for program in programs}


PROGRAMS = load_programs(DB_PATH, strict=True)


def get_programs() -> dict[str, Program]:
    """Get the program database."""
    return PROGRAMS


def get_program(name: str) -> Program:
    """Get a specific program by name."""
    return PROGRAMS[name]
