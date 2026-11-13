"""Regression tests for chained require() forms.

Forms that must produce an import edge:
  const x = require('path').prop          — member_expression value
  const {a} = require('path').prop        — destructured from member_expression (less common)
  require('path').method()                — bare call on require (expression_statement)

Forms that must NOT create false edges:
  const x = y.require('path')             — not a top-level require
  const x = obj.method()                  — no require at all
"""
from repograph.extract import extract


def _modules(src: bytes) -> list[str]:
    return [imp.module for imp in extract("test.js", "javascript", src).imports]


# ── forms that MUST produce an edge ──────────────────────────────────────

def test_chained_member_expression_const():
    mods = _modules(b"const request = require('../../test-helpers/context').request")
    assert "../../test-helpers/context" in mods


def test_chained_member_expression_let():
    mods = _modules(b"let es = require('./esbuild').installForTests()")
    assert "./esbuild" in mods


def test_chained_bare_call():
    """require('./esbuild').installForTests() — no assignment."""
    mods = _modules(b"require('./esbuild').installForTests()")
    assert "./esbuild" in mods


def test_chained_in_destructure():
    """const {a, b} = require('./mod').ns"""
    mods = _modules(b"const {a, b} = require('./mod').ns")
    assert "./mod" in mods


def test_multiple_chained_in_file():
    src = (
        b"const request = require('../../test-helpers/context').request\n"
        b"const response = require('../../test-helpers/context').response\n"
        b"const { only } = require('./only')\n"
    )
    mods = _modules(src)
    assert mods.count("../../test-helpers/context") >= 1  # deduplication allowed
    assert "./only" in mods


# ── forms that must NOT create false edges ───────────────────────────────

def test_no_edge_for_method_on_non_require():
    mods = _modules(b"const x = obj.method()")
    assert len(mods) == 0


def test_no_edge_for_property_require():
    """y.require('path') is not a top-level require."""
    mods = _modules(b"const x = y.require('./mod')")
    assert "./mod" not in mods
