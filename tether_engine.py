#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Tether engine — Herald-signed mandate enforcement at a sim site bridge.

"""Eclipse Tether engine — governed robot task authority (P0, SIM ONLY).

Spec: eclipse-tether-spec-20261025.md. P0 substrate = ROS 2 + Gazebo +
UR-class arm, represented here by an in-process simulated robot behind
the bridge (planner: sim, class: fixture). No real motion, no hardware
calls, no vendor SDK exists in this build.

Novel mechanism (spec §1.1, M1-M10): physical task authority is
exercised only inside a Herald-signed mandate pinning agent x robot
serials x human-authored task-template hashes x workspace envelope x
speed/force ceilings x occupancy class x time window, enforced at the
site bridge (only routed path), with every session — including
refusals, gaps, stops, overrides — sealed into a Blackbox-form
evidence pack verifiable offline (Tether Proof).

SAFETY LAW (spec §3, binding): a mandate NEVER substitutes for a site
risk assessment; ceilings are outputs of a human risk assessment,
entered by humans; NO T2 direct motion surface exists in v0/v1;
occupancy is human-declared, unknown = T0 observe-only; human stop
authority is absolute (HUMAN_OVERRIDE terminal); vendor safety systems
are outside the type system (absent, not gated).

House guards pre-installed: coerce_int_param, parse_time,
require_container_param / require_reference (reference-type guard),
verified-approval pattern for operator T3 verbs (approval signature
re-verified at use time), deep-key scan of dispatch parameters,
schema-enumerating validation.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import herald_sig

HERE = Path(__file__).parent
ENGINE_VERSION = "tether-0.1.0-sim"
PRODUCT = "eclipse-tether"

# Spec §6.4 refusal vocabulary — verbatim, closed for P0.
REFUSALS = (
    "MANDATE_NOT_FOUND", "MANDATE_SIGNATURE_INVALID", "MANDATE_REVOKED",
    "MANDATE_NOT_YET_VALID", "MANDATE_EXPIRED", "MANDATE_EXPIRED_STOP",
    "AGENT_NOT_IN_MANDATE", "ROBOT_NOT_IN_MANDATE",
    "ROBOT_WILDCARD_REFUSED", "SERIAL_MISMATCH",
    "TASK_TEMPLATE_PIN_MISMATCH", "TASK_TEMPLATE_NOT_IN_MANDATE",
    "TEMPLATE_REVOKED", "TEMPLATE_AUTHORING_REFUSED",
    "PARAMETER_SCHEMA_VIOLATION",
    "ENVELOPE_VIOLATION", "ENVELOPE_EXIT_STOP",
    "CEILING_EXCEEDS_VENDOR_RATED", "CEILING_EXCEEDS_MANDATE",
    "CEILING_BREACH_STOP",
    "OCCUPANCY_UNKNOWN_OBSERVE_ONLY", "OCCUPANCY_INSUFFICIENT",
    "OCCUPANCY_UPGRADE_REFUSED", "TIME_WINDOW_VIOLATION",
    "T2_DIRECT_MOTION_REFUSED", "SAFETY_SYSTEM_ACCESS_REFUSED",
    "ESTOP_INTERFERENCE_REFUSED", "WEAPONIZATION_REFUSED",
    "SESSION_NOT_FOUND", "SESSION_ALREADY_ENDED", "TASK_STILL_RUNNING",
    "TASK_NOT_FOUND", "BRIDGE_HEARTBEAT_LOST", "LEASE_UNAVAILABLE",
    "LEASE_HELD_BY_HUMAN", "SITE_FROZEN", "EVIDENCE_PACK_UNAVAILABLE",
    "SESSION_STATE_UNKNOWN_REATTEST_REQUIRED", "HUMAN_OVERRIDE",
)
OCCUPANCY_CLASSES = ("UNOCCUPIED", "SUPERVISED", "SHARED")
OCCUPANCY_RANK = {"UNOCCUPIED": 1, "SUPERVISED": 2, "SHARED": 3}

# Deep-key scan (spec §3.3 / §6.4): motion-stream, escape-hatch,
# safety-system and e-stop keys must never appear inside dispatch
# parameters at any depth.
T2_KEYS = {"velocity", "joint", "joints", "joint_angles", "torque",
           "trajectory", "twist", "cmd_vel", "servo", "topic",
           "service", "script", "command", "shell", "raw_motion"}
SAFETY_KEYS = {"safety_config", "collision_detection", "protective_stop",
               "speed_and_separation", "power_force_limiting",
               "safety_rated_stop", "safety_system"}
ESTOP_KEYS = {"estop_register", "estop_suppress", "estop_disable",
              "override_suppress", "lease_retake"}
WEAPON_KEYS = {"weapon", "weaponize", "payload_harm", "harm_target"}
OCCUPANCY_KEYS = {"occupancy_class", "occupancy", "supervisor_id"}


class ToolError(Exception):
    pass


class Refusal(Exception):
    """Named product refusal (spec §6.4), always receipted."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ------------------------------------------------------- house guards
_INT_SHAPED_RE = re.compile(r"^[+-]?\d+$")
_OFFSET_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def coerce_int_param(value, name, refusal):
    """House reference guard: real ints, int-shaped strings, integral
    floats pass; bools and everything else refuse BY NAME."""
    if isinstance(value, bool):
        raise ToolError(f"{refusal}: {name} must be an integer, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_SHAPED_RE.match(value.strip()):
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ToolError(f"{refusal}: {name} must be an integer (got "
                    f"{type(value).__name__}); refused by name")


def parse_time(value, field="time"):
    """House reference guard: ISO-8601 only with explicit offset;
    offset-less timestamps refuse BY NAME — never guessed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ToolError(f"PARSE_TIME_NO_OFFSET: {field} carries no UTC offset")
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"PARSE_TIME_INVALID: {field} must be an ISO-8601 "
                        "timestamp string with an offset")
    text = value.strip()
    if not _OFFSET_RE.search(text):
        raise ToolError(f"PARSE_TIME_NO_OFFSET: {field}={text!r} has no UTC "
                        "offset; timestamps are never guessed")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"PARSE_TIME_INVALID: {field}={text!r} is not valid "
                        "ISO-8601") from None
    if dt.tzinfo is None:
        raise ToolError(f"PARSE_TIME_NO_OFFSET: {field}={text!r}")
    return dt.astimezone(timezone.utc)


def require_container_param(value, name, expected):
    """Reference-type guard: structured params must arrive as the
    container their schema declares; refuse BY NAME at the boundary."""
    ok = isinstance(value, dict) if expected == "object" else isinstance(value, list)
    if not ok:
        raise ToolError(f"CONTAINER_TYPE_INVALID: {name} must be an {expected} "
                        f"(got {type(value).__name__}); refused by name")
    return value


def require_reference(value, name):
    """Reference-type guard for record refs: string id or record object."""
    if isinstance(value, (str, dict)):
        return value
    raise ToolError(f"REFERENCE_TYPE_INVALID: {name} must be a string ref or a "
                    f"record object (got {type(value).__name__})")


def deep_key_scan(obj, path="$"):
    """Deep-key scan: yields (key, path) for every dict key at any depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), f"{path}.{k}"
            yield from deep_key_scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from deep_key_scan(v, f"{path}[{i}]")


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def sha(obj) -> str:
    if isinstance(obj, (bytes, str)):
        return hashlib.sha256(obj if isinstance(obj, bytes) else obj.encode()).hexdigest()
    return hashlib.sha256(canonical(obj)).hexdigest()


def now_iso(dt=None) -> str:
    return (dt or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()


def _uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _load_json(path, default=None):
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    return default


# ------------------------------------------------------- vendor limits
def limits_table(fixtures_dir):
    data = _load_json(Path(fixtures_dir) / "vendor_limits.json", {"classes": []})
    return {row["robot_class"]: row for row in data["classes"]}


def gauge_check_mandate_doc(mandate, limits):
    """Gauge grammar over a mandate document (spec §5.5). Returns
    deterministic-ordered violation strings; empty list = SOUND."""
    v = []
    if not isinstance(mandate, dict):
        return ["MANDATE_NOT_OBJECT"]
    serials = mandate.get("robot_serials")
    if not isinstance(serials, list) or not serials:
        v.append("SERIALS_ABSENT")
    else:
        for s in serials:
            if not isinstance(s, str) or s.strip() in ("*", "") or "*" in s:
                v.append(f"ROBOT_WILDCARD_REFUSED: serial {s!r} is not concrete")
    window = mandate.get("window") or {}
    if not window.get("expires_at"):
        v.append("EXPIRY_ABSENT")
    else:
        try:
            parse_time(window["expires_at"], "window.expires_at")
            if window.get("not_before"):
                parse_time(window["not_before"], "window.not_before")
        except ToolError as e:
            v.append(f"TIME_WINDOW_VIOLATION: {e}")
    ceilings = mandate.get("ceilings") or {}
    robot_class = mandate.get("robot_class")
    rated = limits.get(robot_class) if robot_class else None
    if ceilings and rated:
        for field, key in (("max_speed_mps", "max_speed_mps"),
                           ("max_force_n", "max_force_n"),
                           ("max_payload_kg", "max_payload_kg")):
            if ceilings.get(field) is not None and ceilings[field] > rated[key]:
                v.append(f"CEILING_EXCEEDS_VENDOR_RATED: {field}="
                         f"{ceilings[field]} > rated {rated[key]} "
                         f"for {robot_class}")
    occ = mandate.get("occupancy_class")
    if occ is not None:
        if occ not in OCCUPANCY_CLASSES:
            v.append(f"OCCUPANCY_CLASS_UNKNOWN: {occ!r}")
        elif occ == "SUPERVISED" and not mandate.get("supervisor_id"):
            v.append("SUPERVISOR_ABSENT: SUPERVISED requires supervisor_id")
    env = mandate.get("envelope")
    if not env:
        v.append("ENVELOPE_ABSENT")
    else:
        frame = (env.get("frame") or "map")
        if frame != "map":
            v.append(f"ENVELOPE_FRAME_NOT_MAP_ANCHORED: frame={frame!r} "
                     "(robot-local frames refused)")
        vol = env.get("volume") or {}
        if vol.get("geometry") not in ("box", "polygon_prism"):
            v.append("ENVELOPE_GEOMETRY_UNKNOWN")
        elif vol.get("geometry") == "box":
            mn, mx = vol.get("min"), vol.get("max")
            if not (isinstance(mn, list) and isinstance(mx, list)
                    and len(mn) == 3 and len(mx) == 3
                    and all(mn[i] < mx[i] for i in range(3))):
                v.append("ENVELOPE_VOLUME_MALFORMED")
    pins = mandate.get("template_pins")
    if not isinstance(pins, list) or not pins:
        v.append("TEMPLATE_PINS_ABSENT")
    else:
        for pin in pins:
            h = (pin or {}).get("template_hash", "")
            if not (isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h)):
                v.append(f"TEMPLATE_PIN_MALFORMED: template "
                         f"{(pin or {}).get('template_id')!r}")
    if not mandate.get("risk_assessment_ref"):
        v.append("RISK_ASSESSMENT_REF_ABSENT (Safety Law 1/2: ceilings are "
                 "outputs of a human risk assessment)")
    return sorted(set(v))


def gauge_check_template_doc(template, limits):
    v = []
    if not isinstance(template, dict):
        return ["TEMPLATE_NOT_OBJECT"]
    schema = template.get("parameter_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        v.append("PARAMETER_SCHEMA_MALFORMED")
    else:
        for key, _ in deep_key_scan(schema.get("properties", {})):
            lk = key.lower()
            if lk in T2_KEYS:
                v.append(f"T2_CONTENT_IN_TEMPLATE: parameter {key!r} is a "
                         "direct-motion field (Safety Law 3)")
            if lk in SAFETY_KEYS:
                v.append(f"SAFETY_SYSTEM_ACCESS_REFUSED: parameter {key!r}")
    if not template.get("required_envelope_class"):
        v.append("REQUIRED_ENVELOPE_CLASS_ABSENT")
    if not template.get("human_author_id"):
        v.append("HUMAN_AUTHOR_ABSENT (agents invoke, never author — M4)")
    defaults = template.get("ceiling_defaults") or {}
    rated = limits.get(template.get("robot_class"))
    if defaults and rated:
        for field in ("max_speed_mps", "max_force_n", "max_payload_kg"):
            if defaults.get(field) is not None and defaults[field] > rated[field]:
                v.append(f"CEILING_EXCEEDS_VENDOR_RATED: template default "
                         f"{field}={defaults[field]} > rated {rated[field]}")
    return sorted(set(v))


def template_hash_of(template):
    body = {k: v for k, v in template.items()
            if k not in ("herald_pin_signature", "template_hash", "state")}
    return sha(body)


def mandate_hash_of(mandate):
    body = {k: v for k, v in mandate.items()
            if k not in ("herald_signature", "state")}
    return sha(body)


# ------------------------------------------------------- sim robot
class SimRobot:
    """Gazebo/UR-arm stand-in (planner: sim, class: fixture). The ONLY
    motion path in P0; reachable exclusively through the Bridge."""

    def __init__(self, record):
        self.serial = record["serial"]
        self.model = record["model"]
        self.robot_class = record["robot_class"]
        self.firmware = record["firmware_version"]
        self.pose = list(record.get("home_pose", [0.0, 0.0, 0.5]))
        self.state = "IDLE"
        self.vendor_calls = []  # every vendor-surface call, for audit

    def attestation(self):
        body = {"serial": self.serial, "model": self.model,
                "robot_class": self.robot_class,
                "firmware_version": self.firmware, "method": "sim-api-response"}
        body["attestation_hash"] = sha(body)
        return body

    def planner_execute(self, run, goal, duration_s):
        self.vendor_calls.append({"call": "planner_execute",
                                  "template_id": run["template_id"],
                                  "goal": goal, "planner": "sim"})
        self.state = "RUNNING"

    def safe_stop(self, cause):
        self.vendor_calls.append({"call": "safe_stop", "cause": cause,
                                  "planner": "sim"})
        self.state = "IDLE"


# ------------------------------------------------------- bridge
class Bridge:
    """Site bridge (spec §5.1): holds registry, sessions, leases, packs.
    Sim control (e-stop / lease grab / heartbeat / evidence) is read
    from fixtures/sim_control.json — the simulated vendor endpoints."""

    def __init__(self, fixtures_dir):
        self.fx = Path(fixtures_dir)
        keys = _load_json(self.fx / "keys.json", {})
        self.herald_pub = bytes.fromhex(keys["herald_pubkey"])
        self.agents = keys.get("agents", {})        # card_id -> pubkey hex
        self.operators = keys.get("operators", {})  # op_id -> pubkey hex
        self.limits = limits_table(self.fx)
        robots = _load_json(self.fx / "robots.json", {"robots": []})["robots"]
        self.robots = {r["serial"]: SimRobot(r) for r in robots}
        self.mandates = {}       # mandate_id -> registered mandate
        self.templates = {}      # template_id -> registered template
        self.revoked_mandates = set()
        self.revoked_templates = set()
        self.sessions = {}       # session_id -> session record
        self.runs = {}           # task_run_id -> run record
        self.packs = {}          # pack_id -> sealed pack
        self.leases = {}         # serial -> session_id
        self.frozen = False
        self.freeze_reason = None
        self.bridge_log = []     # hash-chained bridge log (refusals at open etc.)
        self.override_uncleared = set()   # mandate_ids blocked by HUMAN_OVERRIDE
        self.reattest_required = set()    # serials needing §9.2 re-attestation
        self.reattestations = []          # clearance records
        self.pack_writer_ok = True

    # ---- chain / receipts
    def _chain(self, store_list, record):
        prev = store_list[-1]["record_hash"] if store_list else "GENESIS"
        record["prev_hash"] = prev
        record["record_hash"] = sha({k: v for k, v in record.items()
                                     if k != "record_hash"})
        store_list.append(record)
        return record

    def sim_control(self):
        return _load_json(self.fx / "sim_control.json", {}) or {}

    def refuse(self, code, detail, tool, session=None, at=None):
        """Receipt a named refusal; session-bound refusals enter the
        session's refusal list (pack content), others the bridge log."""
        receipt = {"product": PRODUCT, "record_id": _uid("refusal"),
                   "refusal_id": _uid("rcpt"), "tool": tool, "class": code,
                   "detail": detail, "robot_moved": False,
                   "session_id": session["session_id"] if session else None,
                   "at_ts": now_iso(at), "class_label": "fixture-clock"
                   if at else "bridge-clock"}
        if session is not None:
            session["refusals"].append(receipt)
        else:
            self._chain(self.bridge_log, dict(receipt))
        raise Refusal(code, detail)

    # ---- verified approval (house pattern for operator T3 verbs)
    def verify_operator_approval(self, args, action, subject):
        op_id = args.get("operator_id")
        sig_hex = args.get("approval_signature")
        pub_hex = self.operators.get(op_id or "")
        if not pub_hex or not sig_hex:
            raise ToolError("APPROVAL_UNVERIFIED: operator T3 verb requires "
                            "operator_id + approval_signature, verified at "
                            "use time (house verified-approval pattern)")
        msg = canonical({"action": action, "subject": subject,
                         "operator_id": op_id})
        try:
            sig = bytes.fromhex(sig_hex)
        except ValueError:
            raise ToolError("APPROVAL_UNVERIFIED: approval_signature is not hex")
        if not herald_sig.verify(bytes.fromhex(pub_hex), msg, sig):
            raise ToolError("APPROVAL_UNVERIFIED: approval signature does not "
                            "verify against the operator key at use time")

    # ---- clock
    def clock(self, args):
        at = args.get("at_ts")
        if at is not None:
            return parse_time(at, "at_ts"), True
        return datetime.now(timezone.utc), False

    # ---- monitors (§3.5, §9.2, §9.3) — run at every tool entry
    def tick(self, now):
        ctl = self.sim_control()
        for session in list(self.sessions.values()):
            if session["state"] not in ("OPEN", "ACTIVE", "TASK_RUNNING"):
                continue
            robot = self.robots[session["robot_serial"]]
            running = [r for r in self.runs.values()
                       if r["session_id"] == session["session_id"]
                       and r["state"] == "RUNNING"]
            # human supremacy first
            if ctl.get("estop") or ctl.get("lease_grabbed_by_human") \
                    or ctl.get("local_control"):
                source = "ESTOP" if ctl.get("estop") else \
                    ("LEASE_GRAB" if ctl.get("lease_grabbed_by_human")
                     else "LOCAL_CONTROL")
                for run in running:
                    robot.safe_stop("HUMAN_OVERRIDE")
                    run["state"] = "STOPPED_OVERRIDE"
                    run["ended_at"] = now_iso(now)
                session["overrides"].append(
                    {"session_id": session["session_id"], "source": source,
                     "detected_via": "sim-vendor-endpoint (class: fixture)",
                     "vendor_stop_confirmed": True,
                     "final_pose": list(robot.pose), "at_ts": now_iso(now)})
                self.override_uncleared.add(session["mandate_id"])
                self.reattest_required.add(session["robot_serial"])
                self._end_session(session, "ENDED_HUMAN_OVERRIDE",
                                  "HUMAN_OVERRIDE", now)
                continue
            if ctl.get("heartbeat_ok") is False and running:
                # Comms loss with a task in flight: safe-stop + DROPPED
                # (§9.2). An idle session has nothing to stop; its next
                # dispatch refuses BRIDGE_HEARTBEAT_LOST at the gate.
                for run in running:
                    robot.safe_stop("COMMS_LOSS")
                    run["state"] = "FAILED_VENDOR"
                    run["ended_at"] = now_iso(now)
                session["gaps"].append(
                    {"session_id": session["session_id"],
                     "gap_cause": "COMMS_LOSS",
                     "last_known_pose": list(robot.pose),
                     "telemetry_tail_digest": sha(session["pose_trace"]),
                     "robot_state_after": "UNKNOWN"})
                self.reattest_required.add(session["robot_serial"])
                self._end_session(session, "DROPPED", "COMMS_LOSS", now)
                continue
            mandate = self.mandates.get(session["mandate_id"])
            for run in list(running):
                expires = parse_time(mandate["window"]["expires_at"])
                if now >= expires:
                    robot.safe_stop("MANDATE_EXPIRED_STOP")
                    run["state"] = "STOPPED_EXPIRED"
                    run["ended_at"] = now_iso(now)
                    session["stops"].append(
                        {"class": "MANDATE_EXPIRED_STOP",
                         "cause": "EXPIRED", "final_pose": list(robot.pose),
                         "at_ts": now_iso(now)})
                    self._end_session(session, "ENDED_MANDATE_EXPIRED",
                                      "MANDATE_EXPIRED_STOP", now)
                    break
                elapsed = (now - parse_time(run["started_at"])).total_seconds()
                frac = min(1.0, elapsed / max(run["duration_s"], 0.001))
                start, goal = run["start_pose"], run["goal_pose"]
                pose = [start[i] + (goal[i] - start[i]) * frac for i in range(3)]
                drift = run["parameters"].get("sim_drift_m") or 0.0
                if drift and frac >= 0.5:
                    pose = [pose[0] + drift, pose[1], pose[2]]
                robot.pose = pose
                session["pose_trace"].append(
                    {"at_ts": now_iso(now), "pose": list(pose)})
                env = mandate["envelope"]["volume"]
                if not _inside(env, pose):
                    robot.safe_stop("ENVELOPE_EXIT_STOP")
                    run["state"] = "STOPPED_ENVELOPE_EXIT"
                    run["ended_at"] = now_iso(now)
                    session["stops"].append(
                        {"class": "ENVELOPE_EXIT_STOP",
                         "final_pose": list(pose), "at_ts": now_iso(now)})
                    self._end_session(session, "ENDED_ENVELOPE_EXIT",
                                      "ENVELOPE_EXIT_STOP", now)
                    break
                overspeed = run["parameters"].get("sim_overspeed_mps")
                if overspeed and frac >= 0.5 and \
                        overspeed > mandate["ceilings"]["max_speed_mps"]:
                    robot.safe_stop("CEILING_BREACH_STOP")
                    run["state"] = "STOPPED_CEILING"
                    run["ended_at"] = now_iso(now)
                    session["stops"].append(
                        {"class": "CEILING_BREACH_STOP",
                         "final_pose": list(pose), "at_ts": now_iso(now)})
                    self._end_session(session, "ENDED_CEILING_BREACH",
                                      "CEILING_BREACH_STOP", now)
                    break
                if frac >= 1.0:
                    run["state"] = "SUCCEEDED"
                    run["ended_at"] = now_iso(now)
                    run["end_pose"] = list(pose)
                    run["vendor_result"] = {"result": "SUCCEEDED",
                                            "planner": "sim"}
                    robot.state = "IDLE"
                    session["state"] = "ACTIVE"

    def _end_session(self, session, state, cause, now):
        session["state"] = state
        session["end_cause"] = cause
        session["closed_at"] = now_iso(now)
        self.leases.pop(session["robot_serial"], None)
        self._seal_pack(session, now)

    def _seal_pack(self, session, now):
        if session.get("pack_id") and session["pack_id"] in self.packs:
            return self.packs[session["pack_id"]]
        mandate = self.mandates[session["mandate_id"]]
        robot = self.robots[session["robot_serial"]]
        runs = [r for r in self.runs.values()
                if r["session_id"] == session["session_id"]]
        pack = {
            "pack_id": session["pack_id"], "product": PRODUCT,
            "class_label": "fixture (P0 simulator)",
            "robot": session["attestation"],
            "mandate": {"mandate_id": mandate["mandate_id"],
                        "mandate_hash": mandate_hash_of(mandate),
                        "herald_signature": mandate["herald_signature"],
                        "principal": mandate["principal"],
                        "risk_assessment_ref": mandate["risk_assessment_ref"],
                        "occupancy_class": mandate.get("occupancy_class"),
                        "window": mandate["window"]},
            "templates": [{"template_id": t["template_id"],
                           "template_hash": template_hash_of(t),
                           "human_author_id": t["human_author_id"],
                           "herald_pin_signature": t["herald_pin_signature"]}
                          for t in (self.templates[tid] for tid in
                                    {r["template_id"] for r in runs}
                                    if tid in self.templates)],
            "session": {"session_id": session["session_id"],
                        "opened_at": session["opened_at"],
                        "closed_at": session.get("closed_at"),
                        "end_cause": session.get("end_cause"),
                        "lease_ref": session["lease_ref"]},
            "dispatches": runs,
            "telemetry": {"pose_trace_digest": sha(session["pose_trace"]),
                          "telemetry_digest": sha(
                              {"trace": session["pose_trace"],
                               "serial": robot.serial}),
                          "sampling": "per-tick (sim)"},
            "receipts": {"end_state_images": session["images"],
                         "end_pose": list(robot.pose),
                         "vendor_task_result":
                             runs[-1].get("vendor_result") if runs else None},
            "refusals": session["refusals"],
            "gaps": session["gaps"],
            "overrides": session["overrides"],
            "stops": session["stops"],
            "custody": {"recorder": "eclipse-tether-bridge (site)",
                        "agent_is_author": False,
                        "form": "Blackbox-form (spec §7.2)"},
        }
        elements = []
        prev = "GENESIS"
        for name in ("robot", "mandate", "templates", "session", "dispatches",
                     "telemetry", "receipts", "refusals", "gaps", "overrides",
                     "stops", "custody"):
            h = sha({"prev": prev, "element": name, "body": pack[name]})
            elements.append({"element": name, "hash": h})
            prev = h
        pack["chain"] = elements
        pack["pack_hash"] = prev
        self.packs[pack["pack_id"]] = pack
        return pack


def _inside(volume, pose):
    if volume.get("geometry") == "box":
        mn, mx = volume["min"], volume["max"]
        return all(mn[i] - 1e-9 <= pose[i] <= mx[i] + 1e-9 for i in range(3))
    return False


def _schema_validate(schema, params):
    """Closed JSON-Schema subset validation; returns violation or None."""
    if not isinstance(params, dict):
        return "parameters must be an object"
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in params:
            return f"missing required parameter {req!r}"
    if schema.get("additionalProperties") is False:
        for key in params:
            if key not in props:
                return f"parameter {key!r} not in closed schema"
    for key, val in params.items():
        spec = props.get(key)
        if not spec:
            continue
        t = spec.get("type")
        if t == "number" and not (isinstance(val, (int, float))
                                  and not isinstance(val, bool)):
            return f"parameter {key!r} must be a number"
        if t == "integer":
            try:
                coerce_int_param(val, key, "PARAMETER_SCHEMA_VIOLATION")
            except ToolError as e:
                return str(e)
        if t == "string" and not isinstance(val, str):
            return f"parameter {key!r} must be a string"
        if t == "boolean" and not isinstance(val, bool):
            return f"parameter {key!r} must be a boolean"
        if t == "object":
            if not isinstance(val, dict):
                return f"parameter {key!r} must be an object"
            sub = _schema_validate(spec, val)
            if sub:
                return f"{key}: {sub}"
        if t == "array":
            if not isinstance(val, list):
                return f"parameter {key!r} must be an array"
            item_spec = spec.get("items")
            if item_spec and item_spec.get("type") == "object":
                for item in val:
                    sub = _schema_validate(item_spec, item)
                    if sub:
                        return f"{key}[]: {sub}"
    return None


# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
