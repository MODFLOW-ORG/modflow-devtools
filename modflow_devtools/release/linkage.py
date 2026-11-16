"""
Check that the binaries in a directory will run on users' machines.

Every executable and shared library found (recursively, by file format) may
link only libraries the operating system provides, so the compiler runtimes
must be linked statically. Also:

- Linux: no symbol may need a glibc newer than MAX_GLIBC (RHEL 9's).
- macOS: binaries must be arm64 and run on MACOS_MIN or newer. Set
  MACOSX_DEPLOYMENT_TARGET when building; the setup action does.

Dependencies are read with objdump on Linux and Windows (falling back to
dumpbin on Windows), and with otool on macOS. The check fails if it finds no
binaries, or if a tool fails or reports nothing, rather than passing without
checking.
"""

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from modflow_devtools.release import ci

MAX_GLIBC = (2, 34)
MACOS_MIN = (14, 0)
MACOS_ARCH = "arm64"

# libraries every system has; anything else must be linked statically
LINUX_LIBS = re.compile(
    r"^(linux-vdso|linux-gate|ld-linux[\w.-]*|libc|libm|libdl|libpthread|librt)\.so",
)
MACOS_LIBS = re.compile(r"^(/usr/lib/|/System/Library/)")
WINDOWS_LIBS = re.compile(
    r"^(kernel32|user32|gdi32|advapi32|shell32|ole32|oleaut32|ws2_32|bcrypt|ntdll"
    r"|msvcrt|ucrtbase|api-ms-win-[\w.-]+)\.dll$",
    re.I,
)

ELF = b"\x7fELF"
MACHO = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",  # universal
}
PE = b"MZ"


def system():
    return {"Darwin": "macos"}.get(platform.system(), platform.system().lower())


def is_binary(path, os_):
    with path.open("rb") as f:
        magic = f.read(4)
    if os_ == "linux":
        return magic == ELF
    if os_ == "macos":
        return magic in MACHO
    return magic[:2] == PE


def binaries(root, os_):
    return sorted(p for p in Path(root).rglob("*") if p.is_file() and is_binary(p, os_))


def version_tuple(text):
    return tuple(int(n) for n in text.split("."))


def version_str(v):
    return ".".join(map(str, v))


# parsers, separate from running the tools so they can be tested on samples


def parse_objdump_elf(text):
    """(dynamic, needed libraries, glibc versions) from ``objdump -p``."""
    dynamic = "Dynamic Section:" in text
    needed = re.findall(r"^\s*NEEDED\s+(\S+)", text, re.M)
    glibc = {version_tuple(v) for v in re.findall(r"\bGLIBC_(\d+(?:\.\d+)+)\b", text)}
    return dynamic, needed, glibc


def parse_objdump_pe(text):
    """DLLs from ``objdump -p``."""
    return re.findall(r"^\s*DLL Name:\s*(\S+)", text, re.M)


def parse_dumpbin(text):
    """DLLs from ``dumpbin /dependents``."""
    return re.findall(r"^\s+(\S+\.dll)\s*$", text, re.M | re.I)


def parse_otool_L(text, dylib=False):
    """Libraries from ``otool -L``. A dylib's first entry is its own name."""
    libs = re.findall(r"^\s+(\S.*?) \(compatibility version", text, re.M)
    return libs[1:] if dylib else libs


def parse_otool_l(text):
    """The minimum macOS version from ``otool -l``, or None."""
    if m := re.search(r"cmd LC_BUILD_VERSION\b.*?^\s*minos (\d+(?:\.\d+)*)", text, re.M | re.S):
        return version_tuple(m.group(1))
    if m := re.search(
        r"cmd LC_VERSION_MIN_MACOSX\b.*?^\s*version (\d+(?:\.\d+)*)", text, re.M | re.S
    ):
        return version_tuple(m.group(1))
    return None


# checks, returning a list of problems


def check_linux(text):
    dynamic, needed, glibc = parse_objdump_elf(text)
    if not dynamic:
        return []  # fully static
    if not needed:
        return ["objdump lists no libraries"]
    problems = [f"links {lib}" for lib in needed if not LINUX_LIBS.match(lib)]
    if glibc and max(glibc) > MAX_GLIBC:
        problems.append(
            f"needs glibc {version_str(max(glibc))}, newer than {version_str(MAX_GLIBC)}"
        )
    return problems


def check_macos(libs, archs, minos):
    if not libs:
        return ["otool lists no libraries"]
    problems = [f"links {lib}" for lib in libs if not MACOS_LIBS.match(lib)]
    if MACOS_ARCH not in archs:
        problems.append(f"is built for {' '.join(archs) or 'no known architecture'}, not arm64")
    if minos is None:
        problems.append("has no minimum macOS version")
    elif minos > MACOS_MIN:
        problems.append(
            f"needs macOS {version_str(minos)}, newer than {version_str(MACOS_MIN)}; "
            f"set MACOSX_DEPLOYMENT_TARGET={version_str(MACOS_MIN)}"
        )
    return problems


def check_windows(dlls):
    if not dlls:
        return ["lists no DLLs"]
    return [f"links {dll}" for dll in dlls if not WINDOWS_LIBS.match(dll)]


# running the tools


def tool(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return result.stdout


def inspect(path, os_):
    """What the tools report for one file, and the problems found."""
    p = str(path)
    if os_ == "linux":
        text = tool(["objdump", "-p", p])
        return text, check_linux(text)
    if os_ == "macos":
        text = tool(["otool", "-L", p])
        libs = parse_otool_L(text, dylib=path.suffix == ".dylib")
        archs = tool(["lipo", "-archs", p]).split()
        minos = parse_otool_l(tool(["otool", "-l", p]))
        report = f"{text.strip()}\narchitectures: {' '.join(archs)}"
        report += f"\nminimum macOS: {version_str(minos) if minos else 'unknown'}"
        return report, check_macos(libs, archs, minos)
    if shutil.which("objdump"):
        dlls = parse_objdump_pe(tool(["objdump", "-p", p]))
    elif shutil.which("dumpbin"):
        dlls = parse_dumpbin(tool(["dumpbin", "/dependents", p]))
    else:
        raise RuntimeError("neither objdump nor dumpbin found")
    return "\n".join(dlls), check_windows(dlls)


def check(root, os_=None):
    """Check every binary under root, reporting each. True if all pass."""
    os_ = os_ or system()
    files = binaries(root, os_)
    if not files:
        ci.error(f"no {os_} binaries found in {root}")
        return False
    ok = True
    for path in files:
        name = path.relative_to(root).as_posix()
        try:
            report, problems = inspect(path, os_)
        except (OSError, RuntimeError) as e:
            report, problems = "", [str(e)]
        with ci.group(name):
            print(report, flush=True)
        for problem in problems:
            ci.error(f"{name} {problem}")
            ok = False
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path("bin"))
    args = parser.parse_args(argv)
    return 0 if check(args.path.resolve()) else 1


if __name__ == "__main__":
    sys.exit(main())
