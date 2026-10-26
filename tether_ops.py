#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Tool handlers — agent surface (9), operator surface (6), Proof+Gauge (7).

"""Tool handlers for Eclipse Tether P0 (spec §6: 22 tools exactly).

Surfaces are disjoint (spec §6.2): the server dispatches per-surface
tables; a verb absent from a surface returns the generic unknown-tool
refusal, byte-identical in shape to gibberish (no existence oracle).
"""
import json

import herald_sig
from tether_engine import (Bridge, Refusal, ToolError, canonical,
                           coerce_int_param, deep_key_scan,
                           gauge_check_mandate_doc, gauge_check_template_doc,
                           mandate_hash_of, now_iso, parse_time,
                           require_container_param, require_reference, sha,
                           template_hash_of, ESTOP_KEYS, OCCUPANCY_KEYS,
                           SAFETY_KEYS, T2_KEYS, WEAPON_KEYS, _inside,
                           _schema_validate, _uid)


def _now(bridge, args):
    now, fixture = bridge.clock(args)
    bridge.tick(now)
    return now, fixture


def _live_session(bridge, args, tool):
    sid = args.get("session_id")
    session = bridge.sessions.get(sid)
    if session is None:
        bridge.refuse("SESSION_NOT_FOUND", f"session {sid!r}", tool, None,
                      parse_time(args["at_ts"]) if args.get("at_ts") else None)
    return session


# ------------------------------------------------------------ agent (9)
def fleet_discover(bridge, args):
    now, fixture = _now(bridge, args)
    mandate = bridge.mandates.get(args.get("mandate_id") or "")
    named = set(mandate["robot_serials"]) if mandate else set()
    out, hidden = [], 0
    for serial, robot in sorted(bridge.robots.items()):
        if serial in named:
            out.append({"serial": serial, "model": robot.model,
                        "robot_class": robot.robot_class,
                        "firmware_attestation": robot.attestation(),
                        "state": robot.state})
        else:
            hidden += 1
    return {"robots": out, "non_mandate_robot_count": hidden,
            "note": "non-mandate serials render as count, not identities (M3)",
            "class_label": "fixture" if fixture else "bridge-clock"}


def session_open(bridge, args):
    now, fixture = _now(bridge, args)
    tool = "session_open"
    artifact = args.get("mandate_artifact")
    require_reference(artifact, "mandate_artifact")
    mandate = None
    if isinstance(artifact, dict):
        mandate = bridge.mandates.get(artifact.get("mandate_id") or "")
        if mandate is not None and mandate_hash_of(artifact) != mandate_hash_of(mandate):
            mandate = None
    elif isinstance(artifact, str):
        mandate = bridge.mandates.get(artifact)
    if mandate is None:
        bridge.refuse("MANDATE_NOT_FOUND", "mandate not registered at bridge",
                      tool, None, now)
    mid = mandate["mandate_id"]
    msg = canonical({k: v for k, v in mandate.items()
                     if k not in ("herald_signature", "state")})
    try:
        sig_ok = herald_sig.verify(bridge.herald_pub,
                                   msg, bytes.fromhex(mandate["herald_signature"]))
    except Exception:
        sig_ok = False
    if not sig_ok:
        bridge.refuse("MANDATE_SIGNATURE_INVALID", "Herald signature fails", tool, None, now)
    if mid in bridge.revoked_mandates:
        bridge.refuse("MANDATE_REVOKED", mid, tool, None, now)
    if mid in bridge.override_uncleared:
        bridge.refuse("HUMAN_OVERRIDE",
                      "human override stands until human clearance + "
                      "re-attestation (spec §9.3)", tool, None, now)
    card = args.get("agent_card_id")
    if card != mandate["agent_card_id"]:
        bridge.refuse("AGENT_NOT_IN_MANDATE", f"agent {card!r} not pinned", tool, None, now)
    pub_hex = bridge.agents.get(card or "")
    agent_sig = args.get("agent_signature") or ""
    sig_msg = canonical({"mandate_id": mid, "agent_card_id": card,
                         "action": "session_open"})
    try:
        agent_ok = bool(pub_hex) and herald_sig.verify(
            bytes.fromhex(pub_hex), sig_msg, bytes.fromhex(agent_sig))
    except Exception:
        agent_ok = False
    if not agent_ok:
        bridge.refuse("AGENT_NOT_IN_MANDATE",
                      "presenting agent key does not verify (M2)", tool, None, now)
    window = mandate["window"]
    if window.get("not_before") and now < parse_time(window["not_before"]):
        bridge.refuse("MANDATE_NOT_YET_VALID", window["not_before"], tool, None, now)
    if now >= parse_time(window["expires_at"]):
        bridge.refuse("MANDATE_EXPIRED", window["expires_at"], tool, None, now)
    serial = args.get("robot_serial")
    if isinstance(serial, str) and "*" in serial:
        bridge.refuse("ROBOT_WILDCARD_REFUSED", serial, tool, None, now)
    if serial not in mandate["robot_serials"]:
        bridge.refuse("ROBOT_NOT_IN_MANDATE", f"serial {serial!r}", tool, None, now)
    robot = bridge.robots.get(serial)
    if robot is None:
        bridge.refuse("ROBOT_NOT_IN_MANDATE", f"serial {serial!r} not at site",
                      tool, None, now)
    attested = args.get("attested_serial") or serial
    if attested != robot.serial:
        bridge.refuse("SERIAL_MISMATCH",
                      f"attested {attested!r} != mandate/site {robot.serial!r}",
                      tool, None, now)
    ctl = bridge.sim_control()
    if ctl.get("lease_holder") == "human":
        bridge.refuse("LEASE_HELD_BY_HUMAN", serial, tool, None, now)
    if serial in bridge.leases:
        bridge.refuse("LEASE_UNAVAILABLE", serial, tool, None, now)
    session = {"product": "eclipse-tether", "session_id": _uid("sess"),
               "mandate_id": mid, "agent_card_id": card,
               "robot_serial": serial, "attestation": robot.attestation(),
               "lease_ref": _uid("lease"), "pack_id": _uid("pack"),
               "state": "OPEN", "opened_at": now_iso(now), "closed_at": None,
               "end_cause": None, "refusals": [], "gaps": [], "overrides": [],
               "stops": [], "images": [], "pose_trace": []}
    bridge.sessions[session["session_id"]] = session
    bridge.leases[serial] = session["session_id"]
    return {"session_id": session["session_id"], "pack_id": session["pack_id"],
            "attestation": session["attestation"],
            "lease_ref": session["lease_ref"], "state": "OPEN",
            "tier_ceiling": "T1" if mandate.get("occupancy_class") else "T0",
            "occupancy_class": mandate.get("occupancy_class"),
            "class_label": "fixture" if fixture else "bridge-clock"}


def task_templates_list(bridge, args):
    _now(bridge, args)
    session = _live_session(bridge, args, "task_templates_list")
    mandate = bridge.mandates[session["mandate_id"]]
    out = []
    for pin in mandate["template_pins"]:
        t = bridge.templates.get(pin["template_id"])
        if t:
            out.append({"template_id": t["template_id"],
                        "template_hash": template_hash_of(t),
                        "robot_class": t["robot_class"],
                        "parameter_schema": t["parameter_schema"],
                        "required_envelope_class": t["required_envelope_class"]})
    return {"templates": out}


def task_dispatch(bridge, args):
    now, fixture = _now(bridge, args)
    tool = "task_dispatch"
    session = bridge.sessions.get(args.get("session_id"))
    if session is None:
        bridge.refuse("SESSION_NOT_FOUND", repr(args.get("session_id")), tool, None, now)
    if session["state"] in ("SEALED",) or session["state"].startswith("ENDED") \
            or session["state"] == "DROPPED":
        bridge.refuse("SESSION_ALREADY_ENDED", session["state"], tool, session, now)
    mandate = bridge.mandates[session["mandate_id"]]
    if session["mandate_id"] in bridge.override_uncleared:
        bridge.refuse("HUMAN_OVERRIDE", "override stands (§9.3)", tool, session, now)
    if bridge.frozen:
        bridge.refuse("SITE_FROZEN", bridge.freeze_reason or "", tool, session, now)
    if session["robot_serial"] in bridge.reattest_required:
        bridge.refuse("SESSION_STATE_UNKNOWN_REATTEST_REQUIRED",
                      "§9.2 re-attestation required before T1", tool, session, now)
    ctl = bridge.sim_control()
    if ctl.get("heartbeat_ok") is False:
        bridge.refuse("BRIDGE_HEARTBEAT_LOST", "robot heartbeat dead", tool, session, now)
    if ctl.get("evidence_ok") is False or not bridge.pack_writer_ok:
        bridge.refuse("EVIDENCE_PACK_UNAVAILABLE",
                      "a session that cannot emit its pack does not dispatch",
                      tool, session, now)
    if now >= parse_time(mandate["window"]["expires_at"]):
        bridge.refuse("MANDATE_EXPIRED", mandate["window"]["expires_at"],
                      tool, session, now)
    if mandate["mandate_id"] in bridge.revoked_mandates:
        bridge.refuse("MANDATE_REVOKED", mandate["mandate_id"], tool, session, now)
    tid = args.get("template_id")
    pins = {p["template_id"]: p["template_hash"] for p in mandate["template_pins"]}
    if tid not in pins:
        bridge.refuse("TASK_TEMPLATE_NOT_IN_MANDATE", repr(tid), tool, session, now)
    template = bridge.templates.get(tid)
    if template is None or template_hash_of(template) != pins[tid]:
        bridge.refuse("TASK_TEMPLATE_PIN_MISMATCH", repr(tid), tool, session, now)
    if tid in bridge.revoked_templates:
        bridge.refuse("TEMPLATE_REVOKED", tid, tool, session, now)
    params = args.get("parameters")
    require_container_param(params, "parameters", "object")
    for key, path in deep_key_scan(params):
        lk = key.lower()
        if lk in ESTOP_KEYS:
            bridge.refuse("ESTOP_INTERFERENCE_REFUSED", f"{path} (Law 5)", tool, session, now)
        if lk in SAFETY_KEYS:
            bridge.refuse("SAFETY_SYSTEM_ACCESS_REFUSED", f"{path} (Law 6)", tool, session, now)
        if lk in WEAPON_KEYS:
            bridge.refuse("WEAPONIZATION_REFUSED", path, tool, session, now)
        if lk in OCCUPANCY_KEYS:
            bridge.refuse("OCCUPANCY_UPGRADE_REFUSED",
                          f"{path}: occupancy is human-declared in the mandate "
                          "(Law 4)", tool, session, now)
        if lk in T2_KEYS:
            bridge.refuse("T2_DIRECT_MOTION_REFUSED",
                          f"{path}: no T2 direct-motion surface exists (Law 3)",
                          tool, session, now)
    violation = _schema_validate(template["parameter_schema"], params)
    if violation:
        bridge.refuse("PARAMETER_SCHEMA_VIOLATION", violation, tool, session, now)
    # envelope, pre-motion (spec §6.4 anchor)
    env = mandate["envelope"]["volume"]
    points = []
    if isinstance(params.get("goal"), dict):
        points.append(params["goal"])
    for wp in params.get("waypoints") or []:
        points.append(wp)
    for pt in points:
        pose = [pt.get("x"), pt.get("y"), pt.get("z")]
        if None in pose or not _inside(env, pose):
            bridge.refuse("ENVELOPE_VIOLATION",
                          f"goal/waypoint {pose} outside mandate envelope "
                          f"(pre-motion; robot never moved)", tool, session, now)
    ceilings = mandate["ceilings"]
    if params.get("speed_mps") is not None and params["speed_mps"] > ceilings["max_speed_mps"]:
        bridge.refuse("CEILING_EXCEEDS_MANDATE",
                      f"speed {params['speed_mps']} > mandate "
                      f"{ceilings['max_speed_mps']}", tool, session, now)
    if params.get("payload_kg") is not None and params["payload_kg"] > ceilings["max_payload_kg"]:
        bridge.refuse("CEILING_EXCEEDS_MANDATE",
                      f"payload {params['payload_kg']} > mandate "
                      f"{ceilings['max_payload_kg']}", tool, session, now)
    tdef = template.get("ceiling_defaults") or {}
    if tdef.get("max_speed_mps") is not None and params.get("speed_mps") is not None \
            and params["speed_mps"] > tdef["max_speed_mps"]:
        bridge.refuse("CEILING_EXCEEDS_MANDATE",
                      "speed exceeds template ceiling default", tool, session, now)
    occ = mandate.get("occupancy_class")
    if not occ:
        bridge.refuse("OCCUPANCY_UNKNOWN_OBSERVE_ONLY",
                      "occupancy undeclared; T0 only (Law 4)", tool, session, now)
    required = template.get("required_occupancy_class") or template["required_envelope_class"]
    from tether_engine import OCCUPANCY_RANK
    if required in OCCUPANCY_RANK and OCCUPANCY_RANK.get(occ, 0) < OCCUPANCY_RANK[required]:
        bridge.refuse("OCCUPANCY_INSUFFICIENT",
                      f"template requires {required}, mandate declares {occ}",
                      tool, session, now)
    window = mandate["window"]
    if window.get("not_before") and now < parse_time(window["not_before"]):
        bridge.refuse("TIME_WINDOW_VIOLATION", "before window", tool, session, now)
    robot = bridge.robots[session["robot_serial"]]
    goal = params.get("goal") or {}
    goal_pose = [goal.get("x", robot.pose[0]), goal.get("y", robot.pose[1]),
                 goal.get("z", robot.pose[2])]
    duration = params.get("duration_s", 10)
    duration = coerce_int_param(duration, "duration_s", "PARAMETER_SCHEMA_VIOLATION") \
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) else duration
    checks = [
        {"name": n, "verdict": "pass"} for n in
        ("session_live", "heartbeat_live", "mandate_unexpired", "template_pin",
         "parameter_schema", "envelope_pre_motion", "ceilings", "occupancy",
         "window")]
    run = {"product": "eclipse-tether", "task_run_id": _uid("run"),
           "session_id": session["session_id"], "template_id": tid,
           "template_hash": pins[tid], "parameters": params,
           "parameters_hash": sha(params), "dispatch_checks": checks,
           "state": "RUNNING", "start_pose": list(robot.pose),
           "goal_pose": goal_pose, "started_at": now_iso(now),
           "duration_s": duration, "vendor_task_ref": _uid("vendor"),
           "ended_at": None, "end_pose": None, "vendor_result": None}
    bridge.runs[run["task_run_id"]] = run
    session["state"] = "TASK_RUNNING"
    robot.planner_execute(run, goal_pose, duration)
    return {"task_run_id": run["task_run_id"],
            "dispatch_receipt": {"task_run_id": run["task_run_id"],
                                 "template_hash": pins[tid],
                                 "checks": [c["name"] for c in checks],
                                 "at_ts": now_iso(now), "planner": "sim",
                                 "class_label": "fixture"}}


def task_status(bridge, args):
    _now(bridge, args)
    run = bridge.runs.get(args.get("task_run_id"))
    if run is None:
        bridge.refuse("TASK_NOT_FOUND", repr(args.get("task_run_id")),
                      "task_status", None,
                      parse_time(args["at_ts"]) if args.get("at_ts") else None)
    robot = bridge.robots[bridge.sessions[run["session_id"]]["robot_serial"]]
    return {"task_run_id": run["task_run_id"], "state": run["state"],
            "pose_digest": sha(list(robot.pose)),
            "telemetry_digest": sha({"run": run["task_run_id"],
                                     "pose": robot.pose}),
            "vendor_result": run.get("vendor_result")}


def task_abort(bridge, args):
    now, _ = _now(bridge, args)
    run = bridge.runs.get(args.get("task_run_id"))
    if run is None:
        bridge.refuse("TASK_NOT_FOUND", repr(args.get("task_run_id")),
                      "task_abort", None, now)
    session = bridge.sessions[run["session_id"]]
    if run["state"] == "RUNNING":
        robot = bridge.robots[session["robot_serial"]]
        robot.safe_stop("TASK_ABORT")
        run["state"] = "ABORTED"
        run["ended_at"] = now_iso(now)
        run["end_pose"] = list(robot.pose)
        if session["state"] == "TASK_RUNNING":
            session["state"] = "ACTIVE"
        return {"task_run_id": run["task_run_id"], "state": "ABORTED",
                "receipt": "vendor safe-stop confirmed (sim)"}
    return {"task_run_id": run["task_run_id"], "state": run["state"],
            "receipt": "no-op: run already terminal (receipted, not an error)"}


def telemetry_read(bridge, args):
    _now(bridge, args)
    session = _live_session(bridge, args, "telemetry_read")
    robot = bridge.robots[session["robot_serial"]]
    trace = session["pose_trace"][-50:]
    return {"serial": robot.serial, "state": robot.state,
            "pose": list(robot.pose), "pose_trace": trace,
            "telemetry_digest": sha({"trace": trace, "serial": robot.serial}),
            "class_label": "fixture (sim telemetry)"}


def image_read(bridge, args):
    now, _ = _now(bridge, args)
    session = _live_session(bridge, args, "image_read")
    robot = bridge.robots[session["robot_serial"]]
    receipt = {"source": args.get("source", "sim_cam"),
               "image_hash": sha({"pose": robot.pose, "at": now_iso(now),
                                  "source": args.get("source", "sim_cam")}),
               "class_label": "fixture (sim image; hash receipt only)"}
    session["images"].append(receipt)
    return receipt


def session_close(bridge, args):
    now, _ = _now(bridge, args)
    session = _live_session(bridge, args, "session_close")
    if session["state"] not in ("OPEN", "ACTIVE", "TASK_RUNNING"):
        bridge.refuse("SESSION_ALREADY_ENDED", session["state"],
                      "session_close", session, now)
    running = [r for r in bridge.runs.values()
               if r["session_id"] == session["session_id"]
               and r["state"] == "RUNNING"]
    if running:
        bridge.refuse("TASK_STILL_RUNNING", running[0]["task_run_id"],
                      "session_close", session, now)
    bridge._end_session(session, "SEALED", "SESSION_CLOSED", now)
    pack = bridge.packs[session["pack_id"]]
    return {"pack_id": pack["pack_id"], "pack_hash": pack["pack_hash"],
            "pack": pack,
            "verdict_inputs": {"refusals": len(pack["refusals"]),
                               "dispatches": len(pack["dispatches"]),
                               "gaps": len(pack["gaps"]),
                               "overrides": len(pack["overrides"])}}


# --------------------------------------------------------- operator (6)
def mandate_register(bridge, args):
    now, _ = _now(bridge, args)
    tool = "mandate_register"
    mandate = args.get("mandate")
    require_container_param(mandate, "mandate", "object")
    mandate = json.loads(json.dumps(mandate))
    msg = canonical({k: v for k, v in mandate.items()
                     if k not in ("herald_signature", "state")})
    try:
        ok = herald_sig.verify(bridge.herald_pub, msg,
                               bytes.fromhex(mandate.get("herald_signature", "")))
    except Exception:
        ok = False
    if not ok:
        bridge.refuse("MANDATE_SIGNATURE_INVALID",
                      "mandate must carry a Herald signature from the human "
                      "principal", tool, None, now)
    violations = gauge_check_mandate_doc(mandate, bridge.limits)
    if violations:
        first = violations[0]
        code = first.split(":")[0].split(" ")[0]
        if code not in ("CEILING_EXCEEDS_VENDOR_RATED", "ROBOT_WILDCARD_REFUSED",
                        "TIME_WINDOW_VIOLATION"):
            code = "CEILING_EXCEEDS_VENDOR_RATED" if "CEILING" in first else \
                ("ROBOT_WILDCARD_REFUSED" if "WILDCARD" in first else
                 "TIME_WINDOW_VIOLATION")
        bridge.refuse(code, "Gauge ENVELOPE_UNSOUND at registration: "
                      + "; ".join(violations), tool, None, now)
    bridge.mandates[mandate["mandate_id"]] = mandate
    return {"mandate_id": mandate["mandate_id"], "state": "ACTIVE",
            "mandate_hash": mandate_hash_of(mandate),
            "gauge": "ENVELOPE_SOUND"}


def mandate_revoke(bridge, args):
    now, _ = _now(bridge, args)
    bridge.verify_operator_approval(args, "mandate_revoke",
                                    args.get("mandate_id"))
    mid = args.get("mandate_id")
    if mid not in bridge.mandates:
        bridge.refuse("MANDATE_NOT_FOUND", repr(mid), "mandate_revoke", None, now)
    bridge.revoked_mandates.add(mid)
    stopped = []
    for session in list(bridge.sessions.values()):
        if session["mandate_id"] == mid and session["state"] in (
                "OPEN", "ACTIVE", "TASK_RUNNING"):
            robot = bridge.robots[session["robot_serial"]]
            for run in bridge.runs.values():
                if run["session_id"] == session["session_id"] \
                        and run["state"] == "RUNNING":
                    robot.safe_stop("MANDATE_REVOKED")
                    run["state"] = "STOPPED_EXPIRED"
                    run["ended_at"] = now_iso(now)
            session["stops"].append({"class": "MANDATE_EXPIRED_STOP",
                                     "cause": "REVOKED",
                                     "final_pose": list(robot.pose),
                                     "at_ts": now_iso(now)})
            bridge._end_session(session, "ENDED_MANDATE_EXPIRED",
                                "MANDATE_EXPIRED_STOP", now)
            stopped.append(session["session_id"])
    return {"mandate_id": mid, "state": "REVOKED", "sessions_stopped": stopped}


def template_register(bridge, args):
    now, _ = _now(bridge, args)
    tool = "template_register"
    if args.get("_surface") == "agent":
        bridge.refuse("TEMPLATE_AUTHORING_REFUSED",
                      "agents invoke templates, never author (M4)", tool, None, now)
    template = args.get("template")
    require_container_param(template, "template", "object")
    template = json.loads(json.dumps(template))
    thash = template_hash_of(template)
    try:
        ok = herald_sig.verify(bridge.herald_pub, thash.encode(),
                               bytes.fromhex(template.get("herald_pin_signature", "")))
    except Exception:
        ok = False
    if not ok:
        bridge.refuse("TASK_TEMPLATE_PIN_MISMATCH",
                      "template pin signature does not verify against its hash",
                      tool, None, now)
    violations = gauge_check_template_doc(template, bridge.limits)
    if violations:
        bridge.refuse("PARAMETER_SCHEMA_VIOLATION",
                      "Gauge: " + "; ".join(violations), tool, None, now)
    template["template_hash"] = thash
    bridge.templates[template["template_id"]] = template
    return {"template_id": template["template_id"], "template_hash": thash,
            "state": "ACTIVE", "human_author_id": template["human_author_id"]}


def template_revoke(bridge, args):
    now, _ = _now(bridge, args)
    bridge.verify_operator_approval(args, "template_revoke",
                                    args.get("template_id"))
    tid = args.get("template_id")
    if tid not in bridge.templates:
        bridge.refuse("TASK_TEMPLATE_NOT_IN_MANDATE", repr(tid),
                      "template_revoke", None, now)
    bridge.revoked_templates.add(tid)
    return {"template_id": tid, "state": "REVOKED",
            "note": "in-flight runs continue to safe boundary (§3.5); new "
                    "dispatches refuse TEMPLATE_REVOKED"}


def site_freeze_set(bridge, args):
    now, _ = _now(bridge, args)
    bridge.verify_operator_approval(args, "site_freeze_set",
                                    str(bool(args.get("frozen"))))
    bridge.frozen = bool(args.get("frozen"))
    bridge.freeze_reason = args.get("reason") if bridge.frozen else None
    return {"frozen": bridge.frozen, "reason": bridge.freeze_reason,
            "at_ts": now_iso(now),
            "note": "operator act only (§5.6); reads + evidence continue"}


def session_reattest(bridge, args):
    now, _ = _now(bridge, args)
    bridge.verify_operator_approval(args, "session_reattest",
                                    args.get("session_id"))
    session = bridge.sessions.get(args.get("session_id"))
    if session is None:
        bridge.refuse("SESSION_NOT_FOUND", repr(args.get("session_id")),
                      "session_reattest", None, now)
    robot = bridge.robots[session["robot_serial"]]
    record = {"session_id": session["session_id"],
              "pose": list(robot.pose), "task_state": robot.state,
              "vendor_fault_state": "NONE (sim)",
              "telemetry_tail_digest": sha(session["pose_trace"]),
              "human_clearance": bool(args.get("human_clearance")),
              "operator_id": args.get("operator_id"), "at_ts": now_iso(now),
              "elements": ["pose", "task_state", "vendor_fault_state",
                           "telemetry_tail"]}
    bridge.reattestations.append(record)
    bridge.reattest_required.discard(session["robot_serial"])
    if session["end_cause"] == "HUMAN_OVERRIDE" and record["human_clearance"]:
        bridge.override_uncleared.discard(session["mandate_id"])
        record["override_cleared"] = True
    return {"reattestation": record,
            "note": "clearance record only — the dead session never resumes; "
                    "a new session opens at T0 (§9.2/§9.3)"}


# ------------------------------------------------------------ proof (3)
def pack_verify(bridge, args):
    pack = args.get("pack")
    require_container_param(pack, "pack", "object")
    failing = []

    def check(name, ok):
        if not ok:
            failing.append(name)
    prev = "GENESIS"
    chain = pack.get("chain") or []
    order = ("robot", "mandate", "templates", "session", "dispatches",
             "telemetry", "receipts", "refusals", "gaps", "overrides",
             "stops", "custody")
    if [c.get("element") for c in chain] != list(order):
        failing.append("chain")
    for entry, name in zip(chain, order):
        h = sha({"prev": prev, "element": name, "body": pack.get(name)})
        if h != entry.get("hash"):
            failing.append(name)
        prev = h
    check("pack_hash", prev == pack.get("pack_hash"))
    # Proof re-verifies the pack hash chain + template pins + robot
    # attestation offline; mandate signature was verified by the bridge
    # at registration and at session_open (M1), and the sealed mandate
    # element (id + hash + signature) is chain-bound above.
    for t in pack.get("templates") or []:
        body_ok = t.get("template_hash") and len(t["template_hash"]) == 64
        check("templates", bool(body_ok))
        try:
            pin_ok = herald_sig.verify(
                bridge.herald_pub, t["template_hash"].encode(),
                bytes.fromhex(t.get("herald_pin_signature", "")))
        except Exception:
            pin_ok = False
        check("template_pin", pin_ok)
    robot = pack.get("robot") or {}
    att = {k: robot.get(k) for k in
           ("serial", "model", "robot_class", "firmware_version", "method")}
    check("robot_attestation", sha(att) == robot.get("attestation_hash"))
    verdict = "TASK_VERIFIED" if not failing else "TASK_UNVERIFIED"
    return {"verdict": verdict,
            "failing_elements": sorted(set(failing)),
            "note": "Proof grades Tether packs: pack internally valid + "
                    "attested; never 'the task was safe' (spec §5.4)"}


def _mandate_body(pack):
    return pack.get("mandate") or {}


def pack_render(bridge, args):
    pack = args.get("pack")
    require_container_param(pack, "pack", "object")
    lines = [f"Evidence pack {pack.get('pack_id')} (Blackbox form, §7.2)",
             f"robot: {(pack.get('robot') or {}).get('serial')} "
             f"end_cause: {(pack.get('session') or {}).get('end_cause')}"]
    for d in pack.get("dispatches") or []:
        lines.append(f"dispatch {d.get('task_run_id')} template="
                     f"{d.get('template_id')} state={d.get('state')} "
                     f"params={json.dumps(d.get('parameters'), sort_keys=True)}")
    for r in pack.get("refusals") or []:
        lines.append(f"REFUSAL {r.get('class')} tool={r.get('tool')} "
                     f"detail={r.get('detail')}")
    for g in pack.get("gaps") or []:
        lines.append(f"GAP {g.get('gap_cause')} robot_state_after="
                     f"{g.get('robot_state_after')}")
    for o in pack.get("overrides") or []:
        lines.append(f"OVERRIDE {o.get('source')} final_pose={o.get('final_pose')}")
    for s in pack.get("stops") or []:
        lines.append(f"STOP {s.get('class')} final_pose={s.get('final_pose')}")
    return {"rendering": "\n".join(lines),
            "refusals_rendered": len(pack.get("refusals") or []),
            "note": "verbatim from pack; no refusal, gap or override dropped"}


def pack_compare(bridge, args):
    a, b = args.get("pack_a"), args.get("pack_b")
    require_container_param(a, "pack_a", "object")
    require_container_param(b, "pack_b", "object")
    diffs = []
    for name in ("robot", "mandate", "templates", "session", "dispatches",
                 "telemetry", "receipts", "refusals", "gaps", "overrides",
                 "stops", "custody"):
        if sha(a.get(name)) != sha(b.get(name)):
            diffs.append(name)
    return {"divergent_elements": diffs,
            "same_pack_hash": a.get("pack_hash") == b.get("pack_hash")}


# ------------------------------------------------------------ gauge (4)
def gauge_check_mandate(bridge, args):
    mandate = args.get("mandate")
    require_container_param(mandate, "mandate", "object")
    v = gauge_check_mandate_doc(mandate, bridge.limits)
    return {"verdict": "ENVELOPE_SOUND" if not v else "ENVELOPE_UNSOUND",
            "violations": v}


def gauge_check_template(bridge, args):
    template = args.get("template")
    require_container_param(template, "template", "object")
    v = gauge_check_template_doc(template, bridge.limits)
    return {"verdict": "ENVELOPE_SOUND" if not v else "ENVELOPE_UNSOUND",
            "violations": v}


def gauge_check_pair(bridge, args):
    mandate, template = args.get("mandate"), args.get("template")
    require_container_param(mandate, "mandate", "object")
    require_container_param(template, "template", "object")
    v = gauge_check_mandate_doc(mandate, bridge.limits) \
        + gauge_check_template_doc(template, bridge.limits)
    thash = template_hash_of(template)
    pins = {p["template_id"]: p["template_hash"]
            for p in mandate.get("template_pins") or []}
    if pins.get(template["template_id"]) != thash:
        v.append("TASK_TEMPLATE_PIN_MISMATCH: mandate pin != template hash")
    robot_classes = {bridge.robots[s].robot_class
                     for s in mandate.get("robot_serials") or []
                     if s in bridge.robots}
    if robot_classes and template.get("robot_class") not in robot_classes:
        v.append(f"ROBOT_CLASS_MISMATCH: template {template.get('robot_class')} "
                 f"vs mandate robots {sorted(robot_classes)}")
    req = template.get("required_occupancy_class") or template.get("required_envelope_class")
    from tether_engine import OCCUPANCY_RANK
    occ = mandate.get("occupancy_class")
    if req in OCCUPANCY_RANK:
        if not occ:
            v.append("OCCUPANCY_UNKNOWN_OBSERVE_ONLY: template requires "
                     f"{req}, mandate declares none")
        elif OCCUPANCY_RANK[occ] < OCCUPANCY_RANK[req]:
            v.append(f"OCCUPANCY_INCOMPATIBLE: template requires {req}, "
                     f"mandate declares {occ}")
    req_vol = template.get("required_volume_min") or {}
    env_vol = (mandate.get("envelope") or {}).get("volume") or {}
    if req_vol and env_vol.get("geometry") == "box":
        dims = [env_vol["max"][i] - env_vol["min"][i] for i in range(3)]
        for axis, need in req_vol.items():
            idx = {"x": 0, "y": 1, "z": 2}[axis]
            if dims[idx] < need:
                v.append(f"ENVELOPE_SMALLER_THAN_TEMPLATE_REQUIREMENT: "
                         f"{axis} {dims[idx]} < {need}")
    rated = bridge.limits.get(template.get("robot_class")) or {}
    resolved, disagreements = {}, []
    for field in ("max_speed_mps", "max_force_n", "max_payload_kg"):
        cands = {}
        if (mandate.get("ceilings") or {}).get(field) is not None:
            cands["mandate"] = mandate["ceilings"][field]
        if (template.get("ceiling_defaults") or {}).get(field) is not None:
            cands["template"] = template["ceiling_defaults"][field]
        if rated.get(field) is not None:
            cands["vendor_rated"] = rated[field]
        if cands:
            resolved[field] = min(cands.values())
            if len(set(cands.values())) > 1:
                disagreements.append(f"{field}: {cands} -> min "
                                     f"{resolved[field]} (lower wins, Law 6)")
    return {"verdict": "ENVELOPE_SOUND" if not v else "ENVELOPE_UNSOUND",
            "violations": sorted(set(v)),
            "resolved_ceilings": resolved, "disagreements": disagreements}


def gauge_limits_list(bridge, args):
    rc = args.get("robot_class")
    row = bridge.limits.get(rc)
    if row is None:
        raise ToolError(f"ROBOT_CLASS_UNKNOWN: {rc!r} not in shipped limits "
                        "table (sim classes only in P0)")
    return {"robot_class": rc, "limits": row,
            "note": "vendor rated limits as shipped (source-cited, "
                    "version-stamped); data for Law 6 tighten-only checks, "
                    "never a safety claim"}


AGENT_TOOLS = {
    "fleet_discover": fleet_discover, "session_open": session_open,
    "task_templates_list": task_templates_list, "task_dispatch": task_dispatch,
    "task_status": task_status, "task_abort": task_abort,
    "telemetry_read": telemetry_read, "image_read": image_read,
    "session_close": session_close,
}
OPERATOR_TOOLS = {
    "mandate_register": mandate_register, "mandate_revoke": mandate_revoke,
    "template_register": template_register, "template_revoke": template_revoke,
    "site_freeze_set": site_freeze_set, "session_reattest": session_reattest,
}
TOOL_TOOLS = {
    "pack_verify": pack_verify, "pack_render": pack_render,
    "pack_compare": pack_compare, "gauge_check_mandate": gauge_check_mandate,
    "gauge_check_template": gauge_check_template,
    "gauge_check_pair": gauge_check_pair, "gauge_limits_list": gauge_limits_list,
}

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
