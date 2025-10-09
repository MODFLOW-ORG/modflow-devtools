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
