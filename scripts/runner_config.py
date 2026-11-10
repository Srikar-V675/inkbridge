#!/usr/bin/env python3
"""Write the inkbridge entry of the Ask runner's MCP config for the origin being served (INK-194)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_entry(origin: str, ca: Path | None, server_dir: Path) -> dict:
    env = {"INKBRIDGE_API_URL": origin}
    if origin.startswith("https://") and ca is not None:
        env["SSL_CERT_FILE"] = str(ca)
    return {
        "command": "uv",
        "args": ["run", "--directory", str(server_dir), "inkbridge-mcp"],
        "env": env,
    }


def write_config(path: Path, entry: dict, name: str = "inkbridge") -> None:
    cfg = json.loads(path.read_text()) if path.exists() else {}
    cfg.setdefault("mcpServers", {})[name] = entry  # other servers (vault) stay
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--origin", required=True)
    p.add_argument("--ca")
    p.add_argument("--out", required=True)
    p.add_argument("--name", default="inkbridge")
    a = p.parse_args(argv)
    ca = Path(a.ca).resolve() if a.ca else None
    if a.origin.startswith("https://") and (ca is None or not ca.is_file()):
        print(
            f"runner_config: https origin needs an existing --ca file (got {a.ca})", file=sys.stderr
        )
        return 1
    server_dir = Path(__file__).resolve().parents[1] / "server"
    write_config(Path(a.out), build_entry(a.origin, ca, server_dir), a.name)
    print(f"runner MCP config: {a.out} ({a.name} -> {a.origin})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
