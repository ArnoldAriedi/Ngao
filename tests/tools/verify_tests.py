"""Cross-check every test against the real app: imports, routes, methods, error messages, fixtures, fields, settings, patches."""
import ast, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
problems = []
checked_messages = 0
def problem(path, line, text): problems.append(f"{Path(path).relative_to(ROOT)}:{line}: {text}")

def parse(path): return ast.parse(Path(path).read_text())
def top_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name): names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)): names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return names

def module_path(dotted):
    p = ROOT / (dotted.replace(".", "/") + ".py")
    if p.exists(): return p
    d = ROOT / dotted.replace(".", "/")
    return d if d.is_dir() else None

# ---------- application facts
app_strings, routes, model_columns, settings_fields = set(), [], {}, set()
for path in (ROOT / "app").glob("*.py"):
    tree = parse(path)
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str): app_strings.add(node.value)
        if isinstance(node, ast.JoinedStr):
            app_strings.add("".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values))
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix": prefix = kw.value.value
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "delete") and dec.args:
                    base = prefix if getattr(dec.func.value, "id", "") == "router" else ""
                    routes.append((dec.func.attr, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", base + dec.args[0].value) + "$"), base + dec.args[0].value))
    if path.name == "models.py":
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                model_columns[node.name] = {s.target.id for s in node.body if isinstance(s, ast.AnnAssign)}
    if path.name == "config.py":
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Settings":
                settings_fields = {s.target.id for s in node.body if isinstance(s, ast.AnnAssign)}
module_attrs = {f"app.{p.stem}": top_names(parse(p)) for p in (ROOT / "app").glob("*.py")}

# ---------- test files
HELPER_MODELS = {"make_user": "User", "make_record": "ConvictionRecord", "make_staff": "Staff", "make_report": "CorrectionRequest"}
HELPER_PARAMS = {"make_user": {"verified"}, "make_record": {"km"}, "make_staff": {"role"}, "make_report": {"reason", "hours_old"}}
BUILTIN_FIXTURES = {"monkeypatch", "tmp_path", "capsys", "request"}
CONFTEST_FIXTURES = {"client", "db", "outbox"}
test_files = [p for p in (ROOT / "tests").rglob("test_*.py")]
integration = [p for p in test_files if "integration" in p.parts]

def resolve(node, consts):
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
    if isinstance(node, ast.Name): return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        out = ""
        for part in node.values:
            if isinstance(part, ast.Constant): out += part.value
            else:
                got = resolve(part.value, consts) if isinstance(part.value, ast.Name) else None
                out += got if got is not None else "X"
        return out
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        base = resolve(node.func.value, consts)
        return re.sub(r"\{[^}]*\}", "X", base) if base else None
    return None

for path in test_files:
    tree = parse(path)
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = resolve(node.value, consts)
            if value is not None: consts[node.targets[0].id] = value
    local_fixtures = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("fixture" in ast.unparse(d) for d in n.decorator_list)}
    ui_fixtures = {"api", "app_page", "new_page", "site", "browser"} if "ui" in path.parts else set()

    for node in ast.walk(tree):
        # 1. imports resolve
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in ("app", "tests", "scripts"):
            target = module_path(node.module)
            if target is None: problem(path, node.lineno, f"module {node.module} does not exist"); continue
            if target.is_dir():
                for a in node.names:
                    if not (target / a.name).exists() and not (target / f"{a.name}.py").exists(): problem(path, node.lineno, f"{node.module} has no {a.name}")
                continue
            names = top_names(parse(target))
            for a in node.names:
                if a.name not in names: problem(path, node.lineno, f"{node.module} has no name '{a.name}'")
        # 2. routes and methods
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("get", "post", "put", "delete") \
                and isinstance(node.func.value, ast.Name) and node.func.value.id in ("client", "test_client") and node.args:
            url = resolve(node.args[0], consts)
            if url is None: continue
            url = url.split("?")[0]
            method = node.func.attr
            same_path = [r for r in routes if r[1].match(url)]
            if not same_path and url != "/": problem(path, node.lineno, f"no route for {url}")
            elif same_path and method not in {r[0] for r in same_path}:
                if "405" not in "\n".join(Path(path).read_text().split("\n")[node.lineno - 1:node.lineno + 2]):
                    problem(path, node.lineno, f"{method.upper()} {url} but route allows {sorted({r[0] for r in same_path})}")
        # 2b. (method, path) pairs listed in tables
        if isinstance(node, ast.Tuple) and len(node.elts) == 2 and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts) \
                and node.elts[0].value in ("get", "post", "put", "delete") and node.elts[1].value.startswith("/api"):
            table_url, table_method = node.elts[1].value.split("?")[0], node.elts[0].value
            table_url = re.sub(r"/\d+(?=/|$)", "/X", table_url)
            matching = [r for r in routes if r[1].match(table_url)]
            if not matching: problem(path, node.lineno, f"no route for {table_url}")
            elif table_method not in {r[0] for r in matching}: problem(path, node.lineno, f"{table_method.upper()} {table_url} but route allows {sorted({r[0] for r in matching})}")
        # 3. asserted messages exist in the app
        http_error = any(marker in ast.unparse(node) for marker in ("['detail']", "{'detail'", "value.detail", "failure.detail")) if isinstance(node, ast.Compare) else False
        if isinstance(node, ast.Compare) and http_error:
            for side in [node.left, *node.comparators]:
                for const in ast.walk(side):
                    if isinstance(const, ast.Constant) and isinstance(const.value, str) and const.value != "detail" and len(const.value) > 3:
                        text = const.value
                        checked_messages += 1
                        exact = any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
                        templated = (s for s in app_strings if "{}" in s and len(s.replace("{}", "")) >= 12)
                        if not any(text == s or (not exact and text in s) for s in app_strings) and not any(re.fullmatch(re.escape(s).replace(r"\{\}", ".+"), text) for s in templated):
                            problem(path, node.lineno, f"asserted message not found in app: {text!r}")
        # 5. model fields set through the builders
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in HELPER_MODELS:
            allowed = model_columns[HELPER_MODELS[node.func.id]] | HELPER_PARAMS[node.func.id]
            for kw in node.keywords:
                if kw.arg and kw.arg not in allowed: problem(path, node.lineno, f"{node.func.id}() has no field '{kw.arg}'")
        # 6. settings attributes
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr" and len(node.args) >= 2:
            first, second = node.args[0], node.args[1]
            if isinstance(first, ast.Name) and first.id == "settings" and isinstance(second, ast.Constant):
                if second.value not in settings_fields: problem(path, node.lineno, f"settings has no field '{second.value}'")
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
                module, _, attr = first.value.rpartition(".")
                names = module_attrs.get(module)
                if names is not None and attr not in names: problem(path, node.lineno, f"patch target {first.value} does not exist")
        # 4. fixtures exist
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and node in tree.body:
            params = {a.arg for a in node.args.args}
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and "parametrize" in ast.unparse(dec.func) and dec.args and isinstance(dec.args[0], ast.Constant):
                    params -= {n.strip() for n in dec.args[0].value.split(",")}
            allowed = BUILTIN_FIXTURES | local_fixtures | ui_fixtures | (CONFTEST_FIXTURES if path in integration else set())
            if path not in integration and "ui" not in path.parts: allowed |= {"smtp", "gateway", "mail", "sms", "emails", "tmp_path"}
            for p in params - allowed: problem(path, node.lineno, f"unknown fixture '{p}' in {node.name}")

for p in problems: print(p)
print(f"\n{checked_messages} error messages verified against the app source")
print(f"{len(problems)} problems across {len(test_files)} test files ({len(routes)} routes, {sum(len(v) for v in model_columns.values())} model columns, {len(settings_fields)} settings checked against)")
sys.exit(1 if problems else 0)
