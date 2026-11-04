import ast
from pathlib import Path

import inkbridge.mcp

MCP_DIR = Path(inkbridge.mcp.__file__).parent


def is_db(mod: str) -> bool:
    return mod == "inkbridge.db" or mod.startswith("inkbridge.db.")


def imports_db(source: str, package: str = "inkbridge.mcp") -> bool:
    """True if the source imports inkbridge.db; `package` is the dotted package of the file."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                mod = ".".join(base + ([mod] if mod else []))
            if is_db(mod):
                return True
            if mod == "inkbridge" and any(a.name == "db" for a in node.names):
                return True
        elif isinstance(node, ast.Import) and any(is_db(a.name) for a in node.names):
            return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if is_db(node.value):  # importlib.import_module("inkbridge.db"), __import__(...)
                return True
    return False


def scan_for_db_imports(root: Path) -> list[str]:
    found = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).parent.parts
        package = ".".join(("inkbridge", "mcp", *rel))
        if imports_db(p.read_text(), package):
            found.append(str(p.relative_to(root)))
    return found


def test_mcp_package_never_imports_inkbridge_db():
    assert scan_for_db_imports(MCP_DIR) == []


def test_scan_reaches_subpackages(tmp_path):
    sub = tmp_path / "tools" / "deep"
    sub.mkdir(parents=True)
    (sub / "bad.py").write_text("from inkbridge.db import connect\n")
    (tmp_path / "ok.py").write_text("from inkbridge import config\n")
    assert scan_for_db_imports(tmp_path) == ["tools/deep/bad.py"]


def test_detector_catches_each_import_form():
    assert imports_db("import inkbridge.db")
    assert imports_db("from inkbridge import db")
    assert imports_db("from inkbridge.db import connect")
    assert not imports_db("from inkbridge import config")
    assert imports_db("from .. import db")
    assert imports_db("from ..db import connect")
    assert imports_db("from ...db.x import y", "inkbridge.mcp.tools")
    assert imports_db("from .. import db", "inkbridge.mcp.tools") is False  # inkbridge.mcp.db
    assert not imports_db("from . import client")
    assert imports_db("import importlib\nimportlib.import_module('inkbridge.db')")
    assert imports_db("__import__('inkbridge.db.ops')")
