#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai

"""Eclipse Tether Session / Proof / Gauge — v0.1 (P0, SIMULATOR ONLY).

Descriptor: "governed robot task authority — signed mandates, bounded
envelopes, evidence for every task."

Surfaces (ECLIPSE_TETHER_SURFACE), disjoint by dispatch table (§6):
  * agent    — 9 tools: fleet_discover, session_open,
               task_templates_list, task_dispatch, task_status,
               task_abort, telemetry_read, image_read, session_close.
  * operator — 6 tools: mandate_register, mandate_revoke,
               template_register, template_revoke, site_freeze_set,
               session_reattest. Human principal / desk only.
  * tools    — 7 offline tools: pack_verify, pack_render, pack_compare,
               gauge_check_mandate, gauge_check_template,
               gauge_check_pair, gauge_limits_list.
P0 total = 22 tools (spec §6 count method). Absences (§3.3) are not
tools: no T2 direct motion, no generic service/topic caller, no
safety-system access, no e-stop interference, no agent template
authoring, no unmandated-robot targeting.

P0 = ROS 2 + Gazebo + UR-class arm SIM ONLY. No real motion, no
hardware calls, no vendor SDK. Liability counsel gates P1 real motion
only (§10.4); P0 is unblocked.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import tether_ops as ops  # noqa: E402
from tether_engine import Bridge, Refusal, ToolError  # noqa: E402

FIXTURES = Path(os.environ.get("ECLIPSE_TETHER_FIXTURES", HERE / "fixtures"))
SURFACE = os.environ.get("ECLIPSE_TETHER_SURFACE", "agent")
BRIDGE = Bridge(FIXTURES)

_S = {"type": "string"}
_N = {"type": "number"}
_O = {"type": "object"}
_A = {"type": "array"}
_B = {"type": "boolean"}
_TS = {"type": "string", "description": "bench-only fixture clock (ISO-8601 "
        "with offset); labeled class: fixture wherever it surfaces"}

AGENT_DEFS = {
    "fleet_discover": ("Robots under this bridge for mandate-named serials "
        "only; non-mandate serials render as count, not identities (M3).",
        {"mandate_id": _S, "at_ts": _TS}, []),
    "session_open": ("Present a Herald-signed mandate artifact; bridge "
        "verifies signature, agent pin, window, attestation, lease.",
        {"mandate_artifact": _O, "agent_card_id": _S, "agent_signature": _S,
         "robot_serial": _S, "attested_serial": _S, "at_ts": _TS},
        ["mandate_artifact", "agent_card_id", "agent_signature", "robot_serial"]),
    "task_templates_list": ("Templates pinned in this session's mandate only.",
        {"session_id": _S, "at_ts": _TS}, ["session_id"]),
    "task_dispatch": ("Dispatch a pinned, human-authored task template "
        "inside the mandate envelope/ceilings/occupancy/window. All "
        "validation is pre-motion; refusals are named and receipted.",
        {"session_id": _S, "template_id": _S, "parameters": _O, "at_ts": _TS},
        ["session_id", "template_id", "parameters"]),
    "task_status": ("State + digests for a task run.",
        {"task_run_id": _S, "at_ts": _TS}, ["task_run_id"]),
    "task_abort": ("Request vendor safe-stop; always available, always "
        "receipted; abort of a terminal run is a no-op receipt.",
        {"task_run_id": _S, "at_ts": _TS}, ["task_run_id"]),
    "telemetry_read": ("Telemetry slice + digest (observe-class data only).",
        {"session_id": _S, "stream": _S, "range": _S, "at_ts": _TS},
        ["session_id"]),
    "image_read": ("End-state / camera image receipt (pack-bound hash).",
        {"session_id": _S, "source": _S, "at_ts": _TS}, ["session_id"]),
    "session_close": ("Release lease, seal the Blackbox-form evidence pack.",
        {"session_id": _S, "at_ts": _TS}, ["session_id"]),
}
OPERATOR_DEFS = {
    "mandate_register": ("Register a Herald-signed mandate + human "
        "risk-assessment ref. Gauge ENVELOPE_SOUND required.",
        {"mandate": _O, "at_ts": _TS}, ["mandate"]),
    "mandate_revoke": ("Revoke a mandate (verified operator approval); "
        "live sessions safe-stop with MANDATE_EXPIRED_STOP cause REVOKED.",
        {"mandate_id": _S, "operator_id": _S, "approval_signature": _S,
         "at_ts": _TS}, ["mandate_id", "operator_id", "approval_signature"]),
    "template_register": ("Register a HUMAN-AUTHORED task template + "
        "Herald pin signature. Agents can never reach this verb.",
        {"template": _O, "at_ts": _TS}, ["template"]),
    "template_revoke": ("Revoke a template pin (verified operator approval).",
        {"template_id": _S, "operator_id": _S, "approval_signature": _S,
         "at_ts": _TS}, ["template_id", "operator_id", "approval_signature"]),
    "site_freeze_set": ("Site freeze/thaw — owner act only. Freeze = "
        "observe-only across all robots; dispatch refuses SITE_FROZEN.",
        {"frozen": _B, "reason": _S, "operator_id": _S,
         "approval_signature": _S, "at_ts": _TS},
        ["frozen", "operator_id", "approval_signature"]),
    "session_reattest": ("Human clearance + re-attestation after a dropped "
        "or override-ended session (pose, task state, vendor fault state, "
        "telemetry tail). Never resumes the dead session.",
        {"session_id": _S, "human_clearance": _B, "operator_id": _S,
         "approval_signature": _S, "at_ts": _TS},
        ["session_id", "operator_id", "approval_signature"]),
}
TOOL_DEFS = {
    "pack_verify": ("Offline: verify one evidence pack. TASK_VERIFIED | "
        "TASK_UNVERIFIED + failing element named.",
        {"pack": _O}, ["pack"]),
    "pack_render": ("Offline: human-readable rendering of a pack — "
        "dispatches, refusals, gaps, overrides, stops; nothing dropped.",
        {"pack": _O}, ["pack"]),
    "pack_compare": ("Offline: element-level diff of two packs.",
        {"pack_a": _O, "pack_b": _O}, ["pack_a", "pack_b"]),
    "gauge_check_mandate": ("Static conformance of a mandate vs the safety "
        "grammar. ENVELOPE_SOUND | ENVELOPE_UNSOUND + violations named.",
        {"mandate": _O}, ["mandate"]),
    "gauge_check_template": ("Static conformance of a task template.",
        {"template": _O}, ["template"]),
    "gauge_check_pair": ("Cross-check mandate x template: pin, class, "
        "occupancy, envelope, ceiling resolution = min of all three.",
        {"mandate": _O, "template": _O}, ["mandate", "template"]),
    "gauge_limits_list": ("Vendor rated limits table as shipped "
        "(source-cited, version-stamped; never a safety claim).",
        {"robot_class": _S}, ["robot_class"]),
}

SURFACES = {"agent": (ops.AGENT_TOOLS, AGENT_DEFS),
            "operator": (ops.OPERATOR_TOOLS, OPERATOR_DEFS),
            "tools": (ops.TOOL_TOOLS, TOOL_DEFS)}
HANDLERS, DEFS = SURFACES.get(SURFACE, SURFACES["agent"])


def tool_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": p,
                             "required": r}}
            for n, (d, p, r) in DEFS.items()]


def handle(req):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-tether", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name not in HANDLERS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602, "message": f"unknown tool: {name}"}}
        if not isinstance(args, dict):
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602, "message": "arguments must be an object"}}
        missing = [k for k in DEFS[name][2] if k not in args]
        if missing:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"missing required argument(s): {', '.join(missing)}"}}
        call_args = dict(args)
        call_args["_surface"] = SURFACE
        try:
            out = HANDLERS[name](BRIDGE, call_args)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, indent=1)}]}}
        except Refusal as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(
                    {"refusal": e.code, "detail": e.detail,
                     "robot_moved": False}, indent=1)}], "isError": True}}
        except ToolError as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(e)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line))
        except Exception as e:  # never crash the transport
            resp = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
