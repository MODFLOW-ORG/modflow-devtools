"""
MODFLOW 6, Python3, and GitHub Actions refer to operating
systems differently. This module contains conversion utilities.
"""

import sys
from platform import processor, system

_system = system()
_processor = processor()

SUPPORTED_OSTAGS = ["linux", "mac", "macarm", "win32", "win64"]


def get_modflow_ostag() -> str:
    if _system == "Windows":
        return "win" + ("64" if sys.maxsize > 2**32 else "32")
    elif _system == "Linux":
        return "linux"
    elif _system == "Darwin":
        return "macarm" if _processor == "arm" else "mac"
    else:
        raise NotImplementedError(f"Unsupported system: {_system}")


def get_github_ostag() -> str:
    if _system in ("Windows", "Linux"):
        return _system
    elif _system == "Darwin":
        return "macOS"
    else:
        raise NotImplementedError(f"Unsupported system: {_system}")


def get_ostag(kind: str = "modflow") -> str:
    if kind == "modflow":
        return get_modflow_ostag()
    elif kind == "github":
        return get_github_ostag()
    else:
        raise ValueError(f"Invalid kind: {kind}")


def get_binary_suffixes(ostag: str | None = None) -> tuple[str, str]:
    """
    Returns executable and library suffixes for the given OS tag, if provided,
    otherwise for the current operating system.

    Parameters
    ----------
    ostag : str, optional
        The OS tag. May be provided in modflow, python, or github format.

    Returns
    -------
    Tuple[str, str]
        The executable and library suffixes, respectively.
    """

    if ostag is None:
        ostag = get_modflow_ostag()

    def _suffixes(tag):
        if tag in ["win32", "win64"]:
            return ".exe", ".dll"
        elif tag == "linux":
            return "", ".so"
        elif tag == "darwin" or "mac" in tag:
            return "", ".dylib"
        else:
            raise KeyError(f"Invalid OS tag: {tag!r}")

    try:
        return _suffixes(ostag.lower())
    except KeyError:
        try:
            return _suffixes(python_to_modflow_ostag(ostag))
        except KeyError:
            return _suffixes(github_to_modflow_ostag(ostag))


def python_to_modflow_ostag(tag: str) -> str:
    """
    Convert a platform.system() string to an ostag as expected
    by MODFLOW 6.

    Parameters
    ----------
    platform_system : str
        The platform.system() string.

    Returns
    -------
    str
    """

    if tag == "Windows":
        return "win64"
    elif tag == "Linux":
        return "linux"
    elif tag == "Darwin":
        return "macarm" if _processor == "arm" else "mac"
    else:
        raise ValueError(f"Invalid tag: {tag}")


def modflow_to_python_ostag(tag: str) -> str:
    """
    Convert a MODFLOW os tag to a platform.system() string.

    Parameters
    ----------
    tag : str
        The MODFLOW os tag.

    Returns
    -------
    str
    """

    if tag == "win64":
        return "Windows"
    elif tag == "linux":
        return "Linux"
    elif "mac" in tag:
        return "Darwin"
    else:
        raise ValueError(f"Invalid tag: {tag}")


def modflow_to_github_ostag(tag: str) -> str:
    if tag == "win64":
        return "Windows"
    elif tag == "linux":
        return "Linux"
    elif "mac" in tag:
        return "macOS"
    else:
        raise ValueError(f"Invalid modflow os tag: {tag}")


def github_to_modflow_ostag(tag: str) -> str:
    if tag == "Windows":
        return "win64"
    elif tag == "Linux":
        return "linux"
    elif tag == "macOS":
        return "macarm" if _processor == "arm" else "mac"
    else:
        raise ValueError(f"Invalid github os tag: {tag}")


def python_to_github_ostag(tag: str) -> str:
    return modflow_to_github_ostag(python_to_modflow_ostag(tag))


def github_to_python_ostag(tag: str) -> str:
    return modflow_to_python_ostag(github_to_modflow_ostag(tag))


def convert_ostag(tag: str, mapping: str) -> str:
    if mapping == "py2mf":
        return python_to_modflow_ostag(tag)
    elif mapping == "mf2py":
        return modflow_to_python_ostag(tag)
    elif mapping == "gh2mf":
        return github_to_modflow_ostag(tag)
    elif mapping == "mf2gh":
        return modflow_to_github_ostag(tag)
    elif mapping == "py2gh":
        return python_to_github_ostag(tag)
    elif mapping == "gh2py":
        return github_to_python_ostag(tag)
    else:
        raise ValueError(f"Invalid mapping: {mapping}")
