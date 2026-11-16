"""
Messages from the release modules. In GitHub Actions they're workflow
commands, so errors and notices are annotated on the run and groups fold in
the log; elsewhere they're plain text.
"""

import os
import sys
from contextlib import contextmanager


def github():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def error(message):
    if github():
        print(f"::error::{message}", flush=True)
    else:
        print(f"error: {message}", file=sys.stderr, flush=True)


def notice(message):
    print(f"::notice::{message}" if github() else message, flush=True)


@contextmanager
def group(title):
    if github():
        print(f"::group::{title}", flush=True)
        try:
            yield
        finally:
            print("::endgroup::", flush=True)
    else:
        print(f"{title}:", flush=True)
        yield
