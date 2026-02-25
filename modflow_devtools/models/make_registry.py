import argparse
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import modflow_devtools.models as models
from modflow_devtools.download import download_and_unzip

_REPOS_PATH = Path(__file__).parents[2]


def _download_repo(repo: str, ref: str, verbose: bool = False) -> Path:
    """
    Download a GitHub repository at the specified ref to a temporary directory.

    Parameters
    ----------
    repo : str
        Repository in "owner/name" format
    ref : str
        Git ref (branch, tag, or commit hash)
    verbose : bool
        Print progress messages

    Returns
    -------
    Path
        Path to the extracted repository root directory
    """
    # Use GitHub's archive API to download zipball
    url = f"https://api.github.com/repos/{repo}/zipball/{ref}"

    if verbose:
        print(f"Downloading {repo}@{ref} from {url}")

    # Download to temporary file
    temp_dir = Path(tempfile.mkdtemp(prefix="modflow-devtools-"))
    zip_path = temp_dir / "repo.zip"

    try:
        with urlopen(url) as response:
            with zip_path.open("wb") as f:
                f.write(response.read())

        if verbose:
            print(f"Downloaded to {zip_path}")

        # Extract the zipfile
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()

        with ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        # GitHub zipballs have a single top-level directory named {owner}-{repo}-{short_sha}
        # Find it and return its path
        subdirs = list(extract_dir.iterdir())
        if len(subdirs) != 1:
            raise RuntimeError(
                f"Expected single directory in archive, found {len(subdirs)}: {subdirs}"
            )

        repo_root = subdirs[0]

        if verbose:
            print(f"Extracted to {repo_root}")

        return repo_root

    except Exception as e:
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to download repository {repo}@{ref}: {e}") from e


_DEFAULT_REGISTRY_OPTIONS = [
    {
        "path": _REPOS_PATH / "modflow6-examples" / "examples",
        "url": "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip",
        "model-name-prefix": "mf6/example",
    },
    {
        "path": _REPOS_PATH / "modflow6-testmodels" / "mf6",
        "url": "https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6",
        "model-name-prefix": "mf6/test",
    },
    {
        "path": _REPOS_PATH / "modflow6-largetestmodels",
        "url": "https://github.com/MODFLOW-ORG/modflow6-largetestmodels/raw/master",
        "model-name-prefix": "mf6/large",
    },
    {
        "path": _REPOS_PATH / "modflow6-testmodels" / "mf5to6",
        "url": "https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf5to6",
        "model-name-prefix": "mf2005",
        "namefile": "*.nam",
    },
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Make a registry of models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Version-controlled models - downloads from remote and indexes subdirectory
  python -m modflow_devtools.models.make_registry \\
    --repo MODFLOW-ORG/modflow6-testmodels \\
    --ref master \\
    --name mf6/test \\
    --path mf6 \\
    --output .registry

  # Release asset models - automatically detected via --asset-file
  python -m modflow_devtools.models.make_registry \\
    --repo MODFLOW-ORG/modflow6-examples \\
    --ref current \\
    --asset-file mf6examples.zip \\
    --name mf6/example \\
    --output .registry

  # No path - downloads and indexes entire repo root
  python -m modflow_devtools.models.make_registry \\
    --repo MODFLOW-ORG/modflow6-testmodels \\
    --ref master \\
    --name mf6/test \\
    --output .registry

  # Using local checkout (if /path/to/... exists locally)
  python -m modflow_devtools.models.make_registry \\
    --path /path/to/modflow6-testmodels/mf6 \\
    --repo MODFLOW-ORG/modflow6-testmodels \\
    --ref master \\
    --name mf6/test \\
    --output .registry
""",
    )
    parser.add_argument(
        "--path",
        "-p",
        required=False,
        default=None,
        type=str,
        help=(
            "Path to model directory. Can be: "
            "(1) An existing local directory - uses local checkout (for testing); "
            "(2) A relative path like 'mf6' - downloads repo and uses as subdirectory; "
            "(3) Omitted - downloads repo and indexes from root. "
            "Remote-first (options 2-3) is recommended for production."
        ),
    )
    parser.add_argument(
        "--name",
        required=True,
        type=str,
        help=(
            "Model name prefix - must match the 'name' field in "
            "bootstrap sources (e.g., 'mf6/test', 'mf6/example')."
        ),
    )

    parser.add_argument(
        "--repo",
        required=True,
        type=str,
        help=('Repository in "owner/name" format (e.g., MODFLOW-ORG/modflow6-testmodels).'),
    )
    parser.add_argument(
        "--ref",
        required=True,
        type=str,
        help="Git ref (branch, tag, or commit hash).",
    )
    parser.add_argument(
        "--asset-file",
        type=str,
        help=(
            "Release asset filename (e.g., mf6examples.zip). "
            "If provided, models are indexed from the release asset "
            "instead of version-controlled files."
        ),
    )
    parser.add_argument(
        "--namefile",
        "-n",
        type=str,
        help="Namefile pattern to look for in the model directories.",
        default="mfsim.nam",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output directory for registry file(s). Defaults to current working directory.",
        default=".",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output.",
    )
    args = parser.parse_args()

    # Infer mode from presence of --asset-file
    mode = "release" if args.asset_file else "version"

    # Determine the local path to index
    temp_dir = None
    index_path = None
    path_in_repo = ""  # For URL construction
    use_local_path = False

    try:
        if args.path:
            # Check if it's an existing local directory
            path_obj = Path(args.path)
            if path_obj.exists() and path_obj.is_dir():
                # It's a local path - use directly
                index_path = args.path
                use_local_path = True
                if args.verbose:
                    print(f"Using local directory: {index_path}")
                    print(
                        "Warning: Using local path may not match remote state. "
                        "For production, use a subpath (e.g., 'mf6') to download from remote."
                    )
            else:
                # Path doesn't exist locally - need to download
                # For release mode, download the asset; for version mode, download repo
                if mode == "release":
                    # Download release asset
                    if not args.asset_file:
                        parser.error(
                            "--asset-file is required when mode=release and path not found locally"
                        )

                    asset_url = f"https://github.com/{args.repo}/releases/download/{args.ref}/{args.asset_file}"

                    if args.verbose:
                        print(f"Path '{args.path}' not found locally")
                        print("Downloading and extracting release asset for indexing...")

                    # Create temp directory and download/extract
                    temp_dir = Path(tempfile.mkdtemp(prefix="modflow-devtools-"))
                    extract_dir = download_and_unzip(
                        asset_url, path=temp_dir, delete_zip=True, verbose=args.verbose
                    )

                    # The release asset may have files at root or in a subdirectory
                    # Check if the specified path exists within the extracted content
                    if (extract_dir / args.path).exists():
                        index_path = extract_dir / args.path
                    else:
                        # Path not found as subdirectory, maybe it's at root
                        index_path = extract_dir

                    if args.verbose:
                        print(f"Will index from: {index_path}")
                else:
                    # Version mode - download repository
                    if args.verbose:
                        print(
                            f"Path '{args.path}' not found locally, "
                            f"treating as subpath in remote..."
                        )
                        print("Downloading from remote...")

                    repo_root = _download_repo(args.repo, args.ref, verbose=args.verbose)
                    temp_dir = repo_root.parent.parent

                    index_path = repo_root / args.path
                    if not index_path.exists():
                        raise RuntimeError(
                            f"Subpath '{args.path}' not found in downloaded repository"
                        )
                    path_in_repo = args.path

                    if args.verbose:
                        print(f"Will index from: {index_path}")
        else:
            # No path provided
            if mode == "release":
                # Download release asset and extract to temp directory
                if not args.asset_file:
                    parser.error("--asset-file is required when mode=release")

                asset_url = (
                    f"https://github.com/{args.repo}/releases/download/{args.ref}/{args.asset_file}"
                )

                if args.verbose:
                    print(
                        "No path provided, downloading and extracting release asset from remote..."
                    )

                # Create temp directory and download/extract
                temp_dir = Path(tempfile.mkdtemp(prefix="modflow-devtools-"))
                index_path = download_and_unzip(
                    asset_url, path=temp_dir, delete_zip=True, verbose=args.verbose
                )

                if args.verbose:
                    print(f"Will index from: {index_path}")
            else:
                # Version mode - download entire repository
                if args.verbose:
                    print("No path provided, downloading entire repository from remote...")

                repo_root = _download_repo(args.repo, args.ref, verbose=args.verbose)
                temp_dir = repo_root.parent.parent
                index_path = repo_root

                if args.verbose:
                    print(f"Will index from repo root: {index_path}")

        # Validate arguments and construct URL
        if mode == "version":
            # If using local path, try to auto-detect path in repo from directory structure
            if use_local_path:
                path_obj = Path(index_path).resolve()
                # Extract repository name from owner/repo format
                repo_name = args.repo.split("/")[1]

                # Look for the repo name in the path
                path_parts = path_obj.parts
                try:
                    # Find the index of the repo name in the path
                    repo_index = path_parts.index(repo_name)
                    # Everything after the repo name is the path in repo
                    if repo_index + 1 < len(path_parts):
                        remaining_parts = path_parts[repo_index + 1 :]
                        path_in_repo = "/".join(remaining_parts)
                        if args.verbose:
                            print(
                                f"Detected path in repo: '{path_in_repo}' "
                                "(from directory structure)"
                            )
                    else:
                        # Path ends at repo name, so we're at repo root
                        if args.verbose:
                            print("Detected path in repo: '' (repo root)")
                except ValueError:
                    # Repo name not found in path - assume repo root
                    if args.verbose:
                        print(
                            f"Warning: Repository name '{repo_name}' not found in path, "
                            "using repo root"
                        )

            # Construct raw GitHub URL for version-controlled files
            path_suffix = f"/{path_in_repo}" if path_in_repo else ""
            url = f"https://raw.githubusercontent.com/{args.repo}/{args.ref}{path_suffix}"
            if args.verbose:
                print("Mode: version (version-controlled)")
                print(f"Constructed URL: {url}")

        elif mode == "release":
            # Construct release download URL for release assets
            if not args.asset_file:
                parser.error("--asset-file is required when mode=release")
            url = f"https://github.com/{args.repo}/releases/download/{args.ref}/{args.asset_file}"
            if args.verbose:
                print("Mode: release (release asset)")
                print(f"Constructed URL: {url}")

        # Index the models
        if args.verbose:
            print(f"Adding {index_path} to the registry.")
            if args.output:
                print(f"Output directory: {args.output}")

        models.get_default_registry().index(
            path=index_path,
            url=url,
            prefix=args.name,
            namefile=args.namefile,
            output_path=args.output,
        )

        if args.verbose:
            print("Registry generation complete!")

    finally:
        # Clean up temporary directory if we downloaded
        if temp_dir and temp_dir.exists():
            if args.verbose:
                print(f"Cleaning up temporary directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
