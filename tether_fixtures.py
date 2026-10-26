#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Fixture factory — mint Herald-signed mandates/templates (class: fixture).

"""Builder-side fixture factory (tests/smoke). Benches mint their own
fixtures independently; nothing here is trusted by the bridge beyond
the Herald signatures it verifies."""
import json
from pathlib import Path

import herald_sig
from tether_engine import canonical, template_hash_of

MOVE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "goal": {"type": "object", "additionalProperties": False,
                 "properties": {"x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}},
                 "required": ["x", "y", "z"]},
        "waypoints": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                           "z": {"type": "number"}},
            "required": ["x", "y", "z"]}},
        "speed_mps": {"type": "number"}, "payload_kg": {"type": "number"},
        "duration_s": {"type": "number"},
        "sim_drift_m": {"type": "number"},
        "sim_overspeed_mps": {"type": "number"},
        "label": {"type": "string"}},
    "required": ["goal"]}


def load_keys(fixtures_dir):
    return json.loads((Path(fixtures_dir) / "keys.json").read_text())


def make_template(keys, template_id="move-to-pose", **over):
    t = {"template_id": template_id, "human_author_id": "human-engineer-1",
         "robot_class": "ur_arm", "parameter_schema": MOVE_SCHEMA,
         "required_envelope_class": "cell-a",
         "required_occupancy_class": "UNOCCUPIED",
         "ceiling_defaults": {"max_speed_mps": 0.25, "max_payload_kg": 1.0},
         "task_class": "reposition", "vendor_planner_ref": "planner: sim",
         "state": "ACTIVE"}
    t.update(over)
    seed = bytes.fromhex(keys["herald_seed"])
    t["herald_pin_signature"] = herald_sig.sign(
        seed, template_hash_of(t).encode()).hex()
    return t


def make_mandate(keys, template, mandate_id="mandate-1", **over):
    m = {"mandate_id": mandate_id, "principal": "human-principal-1",
         "agent_card_id": "herald-card-w001",
         "robot_serials": ["UR5e-SIM-001"], "robot_class": "ur_arm",
         "template_pins": [{"template_id": template["template_id"],
                            "template_hash": template_hash_of(template)}],
         "envelope": {"envelope_id": "env-cell-a",
                      "anchor": {"map_id": "sim-map-1", "map_hash": "a" * 64},
                      "frame": "map",
                      "volume": {"geometry": "box",
                                 "min": [-0.5, -0.5, 0.0],
                                 "max": [0.5, 0.5, 1.0],
                                 "z_range": [0.0, 1.0]}},
         "ceilings": {"max_speed_mps": 0.25, "max_force_n": 50.0,
                      "max_payload_kg": 1.0},
         "occupancy_class": "UNOCCUPIED",
         "window": {"not_before": "2026-10-25T00:00:00+00:00",
                    "expires_at": "2027-10-25T00:00:00+00:00"},
         "risk_assessment_ref": {"doc_id": "RA-SIM-001",
                                 "human_author": "human-engineer-1",
                                 "date": "2026-10-20"}}
    m.update(over)
    seed = bytes.fromhex(keys["herald_seed"])
    body = {k: v for k, v in m.items() if k not in ("herald_signature", "state")}
    m["herald_signature"] = herald_sig.sign(seed, canonical(body)).hex()
    return m


def agent_open_sig(keys, mandate_id, card="herald-card-w001"):
    seed = bytes.fromhex(keys["agent_seeds"][card])
    msg = canonical({"mandate_id": mandate_id, "agent_card_id": card,
                     "action": "session_open"})
    return herald_sig.sign(seed, msg).hex()


def operator_sig(keys, action, subject, op="site-operator-1"):
    seed = bytes.fromhex(keys["operator_seeds"][op])
    msg = canonical({"action": action, "subject": subject, "operator_id": op})
    return herald_sig.sign(seed, msg).hex()

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
