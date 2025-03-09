import argparse
import hashlib
from pathlib import Path

import tomli_w as tomli

from modflow_devtools.misc import get_model_paths
from modflow_devtools.models import BASE_URL, DATA_PATH

REGISTRY_PATH = DATA_PATH / "registry.txt"


def _sha256(path: Path) -> str:
    """
    Compute the SHA256 hash of the given file.
    Reference: https://stackoverflow.com/a/44873382/6514033
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with path.open("rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


def write_registry(
    path: Path, registry_path: Path, base_url: str, append: bool = False
):
    if not registry_path.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)

    models: dict[str, list[str]] = {}
    exclude = [".DS_Store"]
    with registry_path.open("a+" if append else "w") as f:
        if not path.is_dir():
            raise NotADirectoryError(f"Path {path} is not a directory.")
        for mp in get_model_paths(path):
            for p in mp.rglob("*"):
                if "compare" in str(p):
                    continue
                if p.is_file() and not any(e in p.name for e in exclude):
                    relpath = p.relative_to(path)
                    name = str(relpath).replace("/", "_").replace("-", "_")
                    hash = _sha256(p)
                    url = f"{base_url}/{relpath!s}"
                    line = f"{name} {hash} {url}"
                    f.write(line + "\n")
                    key = str(relpath.parent).replace("/", "_").replace("-", "_")
                    if key not in models:
                        models[key] = []
                    models[key].append(name)

    models_path = registry_path.parent / "models.toml"
    with models_path.open("ab+" if append else "wb") as mf:
        tomli.dump(dict(sorted(models.items())), mf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert DFN files to TOML.")
    parser.add_argument(
        "--path",
        "-p",
        type=str,
        help="Directory containing model directories.",
    )
    parser.add_argument(
        "--append",
        "-a",
        action="store_true",
        help="Append to the registry file instead of overwriting.",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        type=str,
        help="Base URL for the registry file.",
    )
    args = parser.parse_args()
    path = Path(args.path) if args.path else DATA_PATH
    base_url = args.base_url if args.base_url else BASE_URL
    write_registry(path, REGISTRY_PATH, base_url, args.append)
