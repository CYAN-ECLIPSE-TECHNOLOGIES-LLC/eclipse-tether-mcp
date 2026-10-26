#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Builder regression tests — replicate bench shapes (T-D/H/Gauge/fuzz).

"""Builder regression tests for Eclipse Tether P0. These replicate the
Verity bench shapes byte-for-byte in scenario structure (spec §11);
they do NOT certify — Verity benches independently with own fixtures.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

import tether_fixtures as fx  # noqa: E402
import tether_ops as ops  # noqa: E402
from tether_engine import Bridge, Refusal  # noqa: E402

FXD = HERE / "fixtures"
T0 = "2026-10-25T12:00:00+00:00"


def fresh():
    b = Bridge(FXD)
    keys = fx.load_keys(FXD)
    t = fx.make_template(keys)
    m = fx.make_mandate(keys, t)
    ops.template_register(b, {"template": t})
    ops.mandate_register(b, {"mandate": m})
    return b, keys, t, m


def open_session(b, keys, m, **kw):
    args = {"mandate_artifact": m, "agent_card_id": "herald-card-w001",
            "agent_signature": fx.agent_open_sig(keys, m["mandate_id"]),
            "robot_serial": "UR5e-SIM-001", "at_ts": T0}
    args.update(kw)
    return ops.session_open(b, args)


def refusal_code(fn, *a, **k):
    try:
        fn(*a, **k)
    except Refusal as e:
        return e.code
    return None


def test_happy_and_pack():
    b, keys, t, m = fresh()
    s = open_session(b, keys, m)
    out = ops.task_dispatch(b, {"session_id": s["session_id"],
        "template_id": t["template_id"],
        "parameters": {"goal": {"x": 0.1, "y": 0.1, "z": 0.5},
                       "duration_s": 5, "speed_mps": 0.2},
        "at_ts": T0})
    st = ops.task_status(b, {"task_run_id": out["task_run_id"],
                             "at_ts": "2026-10-25T12:00:06+00:00"})
    assert st["state"] == "SUCCEEDED", st
    closed = ops.session_close(b, {"session_id": s["session_id"],
                                   "at_ts": "2026-10-25T12:00:07+00:00"})
    v = ops.pack_verify(b, {"pack": closed["pack"]})
    assert v["verdict"] == "TASK_VERIFIED", v
    tampered = copy.deepcopy(closed["pack"])
    tampered["refusals"] = [{"class": "FORGED"}]
    v2 = ops.pack_verify(b, {"pack": tampered})
    assert v2["verdict"] == "TASK_UNVERIFIED" and "refusals" in v2["failing_elements"], v2


def test_envelope_pre_motion():
    b, keys, t, m = fresh()
    s = open_session(b, keys, m)
    robot = b.robots["UR5e-SIM-001"]
    before = list(robot.pose)
    code = refusal_code(ops.task_dispatch, b,
        {"session_id": s["session_id"], "template_id": t["template_id"],
         "parameters": {"goal": {"x": 0.51, "y": 0.0, "z": 0.5}}, "at_ts": T0})
    assert code == "ENVELOPE_VIOLATION", code  # goal 1cm outside box x<=0.5
    assert robot.pose == before and robot.vendor_calls == []


def test_expired_mid_task():
    b, keys, t, m = fresh()
    m2 = fx.make_mandate(keys, t, mandate_id="mandate-short",
                         window={"not_before": "2026-10-25T00:00:00+00:00",
                                 "expires_at": "2026-10-25T12:00:03+00:00"})
    ops.mandate_register(b, {"mandate": m2})
    s = open_session(b, keys, m2)
    out = ops.task_dispatch(b, {"session_id": s["session_id"],
        "template_id": t["template_id"],
        "parameters": {"goal": {"x": 0.1, "y": 0.0, "z": 0.5}, "duration_s": 30},
        "at_ts": T0})
    st = ops.task_status(b, {"task_run_id": out["task_run_id"],
                             "at_ts": "2026-10-25T12:00:05+00:00"})
    assert st["state"] == "STOPPED_EXPIRED", st
    sess = b.sessions[s["session_id"]]
    assert sess["state"] == "ENDED_MANDATE_EXPIRED"
    pack = b.packs[sess["pack_id"]]
    assert pack["stops"][0]["class"] == "MANDATE_EXPIRED_STOP"
    assert ops.pack_verify(b, {"pack": pack})["verdict"] == "TASK_VERIFIED"


def test_t2_and_schema_fuzz():
    b, keys, t, m = fresh()
    s = open_session(b, keys, m)
    bad = [{"goal": {"x": 0, "y": 0, "z": 0.5}, "velocity": {"x": 1}},
           {"goal": {"x": 0, "y": 0, "z": 0.5}, "nested": [{"topic": "/cmd"}]},
           {"goal": {"x": 0, "y": 0, "z": 0.5}, "occupancy_class": "SHARED"}]
    codes = [refusal_code(ops.task_dispatch, b,
             {"session_id": s["session_id"], "template_id": t["template_id"],
              "parameters": p, "at_ts": T0}) for p in bad]
    assert codes[0] == "T2_DIRECT_MOTION_REFUSED", codes
    assert codes[1] == "T2_DIRECT_MOTION_REFUSED", codes
    assert codes[2] == "OCCUPANCY_UPGRADE_REFUSED", codes
    code = refusal_code(ops.task_dispatch, b,
        {"session_id": s["session_id"], "template_id": t["template_id"],
         "parameters": {"goal": {"x": "fast", "y": 0, "z": 0.5}}, "at_ts": T0})
    assert code == "PARAMETER_SCHEMA_VIOLATION", code


def test_gauge_battery():
    b, keys, t, m = fresh()
    bad = copy.deepcopy(m); bad["ceilings"]["max_speed_mps"] = 99.0
    v = ops.gauge_check_mandate(b, {"mandate": bad})
    assert v["verdict"] == "ENVELOPE_UNSOUND" and \
        any("CEILING_EXCEEDS_VENDOR_RATED" in x for x in v["violations"]), v
    bad2 = copy.deepcopy(m); bad2["robot_serials"] = ["*"]
    assert ops.gauge_check_mandate(b, {"mandate": bad2})["verdict"] == "ENVELOPE_UNSOUND"
    good = ops.gauge_check_pair(b, {"mandate": m, "template": t})
    assert good["verdict"] == "ENVELOPE_SOUND", good
    assert good["resolved_ceilings"]["max_speed_mps"] == 0.25


def test_template_authoring_and_pin():
    b, keys, t, m = fresh()
    code = refusal_code(ops.template_register, b,
                        {"template": t, "_surface": "agent"})
    assert code == "TEMPLATE_AUTHORING_REFUSED", code
    s = open_session(b, keys, m)
    forged = fx.make_template(keys, template_id="move-to-pose",
                              human_author_id="human-engineer-2")
    b.templates["move-to-pose"] = forged  # registry swap, pin unchanged in mandate
    code = refusal_code(ops.task_dispatch, b,
        {"session_id": s["session_id"], "template_id": "move-to-pose",
         "parameters": {"goal": {"x": 0, "y": 0, "z": 0.5}}, "at_ts": T0})
    assert code == "TASK_TEMPLATE_PIN_MISMATCH", code


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("pass", fn.__name__)
    print(f"{len(fns)} builder tests pass")

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
