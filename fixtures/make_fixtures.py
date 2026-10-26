#!/usr/bin/env python3
# Eclipse Tether MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Fixture minting — TEST keys + sim site only (class: fixture).

"""Mint P0 fixtures: Herald/agent/operator TEST keys, sim robot
registry (ROS 2 + Gazebo + UR-class arm stand-ins), vendor rated
limits table, sim control defaults. Deterministic seeds — fixture
data only, never production keys."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import herald_sig  # noqa: E402


def kp(label):
    seed = hashlib.sha256(f"eclipse-tether-fixture-{label}".encode()).digest()
    _, pub = herald_sig.keypair_from_seed(seed)
    return seed.hex(), pub.hex()


def main():
    herald_seed, herald_pub = kp("herald")
    agent_seed, agent_pub = kp("agent-w001")
    op_seed, op_pub = kp("operator-desk")
    keys = {
        "note": "P0 TEST keys (class: fixture). Seeds present so fixtures "
                "and benches can mint Herald-shaped records; production "
                "custody is a gated decision.",
        "herald_pubkey": herald_pub, "herald_seed": herald_seed,
        "agents": {"herald-card-w001": agent_pub},
        "agent_seeds": {"herald-card-w001": agent_seed},
        "operators": {"site-operator-1": op_pub},
        "operator_seeds": {"site-operator-1": op_seed},
    }
    (HERE / "keys.json").write_text(json.dumps(keys, indent=1))
    robots = {"robots": [
        {"serial": "UR5e-SIM-001", "model": "UR5e (Gazebo model)",
         "robot_class": "ur_arm", "firmware_version": "sim-1.0.0",
         "home_pose": [0.0, 0.0, 0.5]},
        {"serial": "UR5e-SIM-002", "model": "UR5e (Gazebo model)",
         "robot_class": "ur_arm", "firmware_version": "sim-1.0.0",
         "home_pose": [0.0, 0.0, 0.5]},
    ], "class_label": "fixture (simulated site; planner: sim)"}
    (HERE / "robots.json").write_text(json.dumps(robots, indent=1))
    limits = {"classes": [
        {"robot_class": "ur_arm", "max_speed_mps": 1.0,
         "max_force_n": 150.0, "max_payload_kg": 5.0,
         "source_citation": "fixture table: UR5e-class published ratings, "
                            "sim-stamped for P0 (not a safety claim)",
         "table_version": "sim-1"},
        {"robot_class": "spot_quadruped", "max_speed_mps": 1.6,
         "max_force_n": 0.0, "max_payload_kg": 14.0,
         "source_citation": "fixture table: Spot-class published ratings; "
                            "adapter is P2, no P0 surface (spec §4.2/§10.2)",
         "table_version": "sim-1"},
    ]}
    (HERE / "vendor_limits.json").write_text(json.dumps(limits, indent=1))
    control = {"estop": False, "lease_grabbed_by_human": False,
               "local_control": False, "lease_holder": "bridge",
               "heartbeat_ok": True, "evidence_ok": True,
               "note": "simulated vendor endpoints (class: fixture)"}
    (HERE / "sim_control.json").write_text(json.dumps(control, indent=1))
    print("fixtures minted:", sorted(p.name for p in HERE.glob("*.json")))


if __name__ == "__main__":
    main()

# Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
