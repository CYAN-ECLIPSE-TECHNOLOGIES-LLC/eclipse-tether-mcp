# Eclipse Tether MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Tether — governed robot task authority — signed mandates, bounded envelopes, evidence for every task.**

Agents can already command robots through public MCP wrappers whose authority model is: whoever holds the robot password holds the robot. Tether is the mandate layer between an agent and a moving machine: physical task authority is exercised only inside a Herald-signed mandate pinning *which agent* may dispatch *which pinned, human-authored task templates* to *which robot serials*, inside *which workspace envelope*, under *which speed/force ceilings and occupancy class*, until *when* — enforced at a site bridge that is the only routed path to the robot — and every session, including its refusals, gaps, envelope exits, and human overrides, is sealed into a Blackbox-form evidence pack a third party can verify offline.

Spec: `../eclipse-tether-spec-20261025.md`.

## Status — honest labels

v0.1.0, local stdio transport, Python stdlib only. **P0 = simulator only: ROS 2 + Gazebo + UR-class arm represented by an in-process sim robot behind the bridge (`planner: sim`, `class: fixture`). No real motion, no hardware calls, no vendor SDK, no network surface.** Liability counsel + insurance + vendor-terms reviews gate **P1 real motion only** (spec §10.4) — they do not gate this build. Certification ceiling for P0 is `CERTIFIED(simulator)`, granted only by a Verity bench run, never by the builder.

Platform positions (spec §4, binding): Tesla Optimus = published wait position — closed platform, no SDK/API exists; **never a logo wall**. Spot position = governance + evidence for SDK-direct and multi-vendor sites — **not Orbit dispatch** (Orbit 5.2 is Boston Dynamics' own vendor-cloud MCP). Standards landscape: ISO 10218-1/-2:2025, ANSI/A3 R15.06-2025, ANSI/RIA R15.08 as spec'd.

## Safety law (spec §3, binding on every surface)

1. A mandate **never** substitutes for a site risk assessment.
2. Ceilings are **outputs of a human risk assessment**, entered by humans; no agent proposes/computes/raises a ceiling. Shipped sim defaults are refusal-tight placeholders, labeled as such.
3. **No T2 direct motion in v0/v1** — no velocity/joint/torque/trajectory surface exists at any tier, under any mandate.
4. Occupancy is human-declared (`UNOCCUPIED` / `SUPERVISED` / `SHARED`); unknown = T0 observe-only.
5. Human stop authority is absolute: e-stop / lease grab / local control ends the session (`HUMAN_OVERRIDE`, terminal); agent resume refuses until human clearance + re-attestation.
6. Vendor safety systems are outside the type system — absent, not permission-gated. Mandate ceilings may only tighten vendor-rated limits; lower value wins, disagreement receipted.

## Surfaces — 22 tools (spec §6)

Selected by `ECLIPSE_TETHER_SURFACE`; disjoint dispatch tables; a verb absent from a surface returns the generic unknown-tool refusal, byte-identical in shape to gibberish (no existence oracle).

| Surface | Tools |
|---|---|
| agent (9) | `fleet_discover` `session_open` `task_templates_list` `task_dispatch` `task_status` `task_abort` `telemetry_read` `image_read` `session_close` |
| operator (6) | `mandate_register` `mandate_revoke` `template_register` `template_revoke` `site_freeze_set` `session_reattest` |
| tools (7, offline) | `pack_verify` `pack_render` `pack_compare` `gauge_check_mandate` `gauge_check_template` `gauge_check_pair` `gauge_limits_list` |

Operator destructive verbs use the house verified-approval pattern: the operator approval signature is re-verified against the operator key at use time. Simulated vendor endpoints (e-stop, lease grab, heartbeat, evidence writer) are driven by `fixtures/sim_control.json` — the P0 fixture form of §10.2 step 6. Bench-only fixture clock: tools accept `at_ts` (ISO-8601 with offset), labeled `class: fixture` wherever it surfaces.

## Refusal anchors

`ENVELOPE_VIOLATION` is a **pre-motion** refusal (robot never moves, receipted, sealed in the pack). `MANDATE_EXPIRED_STOP` seals a mid-task expiry with final pose. `HUMAN_OVERRIDE` is terminal for the session and is also the refusal class for every agent resume attempt on the same mandate until human clearance. Full closed vocabulary: spec §6.4, mirrored in `tether_engine.REFUSALS`.

## Run

```bash
python3 fixtures/make_fixtures.py   # mint TEST fixture keys + sim site
python3 smoke.py                    # 22-tool surface enumeration
python3 tests/test_tether.py        # builder regression tests (not certification)
ECLIPSE_TETHER_SURFACE=agent python3 server.py
```

## Not tested (manifest, verbatim from spec §13)

real hardware of any class · real vendor SDKs (Spot/Unitree/UR-RTDE) · real e-stop/lease hardware · Isaac Sim · multi-robot sessions · hosted/multi-site · T2 (refused by design, §3) · closed platforms: Tesla Optimus, Figure, Apptronik, Atlas, NEO (no surface exists, §4.1) · Orbit dispatch (vendor's, not ours, §4.2).

---
Eclipse Tether MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai
