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


def scan_for_db_imports(root: Path) -> list[str]:
    return [str(p.relative_to(root)) for p in root.rglob("*.py") if imports_db(p.read_text())]


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
