import ast
from pathlib import Path

import inkbridge.mcp

MCP_DIR = Path(inkbridge.mcp.__file__).parent


def imports_db(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "inkbridge.db" or mod.startswith("inkbridge.db."):
                return True
            if mod == "inkbridge" and any(a.name == "db" for a in node.names):
                return True
        if isinstance(node, ast.Import) and any(
            a.name == "inkbridge.db" or a.name.startswith("inkbridge.db.") for a in node.names
        ):
            return True
    return False


def test_mcp_package_never_imports_inkbridge_db():
    offenders = [p.name for p in MCP_DIR.glob("*.py") if imports_db(p.read_text())]
    assert offenders == []


def test_detector_catches_each_import_form():
    assert imports_db("import inkbridge.db")
    assert imports_db("from inkbridge import db")
    assert imports_db("from inkbridge.db import connect")
    assert not imports_db("from inkbridge import config")
