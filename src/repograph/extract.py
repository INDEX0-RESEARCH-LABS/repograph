"""Tree-sitter based extraction of symbols, imports, references and routes.

Extraction is deliberately *syntactic*. It never executes repository code and
never guesses types. Every extracted item keeps the exact source line span so
later layers can attach evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from tree_sitter import Language, Node, Parser

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts


@dataclass
class Symbol:
    name: str
    qualified_name: str
    kind: str  # function | class | method | interface | type | enum | model
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    tags: list[str] = field(default_factory=list)


@dataclass
class Import:
    raw: str
    module: str
    level: int
    names: list[tuple[str, str]]  # (imported name, local binding); ("*", "*") for star
    line: int
    kind: str = "static"  # static | require | dynamic | reexport


@dataclass
class Ref:
    name: str
    line: int
    col: int
    kind: str  # call | attr_call | inherits | new
    receiver: str | None = None


@dataclass
class Route:
    method: str
    path: str
    handler: str
    line: int
    framework: str


@dataclass
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@lru_cache(maxsize=8)
def _parser(lang: str) -> Parser:
    if lang == "python":
        language = Language(tspy.language())
    elif lang in ("typescript", "tsx"):
        language = Language(tsts.language_tsx() if lang == "tsx" else tsts.language_typescript())
    elif lang in ("javascript", "jsx"):
        language = Language(tsjs.language())
    else:  # pragma: no cover - guarded by scanner
        raise ValueError(f"unsupported language: {lang}")
    return Parser(language)


def _text(node: Node) -> str:
    return node.text.decode("utf-8", "replace")


def _field(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


ATTR_KINDS = {
    "decorated_definition",
    "export_statement",
    "expression_statement",
}


# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------

PY_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
PY_MODEL_BASES = {"Base", "Model", "DeclarativeBase", "Document", "models.Model"}


def _string_value(node: Node) -> str | None:
    """First string literal inside a node, without quotes."""
    if node.type in ("string", "string_fragment"):
        if node.type == "string":
            for c in node.named_children:
                if c.type == "string_content":
                    return _text(c)
            return _text(node).strip("'\"")
        return _text(node)
    for c in node.named_children:
        v = _string_value(c)
        if v is not None:
            return v
    return None


def _py_routes(decorators: list[Node], handler: str) -> list[Route]:
    routes: list[Route] = []
    for dec in decorators:
        target = dec.named_children[0] if dec.named_children else None
        if target is None:
            continue
        if target.type == "call":
            fn = _field(target, "function")
            args = _field(target, "arguments")
            if fn is None or args is None:
                continue
            path = None
            method = None
            if fn.type == "attribute":
                attr = _field(fn, "attribute")
                name = _text(attr) if attr else ""
                if name in PY_VERBS:
                    method = name.upper()
                elif name == "route":
                    method = "GET"
                    for arg in args.named_children:
                        if arg.type == "keyword_argument":
                            k = _field(arg, "name")
                            v = _field(arg, "value")
                            if k is not None and _text(k) == "methods" and v is not None:
                                methods = [_string_value(x) for x in v.named_children]
                                first = next((m.upper() for m in methods if m), None)
                                method = first or method
                else:
                    continue
                path = _string_value(args)
            elif fn.type == "identifier" and _text(fn) == "route":
                method, path = "GET", _string_value(args)
            if method and path is not None:
                routes.append(Route(method, path, handler, dec.start_point[0] + 1, "python-web"))
    return routes


def _walk_python(node: Node, out: ParseResult, scope: list[str], in_class: bool = False) -> None:
    for child in node.named_children:
        typ = child.type

        if typ == "decorated_definition":
            decorators = [c for c in child.children if c.type == "decorator"]
            definition = _field(child, "definition")
            if definition is not None:
                _walk_python_definition(definition, out, scope, decorators, in_class)
            continue

        if typ == "import_statement":
            _py_import(child, out)
            continue
        if typ == "import_from_statement":
            _py_import_from(child, out)
            continue
        if typ == "call":
            fn = _field(child, "function")
            if fn is not None:
                if fn.type == "identifier":
                    name = _text(fn)
                    if name == "__import__":
                        args = _field(child, "arguments")
                        module = _string_value(args) if args is not None else None
                        out.imports.append(Import(_text(child), module or "", 0, [("*", "*")],
                                                  child.start_point[0] + 1, "dynamic"))
                    else:
                        out.refs.append(Ref(name, child.start_point[0] + 1, fn.start_point[1], "call"))
                elif fn.type == "attribute":
                    attr = _field(fn, "attribute")
                    if attr is not None:
                        attr_name = _text(attr)
                        if attr_name == "import_module":
                            args = _field(child, "arguments")
                            module = _string_value(args) if args is not None else None
                            out.imports.append(Import(_text(child), module or "", 0, [("*", "*")],
                                                      child.start_point[0] + 1, "dynamic"))
                        else:
                            obj = _field(fn, "object")
                            receiver = _text(obj) if obj is not None and obj.type == "identifier" else None
                            out.refs.append(Ref(attr_name, child.start_point[0] + 1,
                                                attr.start_point[1], "attr_call", receiver))
            _walk_python(child, out, scope, in_class)
            continue

        _walk_python_definition(child, out, scope, [], in_class)


def _walk_python_definition(
    node: Node, out: ParseResult, scope: list[str], decorators: list[Node], in_class: bool = False
) -> None:
    typ = node.type
    if typ == "class_definition":
        name_node = _field(node, "name")
        if name_node is None:
            return
        name = _text(name_node)
        qname = ".".join([*scope, name])
        bases = _field(node, "superclasses")
        tags: list[str] = []
        if bases is not None:
            for b in bases.named_children:
                base = _text(b)
                out.refs.append(Ref(base.split(".")[-1], b.start_point[0] + 1, b.start_point[1], "inherits"))
                if base in PY_MODEL_BASES or base.endswith("Base") or base.endswith("Model"):
                    tags.append("db_model")
        body = _field(node, "body")
        out.symbols.append(
            Symbol(name, qname, "class", node.start_point[0] + 1, node.end_point[0] + 1,
                   node.start_point[1], node.end_point[1], tags)
        )
        if body is not None:
            for c in body.named_children:
                if c.type == "decorated_definition":
                    decs = [x for x in c.children if x.type == "decorator"]
                    d = _field(c, "definition")
                    if d is not None:
                        _walk_python_definition(d, out, [*scope, name], decs, True)
                elif c.type in ("function_definition", "class_definition"):
                    _walk_python_definition(c, out, [*scope, name], [], True)
        return

    if typ in ("function_definition", "lambda"):
        name_node = _field(node, "name")
        if name_node is None:
            return
        name = _text(name_node)
        qname = ".".join([*scope, name])
        out.symbols.append(
            Symbol(name, qname, "method" if in_class else "function", node.start_point[0] + 1,
                   node.end_point[0] + 1, node.start_point[1], node.end_point[1])
        )
        out.routes.extend(_py_routes(decorators, name))
        body = _field(node, "body")
        if body is not None:
            _walk_python(body, out, [*scope, name], False)
        return

    _walk_python(node, out, scope)


def _py_import(node: Node, out: ParseResult) -> None:
    for name_node in [c for c in node.children if c.type in ("dotted_name", "aliased_import")]:
        if name_node.type == "aliased_import":
            mod = _field(name_node, "name")
            alias = _field(name_node, "alias")
            if mod is None:
                continue
            module = _text(mod)
            local = _text(alias) if alias is not None else module.split(".")[0]
        else:
            module = _text(name_node)
            local = module.split(".")[0]
        out.imports.append(
            Import(_text(node), module, 0, [(module, local)], node.start_point[0] + 1)
        )


def _py_import_from(node: Node, out: ParseResult) -> None:
    module_node = _field(node, "module_name")
    module = ""
    level = 0
    if module_node is not None:
        if module_node.type == "relative_import":
            prefix = next((c for c in module_node.named_children if c.type == "import_prefix"), None)
            level = _text(prefix).count(".") if prefix is not None else 1
            dotted = next((c for c in module_node.named_children if c.type == "dotted_name"), None)
            module = _text(dotted) if dotted is not None else ""
        else:
            module = _text(module_node)

    names: list[tuple[str, str]] = []

    def collect(n: Node) -> None:
        for child in n.named_children:
            if module_node is not None and (child.start_byte, child.end_byte) == (
                module_node.start_byte,
                module_node.end_byte,
            ):
                continue
            if child.type == "dotted_name":
                name = _text(child)
                names.append((name, name.split(".")[0]))
            elif child.type == "aliased_import":
                name_node = _field(child, "name")
                alias = _field(child, "alias")
                if name_node is not None:
                    names.append((_text(name_node), _text(alias) if alias is not None
                                  else _text(name_node).split(".")[0]))
            elif child.type == "wildcard_import":
                names.append(("*", "*"))
            else:
                collect(child)

    collect(node)
    out.imports.append(Import(_text(node), module, level, names, node.start_point[0] + 1))


# --------------------------------------------------------------------------
# TypeScript / JavaScript
# --------------------------------------------------------------------------

TS_HTTP = {"Get", "Post", "Put", "Patch", "Delete", "Head", "Options"}


def _ts_class_prefix(node: Node) -> str:
    prefix = ""
    for c in node.children:
        if c.type == "decorator":
            target = c.named_children[0] if c.named_children else None
            if target is not None and target.type == "call_expression":
                fn = _field(target, "function")
                args = _field(target, "arguments")
                if fn is not None and _text(fn) == "Controller" and args is not None:
                    prefix = _string_value(args) or ""
    return prefix


def _ts_routes_from(decorators: list[Node], handler: str, prefix: str) -> list[Route]:
    routes: list[Route] = []
    for c in decorators:
        target = c.named_children[0] if c.named_children else None
        if target is None or target.type != "call_expression":
            continue
        fn = _field(target, "function")
        args = _field(target, "arguments")
        if fn is None or args is None:
            continue
        name = _text(fn)
        if name not in TS_HTTP and name != "Route":
            continue
        path = _string_value(args) or ""
        method = "GET" if name == "Route" else name.upper()
        routes.append(Route(method, (prefix + path) if path else prefix, handler,
                            c.start_point[0] + 1, "typescript-decorator"))
    return routes


def _ts_import(node: Node, out: ParseResult, kind: str = "static") -> None:
    source = _field(node, "source")
    if source is None:
        return
    module = _string_value(source)
    if module is None:
        return
    names: list[tuple[str, str]] = []
    clause = next((c for c in node.named_children if c.type == "import_clause"), None)
    if clause is not None:
        for c in clause.named_children:
            if c.type == "identifier":
                names.append(("default", _text(c)))
            elif c.type == "namespace_import":
                local = next((x for x in c.named_children if x.type == "identifier"), None)
                if local is not None:
                    names.append(("*", _text(local)))
            elif c.type == "named_imports":
                for spec in c.named_children:
                    if spec.type != "import_specifier":
                        continue
                    n = _field(spec, "name")
                    a = _field(spec, "alias")
                    if n is not None:
                        names.append((_text(n), _text(a) if a is not None else _text(n)))
    if not names:
        names = [("*", "*")]
    out.imports.append(Import(_text(node), module, 0, names, node.start_point[0] + 1, kind))


def _ts_require(node: Node, out: ParseResult) -> None:
    declarator = node.parent
    if declarator is None or declarator.type != "variable_declarator":
        return
    value = _field(declarator, "value")
    if value is None:
        return
    call = value
    if call.type != "call_expression":
        return
    fn = _field(call, "function")
    if fn is None or _text(fn) != "require":
        return
    args = _field(call, "arguments")
    module = _string_value(args) if args is not None else None
    if module is None:
        return
    name_node = _field(declarator, "name")
    names: list[tuple[str, str]] = []
    if name_node is not None:
        if name_node.type == "identifier":
            names.append(("default", _text(name_node)))
        elif name_node.type == "object_pattern":
            for p in name_node.named_children:
                if p.type == "shorthand_property_identifier_pattern":
                    names.append((_text(p), _text(p)))
                elif p.type == "pair_pattern":
                    k = _field(p, "key")
                    v = _field(p, "value")
                    if k is not None and v is not None:
                        names.append((_text(k), _text(v)))
    if not names:
        names = [("default", module.split("/")[-1])]
    out.imports.append(Import(_text(node), module, 0, names, node.start_point[0] + 1, "require"))


def _ts_walk(node: Node, out: ParseResult, scope: list[str]) -> None:
    for child in node.named_children:
        typ = child.type

        if typ == "import_statement":
            _ts_import(child, out)
            continue
        if typ == "export_statement":
            if _field(child, "source") is not None:
                _ts_import(child, out, "reexport")
            decl = _field(child, "declaration")
            if decl is not None:
                _ts_definition(decl, out, scope)
            continue
        if typ == "call_expression":
            fn = _field(child, "function")
            if fn is not None:
                if fn.type == "import":
                    args = _field(child, "arguments")
                    module = _string_value(args) if args is not None else None
                    out.imports.append(Import(_text(child), module or "", 0, [("*", "*")],
                                              child.start_point[0] + 1, "dynamic"))
                elif fn.type == "identifier":
                    name = _text(fn)
                    if name == "require":
                        _ts_require(child, out)
                    elif name == "import":
                        args = _field(child, "arguments")
                        module = _string_value(args) if args is not None else None
                        out.imports.append(Import(_text(child), module or "", 0, [("*", "*")],
                                                  child.start_point[0] + 1, "dynamic"))
                    else:
                        out.refs.append(Ref(name, child.start_point[0] + 1, fn.start_point[1], "call"))
                elif fn.type == "member_expression":
                    prop = _field(fn, "property")
                    obj = _field(fn, "object")
                    receiver = None
                    if obj is not None:
                        if obj.type in ("identifier", "this"):
                            receiver = _text(obj)
                        elif obj.type == "new_expression":
                            ctor = _field(obj, "constructor")
                            if ctor is not None:
                                receiver = _text(ctor).split(".")[-1]
                    if prop is not None:
                        out.refs.append(Ref(_text(prop), child.start_point[0] + 1,
                                            prop.start_point[1], "attr_call", receiver))
            _ts_walk(child, out, scope)
            continue
        if typ == "new_expression":
            ctor = _field(child, "constructor")
            if ctor is not None:
                out.refs.append(Ref(_text(ctor).split(".")[-1], child.start_point[0] + 1,
                                    ctor.start_point[1], "new"))
            _ts_walk(child, out, scope)
            continue

        _ts_definition(child, out, scope)


def _ts_definition(node: Node, out: ParseResult, scope: list[str]) -> None:
    typ = node.type
    if typ in ("function_declaration", "generator_function_declaration"):
        name_node = _field(node, "name")
        if name_node is None:
            return
        name = _text(name_node)
        out.symbols.append(
            Symbol(name, ".".join([*scope, name]), "function", node.start_point[0] + 1,
                   node.end_point[0] + 1, node.start_point[1], node.end_point[1])
        )
        body = _field(node, "body")
        if body is not None:
            _ts_walk(body, out, [*scope, name])
        return

    if typ in ("lexical_declaration", "variable_declaration"):
        for d in node.named_children:
            if d.type != "variable_declarator":
                continue
            name_node = _field(d, "name")
            value = _field(d, "value")
            if name_node is None or value is None:
                continue
            if value.type not in ("arrow_function", "function_expression", "function"):
                _ts_walk(d, out, scope)
                continue
            name = _text(name_node)
            out.symbols.append(
                Symbol(name, ".".join([*scope, name]), "function", node.start_point[0] + 1,
                       node.end_point[0] + 1, node.start_point[1], node.end_point[1])
            )
            body = _field(value, "body")
            if body is not None:
                _ts_walk(body, out, [*scope, name])
        return

    if typ == "class_declaration":
        name_node = _field(node, "name")
        if name_node is None:
            return
        name = _text(name_node)
        prefix = _ts_class_prefix(node)
        heritage = next((c for c in node.named_children if c.type == "class_heritage"), None)
        if heritage is not None:
            for c in heritage.named_children:
                if c.type == "extends_clause":
                    for v in c.named_children:
                        out.refs.append(Ref(_text(v).split(".")[-1], v.start_point[0] + 1,
                                            v.start_point[1], "inherits"))
        out.symbols.append(
            Symbol(name, ".".join([*scope, name]), "class", node.start_point[0] + 1,
                   node.end_point[0] + 1, node.start_point[1], node.end_point[1])
        )
        body = _field(node, "body")
        if body is not None:
            pending: list[Node] = []
            for c in body.named_children:
                if c.type == "decorator":
                    pending.append(c)
                    continue
                if c.type == "method_definition":
                    mn = _field(c, "name")
                    if mn is None:
                        continue
                    mname = _text(mn)
                    out.symbols.append(
                        Symbol(mname, f"{'.'.join([*scope, name])}.{mname}", "method",
                               c.start_point[0] + 1, c.end_point[0] + 1,
                               c.start_point[1], c.end_point[1])
                    )
                    out.routes.extend(_ts_routes_from(pending, f"{name}.{mname}", prefix))
                    pending = []
                    mb = _field(c, "body")
                    if mb is not None:
                        _ts_walk(mb, out, [*scope, name, mname])
                elif c.type == "class_declaration":
                    _ts_definition(c, out, [*scope, name])
                elif c.type == "method_signature":
                    pending = []
        out.routes.extend(_ts_routes_from([c for c in node.children if c.type == "decorator"],
                                         name, prefix))
        return

    if typ in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
        name_node = _field(node, "name")
        if name_node is None:
            return
        kind = {"interface_declaration": "interface", "type_alias_declaration": "type",
                "enum_declaration": "enum"}[typ]
        name = _text(name_node)
        out.symbols.append(
            Symbol(name, ".".join([*scope, name]), kind, node.start_point[0] + 1,
                   node.end_point[0] + 1, node.start_point[1], node.end_point[1])
        )
        return

    # Container nodes (blocks, statements, arguments) are walked so calls and
    # requires nested inside them are not missed.
    if typ not in ATTR_KINDS:
        _ts_walk(node, out, scope)


# --------------------------------------------------------------------------
# Prisma
# --------------------------------------------------------------------------

def _parse_prisma(text: str) -> ParseResult:
    import re

    out = ParseResult()
    for i, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"\s*model\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            out.symbols.append(Symbol(m.group(1), m.group(1), "model", i, i, 0, len(line), ["db_model"]))
    return out


def _first_error_line(tree, source: bytes) -> int | None:
    """Lowest line carrying a tree-sitter ERROR or missing token."""
    first: int | None = None
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            if first is None or node.start_byte < first:
                first = node.start_byte
        stack.extend(node.children)
    return source.count(b"\n", 0, first) + 1 if first is not None else None


def extract(rel_path: str, lang: str, source: bytes) -> ParseResult:
    if lang == "prisma":
        return _parse_prisma(source.decode("utf-8", "replace"))
    if lang == "sql":
        return ParseResult()
    parser = _parser(lang)
    tree = parser.parse(source)
    out = ParseResult()
    if tree.root_node.has_error and b" & " in source:
        # tree-sitter's JS/TS grammars reject a bare "&" in JSX text
        # ("Rated & Billed"), which TypeScript and React accept. Retry with a
        # same-length substitute so byte offsets, and therefore evidence, are
        # unchanged. Only adopted if the retry parses cleanly.
        retry = parser.parse(source.replace(b" & ", b" X "))
        if not retry.root_node.has_error:
            tree = retry
    if tree.root_node.has_error:
        line = _first_error_line(tree, source)
        where = f" at line {line}" if line else ""
        out.errors.append(f"syntax errors present{where}; extraction is partial")
    if lang == "python":
        _walk_python(tree.root_node, out, [])
    else:
        _ts_walk(tree.root_node, out, [])
    return out
