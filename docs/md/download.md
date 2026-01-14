# Web utilities 

Some utility functions are provided for GitHub-related web requests. See this project's test cases (in particular `test_download.py`) for detailed usage examples.

**Note:** to avoid GitHub API rate limits when using these functions, it is recommended to set the `GITHUB_TOKEN` environment variable. If this variable is set, the token will be borne on requests sent to the API.

## Queries

The following functions ask the GitHub API for information about a repository. The singular functions generally return a dictionary, while the plural functions return a list of dictionaries, with dictionary contents parsed directly from the API response's JSON. The first parameter of each function is `repo`, a string whose format must be `owner/name`, as appearing in GitHub URLs.

For instance, to retrieve information about the latest executables release, then manually inspect available assets:

```python
from modflow_devtools.download import get_release

release = get_release("MODFLOW-ORG/executables")
assets = release["assets"]
print([asset["name"] for asset in assets])
```

This prints `['code.json', 'linux.zip', 'macarm.zip', 'win64.zip']`.

## Downloads

The `download_and_unzip` function downloads and unzips zip files.

For instance, to download a MODFLOW 6.4.1 Linux distribution and delete the zipfile after extracting:

```python
from modflow_devtools.download import download_and_unzip

url = f"https://github.com/MODFLOW-ORG/modflow6/releases/download/6.4.1/mf6.4.1_linux.zip"
download_and_unzip(url, "~/Downloads", delete_zip=True, verbose=True)
```

The function's return value is the `Path` the archive was extracted to.