from os import PathLike
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory

from modflow_devtools.download import download_and_unzip


def fetch_dfns(
    owner: str, repo: str, ref: str, outdir: str | PathLike, verbose: bool = False
):
    """Fetch definition files from the MODFLOW 6 repository."""
    url = f"https://github.com/{owner}/{repo}/archive/{ref}.zip"
    if verbose:
        print(f"Downloading MODFLOW 6 repository archive from {url}")
    with TemporaryDirectory() as tmp:
        dl_path = download_and_unzip(url, Path(tmp), verbose=verbose)
        contents = list(dl_path.glob("modflow6-*"))
        proj_path = next(iter(contents), None)
        if not proj_path:
            raise ValueError(f"Missing proj dir in {dl_path}, found {contents}")
        if verbose:
            print("Copying dfns from download dir to output dir")
        copytree(
            proj_path / "doc" / "mf6io" / "mf6ivar" / "dfn", outdir, dirs_exist_ok=True
        )


get_dfns = fetch_dfns  # alias for backward compatibility


def fetch_versioned_path(verbose: bool = True):
    import tempfile

    from modflow_devtools.dfn2toml import convert

    MF6_OWNER = "MODFLOW-ORG"
    MF6_REPO = "modflow6"
    MF6_REF = "develop"

    """Fetch definition files from the MODFLOW 6 repository."""
    url = f"https://github.com/{MF6_OWNER}/{MF6_REPO}/archive/{MF6_REF}.zip"
    systmp = tempfile.gettempdir()
    if verbose:
        print(f"Downloading MODFLOW 6 repository archive from {url}")
    with TemporaryDirectory() as tmp:
        dl_path = download_and_unzip(url, Path(tmp), verbose=verbose)
        contents = list(dl_path.glob("modflow6-*"))
        proj_path = next(iter(contents), None)
        if not proj_path:
            raise ValueError(f"Missing proj dir in {dl_path}, found {contents}")
        vpath = proj_path / "version.txt"
        with vpath.open("r") as f:
            version = f.read()
        spec_path = Path(systmp) / "modflow6" / f"{version}"
        if verbose:
            print(f"Specification path set to f{spec_path}")
        dfn_path = spec_path / "dfn"
        toml_path = spec_path / "toml"
        if verbose:
            print("Copying dfns from download dir to output dfn dir")
        copytree(
            proj_path / "doc" / "mf6io" / "mf6ivar" / "dfn",
            dfn_path,
            dirs_exist_ok=True,
        )
        if verbose:
            print("Converting dfns from output dfn dir to output toml dir")
        convert(dfn_path, toml_path)
        return spec_path
