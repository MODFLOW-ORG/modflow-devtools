import argparse
import textwrap
from datetime import datetime
from pathlib import Path

from filelock import FileLock
from packaging.version import Version

_project_name = "modflow-devtools"
_project_root_path = Path(__file__).parent.parent
_version_txt_path = _project_root_path / "version.txt"
_package_init_path = _project_root_path / "modflow_devtools" / "__init__.py"
_docs_config_path = _project_root_path / "docs" / "conf.py"
_current_version = Version(_version_txt_path.read_text().strip())


def update_version_txt(version: Version):
    _version_txt_path.write_text(str(version))
    print(f"Updated {_version_txt_path} to version {version}")


def update_init_py(timestamp: datetime, version: Version):
    lines = []
    for line in _package_init_path.read_text().splitlines():
        if "__date__" in line:
            line = f'__date__ = "{timestamp:%b %d, %Y}"'
        if "__version__" in line:
            line = f'__version__ = "{version}"'
        lines.append(line)
    _package_init_path.write_text("\n".join(lines) + "\n")
    print(f"Updated {_package_init_path} to version {version}")


def update_docs_config(version: Version):
    lines = []
    for line in _docs_config_path.read_text().splitlines():
        if "release = " in line:
            line = f'release = "{version}"'
        lines.append(line)
    _docs_config_path.write_text("\n".join(lines) + "\n")
    print(f"Updated {_docs_config_path} to version {version}")


def update_version(
    timestamp: datetime = datetime.now(),
    version: Version | None = None,
):
    lock_path = Path(_version_txt_path.name + ".lock")
    lock = FileLock(lock_path)
    with lock:
        previous = Version(_version_txt_path.read_text().strip())
        version = (
            version if version else Version(f"{previous.major}.{previous.minor}.{previous.micro}")
        )

        update_version_txt(version)
        update_init_py(timestamp, version)
        update_docs_config(version)

    lock_path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog=f"Update {_project_name} version",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Update version information stored in version.txt in the project root,
            as well as several other files in the repository. If --version is not
            provided, the version number will not be changed. A file lock is held
            to synchronize file access. The version tag must comply with standard
            '<major>.<minor>.<patch>' format conventions for semantic versioning.
            """
        ),
    )
    parser.add_argument(
        "-v",
        "--version",
        required=False,
        help="Specify the release version",
    )
    parser.add_argument(
        "-g",
        "--get",
        required=False,
        action="store_true",
        help="Just get the current version number, don't update anything (defaults to false)",
    )
    args = parser.parse_args()

    if args.get:
        print(Version(_version_txt_path.read_text().strip()))
    else:
        update_version(
            timestamp=datetime.now(),
            version=(Version(args.version) if args.version else _current_version),
        )
