from os import PathLike
from pathlib import Path
from subprocess import run


def meson_build(
    project_path: PathLike,
    build_path: PathLike,
    bin_path: PathLike,
):
    project_path = Path(project_path).expanduser().resolve()
    build_path = Path(build_path).expanduser().resolve()
    bin_path = Path(bin_path).expanduser().resolve()

    # meson setup
    args = [
        "meson",
        "setup",
        str(build_path),
        f"--bindir={bin_path}",
        f"--libdir={bin_path}",
        f"--prefix={Path.cwd()}",
    ]
    if build_path.is_dir():
        args.append("--wipe")

    print("Running command: " + " ".join(args))
    run(args, check=True, cwd=project_path)

    # meson compile
    args = ["meson", "compile", "-C", str(build_path)]
    print("Running command: " + " ".join(args))
    run(args, check=True, cwd=project_path)

    # meson install
    args = ["meson", "install", "-C", str(build_path)]
    print("Running command: " + " ".join(args))
    run(args, check=True, cwd=project_path)
