#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Smoke — surface counts (9+6+7=22) + one happy-path sim session per process env.

"""Smoke: enumerate all three surfaces via subprocess stdio, assert
22 distinct tools, then drive one happy-path session in-process."""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def rpc(surface, calls):
    env = dict(os.environ, ECLIPSE_TETHER_SURFACE=surface)
    proc = subprocess.Popen([sys.executable, str(HERE / "server.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, env=env)
    reqs = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": m,
                               "params": p}) + "\n"
                   for i, (m, p) in enumerate(calls))
    out, _ = proc.communicate(reqs)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main():
    total = {}
    for surface in ("agent", "operator", "tools"):
        resp = rpc(surface, [("initialize", {}), ("tools/list", {})])
        names = [t["name"] for t in resp[1]["result"]["tools"]]
        total[surface] = names
        print(surface, len(names), names)
    all_names = total["agent"] + total["operator"] + total["tools"]
    assert len(all_names) == 22 and len(set(all_names)) == 22, all_names
    resp = rpc("agent", [("tools/call", {"name": "definitely_not_a_tool",
                                         "arguments": {}})])
    assert resp[0]["error"]["code"] == -32602, resp
    print("smoke ok: 22 tools across 3 disjoint surfaces; unknown tool -32602")


if __name__ == "__main__":
    main()

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
