from __future__ import annotations

from engine.diffing import line_diff
from engine.graph import analyze_edit, build_graph, load_sources, walk_up
from engine.models import Edit
from engine.tests.conftest import REPO, source

SIGNUP = "app/signup.py::"


def graph():
    return build_graph(load_sources(REPO))


def test_graph_has_functions_across_files():
    g = graph()
    assert SIGNUP + "handle_signup" in g.nodes
    assert "app/validators.py::valid_email" in g.nodes
    assert len({n.file for n in g.nodes.values() if n.file.startswith("app/")}) >= 4


def test_cross_file_calls_resolve():
    edges = graph().edges
    assert ("app/routes.py::signup_route", SIGNUP + "handle_signup") in edges      # from x import y
    assert (SIGNUP + "handle_signup", "app/validators.py::valid_email") in edges
    assert ("app/routes.py::profile_route", SIGNUP + "find_user") in edges


def test_module_alias_and_class_methods_resolve():
    sources = {
        "pkg/__init__.py": "",
        "pkg/a.py": "class Box:\n    def __init__(self):\n        self.reset()\n    def reset(self):\n        pass\n",
        "main.py": "from pkg import a\nfrom pkg.a import Box\n\ndef run():\n    b = Box()\n    a.Box.reset(b)\n",
    }
    edges = build_graph(sources).edges
    assert ("pkg/a.py::Box.__init__", "pkg/a.py::Box.reset") in edges   # self.method()
    assert ("main.py::run", "pkg/a.py::Box.__init__") in edges          # constructor call
    assert ("main.py::run", "pkg/a.py::Box.reset") in edges             # module.Class.method


def test_walk_up_respects_depth():
    edges = {("b", "a"), ("c", "b"), ("d", "c"), ("e", "d")}
    assert walk_up(edges, ["a"], depth=3) == ["b", "c", "d"]
    assert walk_up(edges, ["a"], depth=1) == ["b"]


def test_edit_reports_touched_and_blast():
    before = source("app/signup.py")
    after = before.replace('raise ValueError("already registered")', 'raise ValueError("email taken")')
    edit = Edit(agent="a", file="app/signup.py", before=before, after=after)
    result = analyze_edit(edit, load_sources(REPO), line_diff(before, after))
    assert result.touched == [SIGNUP + "handle_signup"]
    assert result.blast[0] == "app/routes.py::signup_route"          # nearest first
    assert "tests/test_signup.py::test_signup_creates_user" in result.blast
    assert result.findings == []                                       # same signature


def test_module_level_edit_touches_no_function():
    before = source("app/signup.py")
    result = analyze_edit(Edit(agent="a", file="app/signup.py", before=before, after=before.replace("USERS = {}", "USERS = dict()")),
                          load_sources(REPO), line_diff(before, ""))
    assert result.touched == [] and result.blast == []


def test_new_function_is_touched_with_no_blast():
    before = source("app/validators.py")
    after = before + "\n\ndef shout(text):\n    return text.upper()\n"
    result = analyze_edit(Edit(agent="a", file="app/validators.py", before=before, after=after),
                          load_sources(REPO), line_diff(before, after))
    assert result.touched == ["app/validators.py::shout"] and result.blast == []


def test_breaking_signature_change_raises_impact_finding():
    before = source("app/signup.py")
    after = before.replace("def find_user(email):", "def find_user(email, tenant):")
    result = analyze_edit(Edit(agent="a", file="app/signup.py", before=before, after=after),
                          load_sources(REPO), line_diff(before, after))
    [finding] = result.findings
    assert finding.check == "impact_analyst" and "find_user" in finding.message
    assert "profile_route" in finding.message or "handle_signup" in finding.message


def test_additive_signature_with_default_is_not_breaking():
    before = source("app/signup.py")
    after = before.replace("def find_user(email):", "def find_user(email, tenant=None):")
    result = analyze_edit(Edit(agent="a", file="app/signup.py", before=before, after=after),
                          load_sources(REPO), line_diff(before, after))
    assert result.findings == []


def test_removed_function_with_callers_raises_impact_finding():
    before = source("app/validators.py")
    after = before.replace("def valid_password(password):\n    return len(password) >= 8 and any(c.isdigit() for c in password)\n", "")
    result = analyze_edit(Edit(agent="a", file="app/validators.py", before=before, after=after),
                          load_sources(REPO), line_diff(before, after))
    assert "app/validators.py::valid_password" in result.touched
    assert any("was removed" in f.message and "handle_signup" in f.message for f in result.findings)


def test_non_python_file_has_no_graph_effect():
    result = analyze_edit(Edit(agent="a", file="README.md", before="a", after="b"), load_sources(REPO), line_diff("a", "b"))
    assert result.touched == [] and result.blast == [] and result.findings == []


def test_syntax_error_does_not_raise():
    before = source("app/signup.py")
    result = analyze_edit(Edit(agent="a", file="app/signup.py", before=before, after="def broken(:\n"),
                          load_sources(REPO), line_diff(before, "def broken(:\n"))
    assert isinstance(result.touched, list)
