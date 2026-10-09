from __future__ import annotations

import pytest

from engine.checks import patterns
from engine.diffing import line_diff
from engine.models import Edit
from engine.tests.conftest import REPO


def run(file: str, after: str, before: str = "", prompt: str = "") -> list:
    edit = Edit(agent="a", file=file, before=before, after=after, prompt=prompt)
    return patterns.run_patterns(edit, REPO, line_diff(before, after))


def checks(findings) -> set[tuple[str, str]]:
    return {(f.check, f.severity) for f in findings}


# -- Hardcode Hunter ----------------------------------------------------------


@pytest.mark.parametrize("secret", [
    'token = "xo' 'xb-123456789012-abcdefghijklmnop"',
    'gh = "gh' 'p_abcdefghijklmnopqrstuvwxyz0123456789"',
    'key = "s' 'k-abcdefghijklmnopqrstuvwxyz123456"',
    'aws = "AK' 'IAABCDEFGHIJKLMNOP"',
    "-----BEGIN RSA PRIV" "ATE KEY-----",
    'url = "postgres://admin:hunter22@db.internal/app"',
])
def test_known_secret_formats_are_high(secret):
    found = run("app/config.py", secret + "\n")
    assert ("hardcode_hunter", "high") in checks(found)


def test_secret_is_redacted_in_evidence():
    found = run("app/config.py", 'token = "xo' 'xb-123456789012-abcdefghijklmnop"\n')
    assert "abcdefghijklmnop" not in found[0].evidence
    assert found[0].evidence.startswith('token = "xo' 'xb-')


def test_abbreviated_token_is_not_flagged():
    assert run("app/config.py", 'hint = "xo' 'xb-…"\n') == []


def test_high_entropy_string_is_medium():
    found = run("app/config.py", 'blob = "q8Zx2LmP9vTr4KdW7sYb1NcH6jFu3GeA"\n')
    assert ("hardcode_hunter", "medium") in checks(found)


def test_password_assignment_is_medium_and_masked():
    found = run("app/config.py", 'password = "correct-horse-battery"\n')
    assert found[0].severity == "medium" and "battery" not in found[0].evidence


def test_local_path_and_fixed_port_are_low():
    found = run("app/config.py", 'path = "C:\\\\Users\\\\me\\\\data"\nport = 8080\n')
    assert checks(found) == {("hardcode_hunter", "low")}
    assert {f.message for f in found} == {"Absolute local path", "Fixed port 8080"}


def test_only_added_lines_are_checked():
    before = 'token = "xo' 'xb-123456789012-abcdefghijklmnop"\n'
    assert run("app/config.py", before + "x = 1\n", before=before) == []


def test_ordinary_code_is_clean():
    assert run("app/util.py", "def add(a, b):\n    return a + b\n") == []


# -- Test Guardian ------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "@pytest.mark.skip",
    "    pytest.skip('later')",
    "    assert True",
    "it.only('works', () => {})",
    "xit('works', () => {})",
    "test.skip('works', () => {})",
    "expect(true).toBe(true)",
])
def test_skipped_or_vacuous_tests_are_flagged(line):
    found = run("tests/test_x.py", line + "\n")
    assert ("test_guardian", "medium") in checks(found)


def test_deleted_python_test_is_high():
    before = "def test_a():\n    assert 1\n\ndef test_b():\n    assert 2\n"
    after = "def test_a():\n    assert 1\n"
    found = run("tests/test_x.py", after, before)
    assert [(f.check, f.severity, f.message) for f in found] == [("test_guardian", "high", "Test deleted: test_b")]


def test_deleted_js_test_is_high():
    before = "it('adds', () => {})\nit('subtracts', () => {})\n"
    found = run("web/math.test.js", "it('adds', () => {})\n", before)
    assert ("test_guardian", "high") in checks(found)


def test_skip_in_non_test_file_is_ignored():
    assert run("app/util.py", "assert True\n") == []


# -- Reality Check ------------------------------------------------------------


def test_unknown_import_is_marked_not_installed():
    found = run("app/signup.py", "import slack_notify_pro\n")
    assert [(f.check, f.line) for f in found] == [("reality_check", 1)]
    assert "not installed" in found[0].message


@pytest.mark.parametrize("line", [
    "import os",                        # stdlib
    "from app.validators import x",     # in the repo
    "import requests",                  # in requirements.txt
    "from . import validators",         # relative
    "import tests.test_signup",         # a repo directory
])
def test_known_imports_are_fine(line):
    assert run("app/signup.py", line + "\n") == []


def test_import_alias_maps_to_requirement(tmp_path):
    (tmp_path / "requirements.txt").write_text("PyYAML>=6\npillow\n")
    edit = Edit(agent="a", file="x.py", after="import yaml\nfrom PIL import Image\nimport cv2\n")
    found = patterns.run_patterns(edit, tmp_path)
    assert [f.message.split("'")[1] for f in found] == ["cv2"]


def test_js_imports_checked_against_package_json(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "18"}, "devDependencies": {"vite": "5"}}')
    after = "import React from 'react'\nimport fs from 'fs'\nimport x from './x'\nimport y from 'left-pad-pro'\n" \
            "const z = require('@scope/pkg/deep')\n"
    found = patterns.run_patterns(Edit(agent="a", file="src/a.js", after=after), tmp_path)
    assert sorted(f.message.split("'")[1] for f in found) == ["@scope/pkg", "left-pad-pro"]


# -- Scope Guard --------------------------------------------------------------


@pytest.mark.parametrize("file", [
    "package-lock.json", "web/yarn.lock", ".env", ".env.production", ".github/workflows/ci.yml",
])
def test_unrequested_sensitive_files_are_flagged(file):
    found = run(file, "x\n", prompt="rename a variable in signup")
    assert [(f.check, f.severity) for f in found] == [("scope_guard", "medium")]


@pytest.mark.parametrize("file,prompt", [
    ("package-lock.json", "upgrade the dependencies"),
    (".env", "add the new API URL to .env"),
    (".github/workflows/ci.yml", "fix the CI pipeline"),
])
def test_requested_sensitive_files_are_fine(file, prompt):
    assert run(file, "x\n", prompt=prompt) == []


def test_ordinary_file_never_trips_scope_guard():
    assert patterns.scope_guard(Edit(agent="a", file="app/x.py", prompt="")) == []
