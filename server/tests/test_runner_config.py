"""The Ask runner's MCP config follows the origin being served (INK-194, decision 0109)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "runner_config.py"
_spec = importlib.util.spec_from_file_location("runner_config", SCRIPT)
assert _spec and _spec.loader
runner_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner_config)


def test_http_origin_has_no_ca(tmp_path: Path) -> None:
    entry = runner_config.build_entry("http://127.0.0.1:8000", None, tmp_path)
    assert entry["env"] == {"INKBRIDGE_API_URL": "http://127.0.0.1:8000"}
    assert "SSL_CERT_FILE" not in entry["env"]


def test_https_origin_sets_ca(tmp_path: Path) -> None:
    entry = runner_config.build_entry("https://127.0.0.1:4173", Path("/x/ca.pem"), tmp_path)
    assert entry["env"]["INKBRIDGE_API_URL"] == "https://127.0.0.1:4173"
    assert entry["env"]["SSL_CERT_FILE"] == "/x/ca.pem"


def test_update_keeps_other_servers(tmp_path: Path) -> None:
    out = tmp_path / "mcp.json"
    out.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "vault": {"command": "v"},
                    "inkbridge": {"env": {"INKBRIDGE_API_URL": "http://127.0.0.1:8000"}},
                }
            }
        )
    )
    entry = runner_config.build_entry("https://127.0.0.1:4173", Path("/x/ca.pem"), tmp_path)
    runner_config.write_config(out, entry)
    cfg = json.loads(out.read_text())
    assert cfg["mcpServers"]["vault"] == {"command": "v"}
    assert cfg["mcpServers"]["inkbridge"]["env"]["INKBRIDGE_API_URL"] == "https://127.0.0.1:4173"


def test_https_without_ca_file_errors(tmp_path: Path) -> None:
    rc = runner_config.main(
        [
            "--origin",
            "https://127.0.0.1:4173",
            "--ca",
            str(tmp_path / "missing.pem"),
            "--out",
            str(tmp_path / "mcp.json"),
        ]
    )
    assert rc != 0
    assert not (tmp_path / "mcp.json").exists()


def test_switching_to_http_drops_ssl_cert_file(tmp_path: Path) -> None:
    out = tmp_path / "mcp.json"
    runner_config.write_config(
        out, runner_config.build_entry("https://127.0.0.1:4173", Path("/x/ca.pem"), tmp_path)
    )
    assert "SSL_CERT_FILE" in json.loads(out.read_text())["mcpServers"]["inkbridge"]["env"]

    runner_config.write_config(
        out, runner_config.build_entry("http://127.0.0.1:8000", None, tmp_path)
    )
    env = json.loads(out.read_text())["mcpServers"]["inkbridge"]["env"]
    assert "SSL_CERT_FILE" not in env
    assert env["INKBRIDGE_API_URL"] == "http://127.0.0.1:8000"
