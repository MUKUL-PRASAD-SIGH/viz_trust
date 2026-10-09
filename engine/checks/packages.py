"""Does an imported package exist? Answered in code, never by the model.

Gemma is good at saying an import *looks* invented, and bad at knowing for sure. So Reality Check
only raises a high-severity finding after the package index itself says the name doesn't exist.
Lookups are cached, and any network failure returns None ("unknown") rather than a guess.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache

import httpx

LOOKUP_TIMEOUT_S = 2.0

# Import names whose PyPI distribution is called something else.
PYTHON_ALIASES = {
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "Crypto": "pycryptodome",
    "magic": "python-magic",
}

PY_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import\b|import\s+(.+))")
JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s*\(\s*|^\s*import\s+)["']([^"'./][^"']*)["']""")

JS_BUILTINS = {
    "fs", "path", "os", "http", "https", "crypto", "url", "util", "events", "stream", "child_process",
    "assert", "buffer", "net", "zlib", "readline", "process", "timers", "worker_threads",
}


def language_of(path: str) -> str:
    if path.endswith(".py"):
        return "python"
    if path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        return "javascript"
    return "other"


def imports_in_line(text: str, language: str) -> list[str]:
    """Top-level package names imported on this line. Relative and built-in imports are skipped."""
    if language == "python":
        match = PY_IMPORT.match(text)
        if not match:
            return []
        if match.group(1):
            names = [match.group(1)]
        else:  # "import a.b as x, c" -> ["a.b", "c"]
            names = [part.split()[0] for part in match.group(2).split("#")[0].split(",") if part.strip()]
        tops = [name.split(".")[0] for name in names]
        return [top for top in tops if top and top not in sys.stdlib_module_names and top != "__future__"]
    if language == "javascript":
        found = []
        for spec in JS_IMPORT.findall(text):
            spec = spec.removeprefix("node:")
            top = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            if top not in JS_BUILTINS:
                found.append(top)
        return found
    return []


@lru_cache(maxsize=1024)
def exists_on_index(name: str, language: str) -> bool | None:
    """True or False from PyPI / npm. None if the lookup couldn't be made (offline, timeout)."""
    if language == "python":
        url = f"https://pypi.org/pypi/{name}/json"
    elif language == "javascript":
        url = f"https://registry.npmjs.org/{name.replace('/', '%2F')}"
    else:
        return None
    try:
        response = httpx.head(url, timeout=LOOKUP_TIMEOUT_S, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code == 404:
        return False
    return None


def resolve(import_name: str, language: str) -> bool | None:
    """Does the package behind this import exist? Checks the import name and known aliases."""
    direct = exists_on_index(import_name, language)
    if direct is True:
        return True
    alias = PYTHON_ALIASES.get(import_name) if language == "python" else None
    if alias:
        aliased = exists_on_index(alias, language)
        if aliased is not None:
            return aliased
    return direct
