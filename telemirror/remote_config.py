"""
Optional remote mirror config (e.g. a GitHub Gist) with retry and a cached last-good copy.

Fallback order: remote fetch -> cached copy of the last successful fetch -> None
(the caller then continues with the local config sources as if no remote was set).
"""

import os
import re
import sys
import time
import urllib.request
from typing import Optional

import yaml

_GIST_PAGE = re.compile(
    r"^https?://gist\.github\.com/(?P<user>[\w.-]+)/(?P<id>[0-9a-f]+)(?:[/?#].*)?$"
)


def _log(message: str) -> None:
    # runs at import time, before the app logger is configured
    print(f"[remote-config] {message}", file=sys.stderr, flush=True)


def to_raw_url(url: str) -> str:
    """Turn a regular Gist page link into its raw URL; any other URL is returned as is.

    The raw URL without a revision hash always serves the latest version. For a
    multi-file Gist it serves the first file, so pass a raw link to pick another file.
    """
    url = url.strip()
    match = _GIST_PAGE.match(url)
    if match:
        return f"https://gist.githubusercontent.com/{match['user']}/{match['id']}/raw"
    return url


def _parse(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "directions" not in data:
        raise ValueError("remote config is not a mapping with a 'directions' key")
    return data


def _fetch(url: str, timeout: float, retries: int) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf8")
        except Exception as e:
            last_error = e
            _log(f"fetch attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(min(2**attempt, 10))
    raise last_error


def _write_cache(path: str, text: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf8") as file:
            file.write(text)
        os.replace(tmp, path)
    except OSError as e:
        _log(f"could not write cache {path}: {e}")


def load_remote_config(
    url: str, cache_file: str, timeout: float = 10.0, retries: int = 3
) -> Optional[dict]:
    """Returns the parsed remote config, or None if neither remote nor cache is usable."""
    raw_url = to_raw_url(url)

    try:
        text = _fetch(raw_url, timeout, retries)
        data = _parse(text)
        _write_cache(cache_file, text)
        _log(f"loaded config from {raw_url}")
        return data
    except Exception as e:
        _log(f"remote config unavailable: {e}")

    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf8") as file:
                data = _parse(file.read())
            _log(f"using cached copy of the last good remote config ({cache_file})")
            return data
        except Exception as e:
            _log(f"cached config unusable: {e}")

    _log("falling back to the local config")
    return None
