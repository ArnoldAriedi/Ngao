"""Find undefined names and unused imports without needing any third-party linter."""
import ast
import builtins
import symtable
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".venv", "venv", "node_modules", ".git"}


def undefined(path):
    top = symtable.symtable(path.read_text(), str(path), "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()} | {"__file__"}
    found = []

    def walk(table):
        for symbol in table.get_symbols():
            name = symbol.get_name()
            if symbol.is_referenced() and symbol.is_global() and not symbol.is_assigned() and name not in defined and not hasattr(builtins, name):
                found.append(name)
        for child in table.get_children():
            walk(child)

    walk(top)
    found += [s.get_name() for s in top.get_symbols() if s.is_referenced() and not (s.is_assigned() or s.is_imported() or s.is_namespace()) and s.get_name() not in defined and not hasattr(builtins, s.get_name())]
    return found


def unused_imports(path):
    source = path.read_text()
    tree = ast.parse(source)
    lines = source.splitlines()
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update({(a.asname or a.name).split(".")[0]: node.lineno for a in node.names})
        elif isinstance(node, ast.ImportFrom):
            imported.update({a.asname or a.name: node.lineno for a in node.names})
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return [name for name, line in imported.items() if name not in used and "noqa" not in lines[line - 1] and path.name != "__init__.py"]


def main():
    problems = 0
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP & set(path.parts):
            continue
        for name in undefined(path):
            print(f"{path.relative_to(ROOT)}: undefined name {name}")
            problems += 1
        for name in unused_imports(path):
            print(f"{path.relative_to(ROOT)}: unused import {name}")
            problems += 1
    print(f"{problems} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
