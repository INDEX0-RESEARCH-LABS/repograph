from __future__ import annotations

from repograph.extract import extract


PY = b'''
import os, a.b as ab
from . import sibling
from ..pkg.mod import (alpha, beta as b)

class Base:
    pass

class Service(Base):
    def helper(self):
        return 1
    @app.post("/items/{item_id}")
    def handle(self, item_id):
        def nested():
            return self.helper()
        return alpha(item_id)

@router.route("/legacy", methods=["POST"])
def legacy():
    return b()
'''


def test_python_symbols_are_qualified_and_typed():
    out = extract("pkg/service.py", "python", PY)
    names = {s.qualified_name: s.kind for s in out.symbols}
    assert names["Service"] == "class"
    assert names["Service.helper"] == "method"
    assert names["Service.handle"] == "method"
    assert names["Service.handle.nested"] == "function"
    assert names["legacy"] == "function"
    assert [(s.name, s.tags) for s in out.symbols if s.name == "Service"] == [("Service", ["db_model"])]


def test_python_imports_preserve_levels_and_bindings():
    out = extract("pkg/service.py", "python", PY)
    imports = {(i.module, i.level): i for i in out.imports}
    assert imports[("", 1)].names == [("sibling", "sibling")]
    assert imports[("pkg.mod", 2)].names == [("alpha", "alpha"), ("beta", "b")]
    assert imports[("a.b", 0)].names == [("a.b", "ab")]


def test_python_routes_and_parse_error():
    out = extract("pkg/service.py", "python", PY)
    routes = {(r.method, r.path, r.handler) for r in out.routes}
    assert ("POST", "/items/{item_id}", "handle") in routes
    assert ("POST", "/legacy", "legacy") in routes
    bad = extract("bad.py", "python", b"def broken(:\n")
    assert bad.errors and "line 1" in bad.errors[0]


def test_jsx_bare_ampersand_is_not_a_parse_error():
    tsx = b"export function P() {\n  return <div>Rated & Billed</div>;\n}\n"
    out = extract("web/P.tsx", "tsx", tsx)
    assert out.errors == []
    assert [s.name for s in out.symbols] == ["P"]


def test_python_dynamic_import_detected():
    out = extract("d.py", "python", b"import importlib\nimportlib.import_module('pkg.' + x)\n")
    assert [i.kind for i in out.imports] == ["static", "dynamic"]


TS = b'''
import def, { a as b, c } from "./mod";
import * as ns from "../pkg";
const legacy = require("./legacy");
export class Service extends Base {
  @Get("/x")
  run() { return new Helper().go(b(1)); }
}
export const handler = (x: number) => x;
interface Shape { id: string }
type Alias = string;
enum Mode { A }
@Controller("/api") class Ctl {
  @Post("/items") create() { return fetch("/items"); }
}
const later = import(`./plugins/${name}`);
'''


def test_typescript_symbols_and_refs():
    out = extract("web/service.ts", "typescript", TS)
    kinds = {s.qualified_name: s.kind for s in out.symbols}
    assert kinds["Service"] == "class"
    assert kinds["Service.run"] == "method"
    assert kinds["handler"] == "function"
    assert kinds["Shape"] == "interface"
    assert kinds["Alias"] == "type"
    assert kinds["Mode"] == "enum"
    assert kinds["Ctl.create"] == "method"
    refs = {(r.name, r.kind) for r in out.refs}
    assert ("Base", "inherits") in refs
    assert ("go", "attr_call") in refs
    assert ("b", "call") in refs


def test_typescript_imports_routes_and_dynamic():
    out = extract("web/service.ts", "typescript", TS)
    imports = {i.module: i for i in out.imports}
    assert imports["./mod"].names == [("default", "def"), ("a", "b"), ("c", "c")]
    assert imports["../pkg"].names == [("*", "ns")]
    assert imports["./legacy"].kind == "require"
    assert {i.kind for i in out.imports if i.module.startswith("./plugins")} == {"dynamic"}
    routes = {(r.method, r.path) for r in out.routes}
    assert ("GET", "/x") in routes
    assert ("POST", "/api/items") in routes


def test_prisma_models_and_python_error_recovery():
    out = extract("schema.prisma", "prisma", b"model Account {\n id Int\n}\n")
    assert out.symbols[0].kind == "model"
    assert out.symbols[0].tags == ["db_model"]
