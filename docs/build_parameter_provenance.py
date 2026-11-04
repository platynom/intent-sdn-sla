"""Extract configured parameters without running or changing an experiment.

Run from the repository root using the application Python (PyYAML installed).
Standards/literature verification is documented in PARAMETER_PROVENANCE.md.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROWS = []


def line_of(path, needle):
    for number, text in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if needle in text:
            return number
    raise ValueError((path, needle))


def add(parameter, value, path, needle, kind, citation, why, effect):
    line = needle if isinstance(needle, int) else line_of(path, needle)
    ROWS.append(dict(parameter=parameter, value=str(value), where=f"{path}:{line}",
                     source_type=kind, citation=citation, justification=why, effect=effect))


def leaves(node, prefix=""):
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            yield from leaves(value, f"{prefix}.{key.value}".strip("."))
    elif isinstance(node, yaml.SequenceNode):
        for i, value in enumerate(node.value):
            yield from leaves(value, f"{prefix}[{i}]")
    else:
        yield prefix, node.value, node.start_mark.line + 1


def extract():
    topology = "topology/topology_spec.py"
    tree = ast.parse((ROOT / topology).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("Link", "Host"):
            values = [ast.literal_eval(arg) for arg in node.args]
            if node.func.id == "Link":
                name = f"{values[0]}-{values[1]}"
                for field, value in zip(("bandwidth Mbit/s", "one-way delay ms"), values[2:]):
                    inferred = any(k.arg == "inferred" and ast.literal_eval(k.value) for k in node.keywords)
                    add(f"{name} {field}", value, topology, node.lineno,
                        "ASSUMPTION" if inferred else "PROJECT PLAN",
                        "Team16 project plan, topology diagram and tc budgets; PDF p.9; topology_spec interpretation note",
                        "Inferred continuation of the northern/southern rail" if inferred else "Deliberately unequal alternative routes for recovery tests; not measured field infrastructure",
                        "Changes path feasibility, RTT, queue ceiling, offered-load pressure and recovery choices")
            else:
                for field, value in zip(("host", "IPv4", "attachment switch", "role"), values):
                    add(f"{values[0]} {field}", value, topology, node.lineno, "ENGINEERING CHOICE",
                        "topology_spec host allocation and project plan topology",
                        "Fixed reproducible namespace endpoint and traffic role", "Changing endpoint/attachment requires matching intents, port maps and harness commands")

    catalog_path = "src/intent_manager/profiles.yaml"
    node = yaml.compose((ROOT / catalog_path).read_text(encoding="utf-8"))
    standard_fields = {"five_qi", "resource_type", "standard_priority", "pdb_ms", "cn_pdb_ms", "per", "mdbv_bytes"}
    for key, value, line in leaves(node):
        if key == "transport_share":
            add(key, value, catalog_path, line, "ASSUMPTION", "No universal allocation verified; SERVICE_PROFILES.md method B, GSTR-TN5G 7.2 and RFC9543 5.1.1.1 reviewed",
                "Explicit sensitivity comparison fraction, not a standardized transport share", "Changes comparison B only, not default A or published evaluation")
        if not key.startswith("profiles.") or ".source." in key or ".bandwidth_source." in key:
            continue
        _, profile, field = key.split(".", 2)
        kind = "STANDARD" if field in standard_fields else "ENGINEERING CHOICE"
        citation = "TS23.501 Rel17, ETSI V17.9.0 (2023-07), Table5.7.4-1, Notes4/5/13; PDF pp.172-174"
        why = "Pinned QoS characteristic; application-to-5QI mapping remains project policy"
        if field == "min_bandwidth_mbps":
            kind = "STANDARD" if profile == "embb" else ("ENGINEERING CHOICE" if value == "null" else "ASSUMPTION")
            citation = "TS22.261 Rel17 V17.10.0, Table7.1-1 urban-macro DL, Note5 target" if profile == "embb" else "profiles.yaml bandwidth_source; no application-rate standard claimed"
            why = "Experienced-rate target used as project reservation, not mandatory GBR" if profile == "embb" else "Non-GBR minimum deliberately absent" if value == "null" else "Illustrative rate assumption; no clinical/V2X/protection rate authority"
        elif field not in standard_fields:
            citation = "profiles.yaml explicit mapping; frozen validator priority policy"
            why = "Project label, mapping or priority, separate from normative 3GPP characteristics"
        add(key, value, catalog_path, line, kind, citation, why,
            "Changes generated intent, comparative budget or service interpretation; must not relabel old runs")

    # Scalar leaves preserve exact endpoints, rates, bounds, actions and modes.
    files = sorted((ROOT / "intents").glob("*.yaml")) + sorted((ROOT / "experiments/scenarios/fixtures").glob("*.yaml"))
    for file in files:
        relative = file.relative_to(ROOT).as_posix()
        for key, value, line in leaves(yaml.compose(file.read_text(encoding="utf-8"))):
            if file.name.startswith("profile_"):
                citation = "Generated copy of profiles.yaml; normative characteristic and proxy caveats in catalogue register above"
                why = "Ordinary frozen-grammar example for the profile API; not a new standard"
            else:
                citation = "Scenario fixture and its leading comments; Team16 plan scenario matrix (PDF p.9); illustrative, not standards-derived"
                why = "Reproducible scenario stimulus; application tenant name does not certify real service requirements"
            add(file.stem + ": " + key, value, relative, line, "ENGINEERING CHOICE", citation, why,
                "Rate/bound changes feasibility and detection; endpoint/port changes traffic matching; dwell/mode/action changes recovery; id/tenant changes identity only")

    # Named numerical defaults and constants in runtime source (excluding test data).
    for file in sorted((ROOT / "src").rglob("*.py")):
        relative = file.relative_to(ROOT).as_posix()
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args.posonlyargs + node.args.args
                for arg, default in zip(args[len(args)-len(node.args.defaults):], node.args.defaults):
                    candidates.append((f"{node.name}.{arg.arg} default", default))
                for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    if default is not None:
                        candidates.append((f"{node.name}.{arg.arg} default", default))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = node.targets if isinstance(node, ast.Assign) else [node.target]
                for name in names:
                    if isinstance(name, ast.Name) and (name.id.isupper() or name.id in {"queue_id", "priority"}):
                        candidates.append((name.id, node.value))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                for keyword in node.keywords:
                    if keyword.arg == "default":
                        label = ast.literal_eval(node.args[0]) if node.args else "argument"
                        candidates.append((str(label) + " CLI default", keyword.value))
            for label, expression in candidates:
                try:
                    value = ast.literal_eval(expression)
                except (ValueError, TypeError):
                    continue
                if not isinstance(value, (int, float, bool)):
                    continue
                why = "Implementation default; no optimization or standards derivation recorded"
                if "ewma" in label:
                    why = "Smooth noisy samples; alpha weights current sample; numerical tuning is not standardized"
                elif "hysteresis" in label:
                    why = "Separate breach and recovery boundaries to reduce threshold chatter"
                elif "consecutive" in label:
                    why = "Require repeated breaches rather than one isolated spike"
                add(label, value, relative, expression.lineno, "ENGINEERING CHOICE",
                    "Implementation default at cited line; concept references L1-L6, no numerical endorsement", why,
                    "Changes runtime scheduling, matching, search bounds or sensitivity; numeric default is not a field measurement")

    # Numeric CLI workload knobs and shell scalar controls in every scenario.
    pattern = re.compile(r"--([\w-]+)\s+([0-9]+(?:\.[0-9]+)?[A-Za-z]*)\b")
    assignment = re.compile(r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z_0-9]*)=([0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$")
    for file in sorted((ROOT / "experiments/scenarios").glob("*.sh")):
        relative = file.relative_to(ROOT).as_posix()
        for line, text in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if text.lstrip().startswith("#"):
                continue
            found = [(name, value) for name, value in pattern.findall(text)]
            match = assignment.match(text)
            if match:
                found.append(match.groups())
            for label, value in found:
                add(file.stem + ": " + label, value, relative, line, "ENGINEERING CHOICE",
                    "Scenario implementation; no standardized magnitude or statistical-power calculation claimed",
                    "Bounded reproducible workload, timing, count, port or controlled comparison",
                    "Changes scenario load/timing/sampling or run count; published measurements remain specific to original setting")

    add("IntentRecord.dwell_seconds default", 10, "src/common/models.py", "dwell_seconds: int = 10", "PROJECT PLAN",
        "Team16 project plan PDF p.6, frozen grammar design notes", "Plan explicitly specifies tunable 10 s default hold-off", "Changes minimum replan spacing; fixtures can override it")
    explicit = [
        ("B2 detector (alpha / band / confirmations)", "1 / 0% / 1", "experiments/scenarios/s1_single_intent.sh", "DETECTOR_ARGS=(--ewma-alpha", "Immediate undamped comparator; B2 matched-detector variant instead inherits B3 tuning", "Lower latency, greater noise/spike sensitivity"),
        ("B3 detector (alpha / band / confirmations)", "0.3 / 10% / 3", "experiments/scenarios/e6_oscillation.sh", "detector_args=(--ewma-alpha 0.3", "Damped comparator selected to demonstrate smoothing and anti-flap mechanisms", "More confirmation delay, fewer transient reroutes; no optimality demonstrated"),
        ("E1 northern egress fault", "replace s1-eth2 delay with 40 ms (not add 40)", "experiments/scenarios/e1_violation_duration.sh", "netem delay 40ms", "Force latency breach after planner sees unchanged nominal graph", "Physical RTT rises by roughly 38 ms relative to 2 ms baseline on this egress"),
        ("E1 fault schedule and censoring", "fault before admission; 15 s censor, B1 15 samples / B3 8 samples", "experiments/scenarios/e1_violation_duration.sh", "FAULT_WINDOW_S=15", "Bound open-loop violation observation; script does not remove fault exactly 15 s after injection", "15 s is analysis censoring, not measured physical fault lifetime"),
        ("E2 / E3 controlled northern fault", "40 ms s1-eth2 before intent submission", "experiments/scenarios/s1_single_intent.sh", "netem delay 40ms", "Common B2/B3 physical stimulus for detection and event-to-install timing", "Timings stay implementation-specific RTT detector results"),
        ("E4 fault and trigger", "40 ms before admission; synthetic event delay 51 ms vs bound 35 ms after stream warmup", "experiments/scenarios/e4_packet_loss.sh", "db.save_event(conn, sla_violated", "Isolate update loss rather than detector latency; event value is injected, not a probe sample", "E4 is not a live fault-detection latency experiment"),
        ("E4 sequence stream", "1000 packets/s; 64 bytes; 8 s send; 9 s receive; 2.5 s warmup", "experiments/scenarios/e4_packet_loss.sh", "--rate 1000", "Resolve short update outages using sequence numbers", "Changing packet rate changes loss counts; 64-byte payload load = 0.512 Mbit/s excluding headers"),
        ("E4 measurement window", "event minus 2 s to path-installed plus 2 s", "experiments/scenarios/e4_packet_loss.sh", "window_start = fault_inject_at - 2.0", "Capture transition plus surrounding steady traffic", "Window size changes denominator and coverage"),
        ("E5 simultaneous fault", "40 ms northern egress; four intents, ports 5001-5004; synthetic 51/35 ms events", "experiments/scenarios/e5_flow_table_entries.sh", "netem delay 40ms", "Compare all-strict / 2 strict + 2 relaxed / all-relaxed on same workload", "Concurrency and policy split change overlap and peak rule count"),
        ("E5 flow poller", "40 ms target loop; 2 s window", "experiments/scenarios/e5_flow_table_entries.sh", "rem = 0.040 - elapsed", "Code wins over stale comment claiming 20 ms; subprocess dump time may exceed period", "Short-lived peaks can be missed; not a hardware TCAM test"),
        ("E6 middle baseline", "2.5 ms on six directional middle egresses", "experiments/scenarios/e6_oscillation.sh", "netem delay 2.5ms", "Near-equal RTT alternative for S6; runtime qdisc override, topology_spec is unchanged", "This experiment differs from nominal 5 ms middle links"),
        ("E6 healthy / fast reset", "north 2 ms, middle 2.5 ms; fast all 0.2 ms", "experiments/scenarios/e6_oscillation.sh", "ms = 0.2 if fast", "Fast reset lets EWMA cross recovery band before next breach", "Damping comparison depends on this deliberately constructed trace"),
        ("S6 macro-cycle", "2 s initial warmup; 20 s cycle", "experiments/scenarios/e6_oscillation.sh", "min(2.0, float(duration_s))", "Repeatable anti-flap stimulus; 600 s default, 3 default runs, recorded follow-up n=10", "Default run count is not the number in every historical result family"),
        ("S6 phase 1", "30 ms active first egress for 4.2 s", "experiments/scenarios/e6_oscillation.sh", "spike_active(30.0)", "Sustained breach intended to trigger both detectors", "Value is replacement egress delay, not additive delay"),
        ("S6 phase 2", "fast reset 0.2 ms for 3.3 s", "experiments/scenarios/e6_oscillation.sh", "time.sleep(3.3)", "Clear smoothed hysteresis state", "Shorter reset can prevent recovery transition"),
        ("S6 phase 3", "45 ms active first egress for 3 s", "experiments/scenarios/e6_oscillation.sh", "spike_active(45.0)", "Secondary breach inside dwell window", "Changes suppression/reroute opportunities"),
        ("S6 phase 4", "fast reset 0.2 ms for 4.5 s", "experiments/scenarios/e6_oscillation.sh", "time.sleep(4.5)", "Recovery before next isolated spike", "Changes EWMA initialization for following spike"),
        ("S6 phase 5", "18 ms active first egress for 1.5 s", "experiments/scenarios/e6_oscillation.sh", "spike_active(18.0)", "Intended isolated spike; exact sampled count depends on scheduling", "Do not claim guaranteed one-sample capture on all machines"),
        ("S6 phase 6", "healthy remainder to 20 s", "experiments/scenarios/e6_oscillation.sh", "20.0 - elapsed", "Preserve cycle duration after processing overhead", "Overruns reduce/erase final remainder"),
        ("Probe payload / protocol / timeout", "UDP echo b'team16' (6 payload bytes), 64-byte receive, 1 s timeout", "src/telemetry/runtime.py", "s=socket.socket", "Small matching active echo to measure delay; custom protocol, not TWAMP", "Probe size/rate changes load and sample statistics; no sustained-rate guarantee"),
        ("Probe and counter nominal period", "1 s; one request per iteration, actual interval can exceed target", "src/telemetry/runtime.py", "--interval", "Low-overhead observable control loop", "Subprocess and timeout time limit effective rate; not exact synchronized 1 Hz"),
        ("O3 contention", "150 Mbit/s cross + 25 Mbit/s intent, 5 s each", "experiments/scenarios/o3_queue_binding.sh", "-b 150M", "Saturate 100 Mbit/s north path to test protected queue under competition", "Offered rate is not delivered rate and not a 5G traffic model"),
        ("O3 source pacing", "h1 netem 1 ms, queue limit 10000", "experiments/scenarios/o3_queue_binding.sh", "netem delay 1ms", "Harness queue/pacing control before competing iperf traffic", "Changes buffering and measured loss; included in experiment environment"),
        ("Strict drain formula (current)", "max(100 ms, 2 * old plan latency + 100 ms)", "src/enforcement/controller.py", "hub.sleep(max(0.1", "Code comment: two directions plus margin tailored to bounded emulator", "Not fixed 250 ms; nominal north/middle/south = 112/130/148 ms; ignores arbitrary fault/queue tails"),
        ("VLAN version mapping", "versions 0/1 -> VLAN 100/101", "src/enforcement/two_phase.py", "_VLAN_BASE = 100", "Two reusable disjoint versions enable staged forwarding; Reitblatt concept, ids are arbitrary", "Requires no collision with existing VLAN use; versions are not per-tenant security"),
        ("HTB queue ceiling", "topology egress capacity: 100/50/40 Mbit/s when max_mbps omitted; queue 1", "src/enforcement/queues.py", "max_mbps = link_capacity_mbps", "Allow borrowing up to physical model ceiling; minimum comes from admitted intent", "Shared queue id means not independent simultaneous per-intent isolation"),
    ]
    for label, value, path, needle, why, effect in explicit:
        add(label, value, path, needle, "ENGINEERING CHOICE", "Cited code/comments; plan motivation; literature concepts L1-L6, no numerical standard", why, effect)


def markdown_table(columns, records):
    def clean(value):
        return str(value).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)] +
                     ["| " + " | ".join(clean(v) for v in row) + " |" for row in records])


def build():
    extract()
    counts = {name: Counter(row["source_type"] for row in ROWS)[name] for name in
              ("STANDARD", "LITERATURE", "MEASURED", "PROJECT PLAN", "ENGINEERING CHOICE", "ASSUMPTION")}
    text = "# Parameter provenance and realism\n\nAudit baseline: feat/final-integration 98ddf64; prepared 4 November 2026. No parameter, raw measurement, schema or experiment changed.\n\n"
    text += markdown_table(["Source type", "Register rows"], list(counts.items()))
    text += f"\n\nTotal: {len(ROWS)} parameter occurrences. Counts refer to source-located settings, not unique numeric values; the same default in a CLI and class is two occurrences. Derived comparisons below are not counted. LITERATURE and MEASURED are zero deliberately: papers motivate mechanisms but do not prescribe these constants; configured workload values are not measurements.\n\n"
    text += "## Top five examiner risks\n\n"
    risks = [
        ("RTT vs one-way", "We compare echo RTT to the same field used for one-way planning; no common one-way compliance conclusion is established."),
        ("2/5/12 ms links", "These are stress-test budgets, equivalent to 400/1000/2400 km of fibre if attributed solely to propagation; not measured metro spans."),
        ("250 ms drain", "That fixed value is stale documentation; current code computes twice planned one-way delay plus 100 ms, minimum 100 ms."),
        ("Detector tuning", "0.3 / 10% / 3 / 10 s is an engineering comparator, not an optimal or standards-mandated setting."),
        ("Profile realism", "5QI values have pinned sources, but application mappings, several rates and IP-loss proxies are project assumptions, not certification."),
    ]
    text += markdown_table(["Risk", "Honest answer"], risks)
    text += "\n\n## Scope and extraction method\n\nThe register extracts all scalar fields of root intents (S1-S8, demo_010-013, generated profiles) and evaluation fixtures; all catalogue profile characteristics; every fabric link and host attachment; named numeric runtime constants/defaults; numeric scenario CLI controls and shell scalar assignments. Explicit rows cover embedded fault schedules, probes, queue ceilings and drain formulas. Invalid examples and unit-test stimuli are excluded. Interpreter/libraries and derived experiment measurements are separate from tunable parameters. String identity fields are retained so addresses, ports and labels are auditable. Reasons describe code comments or operational purpose; no undocumented historical optimization is invented. Source file:line references refer to unchanged runtime/config files at the baseline.\n\n"
    text += "## Verified source documents\n\n"
    text += """The actual ITU PDFs and RFC text were obtained from the following primary URLs and opened. Local copies are ignored under docs/specs; the six literature PDFs and project plan were opened from ../references. Full original PDFs are never committed. Exact clause/table references below identify the checked locations; short quotations do not substitute for the metric's scope.

- **Y1**: ITU-T Y.1541 (12/2011), clauses 5.3, 5.3.1, 5.3.2, 5.3.7, Tables 1-3, PDF pp.14-20, printed pp.8-14. Table 1 IPTD objective: "Upper bound on the mean IPTD". [Official PDF](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-Y.1541-201112-I!!PDF-E&lang=e&type=items).
- **D1**: RFC 7679 (January 2016), sections 3.4, 3.6, 3.7.1: one-way first-bit source to last-bit destination; clock synchronization and uncertainty matter. Section 3.4: "Dst received the last bit of that packet". [Official text](https://www.rfc-editor.org/rfc/rfc7679.txt).
- **D2**: RFC 2681 (September 1999), sections 2.4-2.6: source-to-destination-and-back metric. Section 2.4: "then immediately sent a Type-P packet back to Src". [Official text](https://www.rfc-editor.org/rfc/rfc2681.txt).
- **D3**: RFC 5357 (October 2008), sections 2, 3, 4.1, 4.2.1: TWAMP-Control and TWAMP-Test, timestamped sender/reflector exchange. Section 4.1 describes "measuring two-way metrics". Our six-byte UDP echo does not implement those formats or control sessions; it is not a TWAMP implementation. [Official text](https://www.rfc-editor.org/rfc/rfc5357.txt).
- **F1**: ITU-T G.114 (05/2003), Annex A.1, Table A.1, PDF p.10, printed p.4: "Optical fibre cable system, digital transmission" has "5 µs/km (Note 1)". Note 1 (next page) marks this planning value provisional and under study. [Official PDF](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-G.114-200305-I!!PDF-E&lang=e&type=items).
- **S1/S2**: pinned ETSI TS123501 V17.9.0 Table5.7.4-1 Notes4/5/13 and TS122261 V17.10.0 Table7.1-1 Note5; source PDFs previously opened and source hashes retained in profile source metadata. See SERVICE_PROFILES.md for primary URLs and scope.

## Literature and project-plan support

All six local papers were opened. They support concepts, not the chosen numerical constants. L1: Reitblatt et al., SIGCOMM 2012, section 5, "Two-phase update", Definition 5 (PDF p.7); its optimized mechanisms discuss draining in-flight packets (PDF p.8). L2: Zhou et al., NSDI 2015, introduction and CCG overview (PDF pp.2-3, printed pp.73-74): customizable consistency motivates selective policy; no 250 ms mandate. L3: Foerster et al., IEEE COMST 2019, section I introduction (PDF pp.1-2): consistency/overhead tradeoffs, no local VLAN numbers or detector tuning endorsed. L4: Leivadeas and Falkner, IEEE COMST 2023, section II.A taxonomy discussion (PDF p.2): intent activation and assurance. L5: Park et al., Computer Networks 2023, SLA-management overview (PDF p.2) and assurance discussion (PDF pp.6-7): active/passive monitoring and remediation. L6: Martini et al., FGCS 2023, background (PDF pp.2-3): fulfillment and assurance in a closed loop. None is claimed to prescribe alpha=0.3, a 10% band, N=3, 20 s cycles or the chosen fault magnitudes. Numeric-optimality evidence: NOT VERIFIED (no tuning study recorded).

Project plan: Team16 Project Plan, 16-page local PDF, topology/budgets p.9, frozen grammar/10 s dwell p.6, scenario matrix p.9. The topology source explicitly identifies two inferred continuation edges. The numerical detector band/alpha are engineering choices even where the plan motivates damping.

## Parameter register

"""
    text += markdown_table(["Parameter", "Value", "Where used (file:line)", "Source type", "Citation", "Justification", "Effect if changed"],
                           [[r[k] for k in ("parameter", "value", "where", "source_type", "citation", "justification", "effect")] for r in ROWS])
    text += "\n\n## Y.1541 comparison\n\nThis is a closest-use comparator chosen for discussion, not a standardized 5QI-to-Y.1541 mapping. Table 2 application guidance motivates real-time UDP -> class 0 and transaction/TCP -> class 2 (or 3 for looser delay), bulk no-bound TCP -> class 4. Very low loss may be compared with provisional class 6. Classes 6/7 remain provisional in clause 5.3.7. Y.1541 is UNI-to-UNI statistical performance; these profile targets cover a modelled transport segment and PER is not IPLR.\n\n"
    text += markdown_table(["Y.1541 class", "Mean IPTD ms", "IPDV ms", "IPLR ratio", "IPER ratio"],
                           [("0",100,50,"1e-3","1e-4"),("1",400,50,"1e-3","1e-4"),("2",100,"U","1e-3","1e-4"),("3",400,"U","1e-3","1e-4"),("4",1000,"U","1e-3","1e-4"),("5","U","U","U","U"),("6 provisional",100,50,"1e-5","1e-6"),("7 provisional",400,50,"1e-5","1e-6")])
    text += "\n\nU means unspecified; IPDV is quantile-minus-minimum (class0/1 use 1-1e-3 quantile; provisional6/7 use 1-1e-5), not our consecutive absolute RTT difference. IPLR ratios 1e-3/1e-5 correspond to 0.1%/0.001%. We do not measure IPER or enforce these IPDV objectives. Y1 5.3.2 suggests one-minute evaluation intervals; five one-packet probes cannot certify these classes.\n\n"
    comparisons = []
    for file in sorted((ROOT / 'intents').glob('*.yaml')) + sorted((ROOT / 'experiments/scenarios/fixtures').glob('*.yaml')):
        intent = yaml.safe_load(file.read_text(encoding='utf-8'))['intent']
        guarantee = intent.get('guarantee', {})
        latency = guarantee.get('max_latency_ms')
        loss = guarantee.get('max_loss_pct')
        tcp = intent.get('match', {}).get('proto') == 'tcp'
        cls, delay_bound, loss_bound = ('4', 1000, .1) if tcp and latency is None else ('3',400,.1) if tcp and latency and latency > 100 else ('2',100,.1) if tcp else ('0',100,.1)
        if loss is not None and loss <= .001 and not tcp:
            cls, delay_bound, loss_bound = '6 provisional',100,.001
        def compare(value, bound):
            return 'unspecified' if value is None else 'stricter' if value < bound else 'equal' if value == bound else 'looser'
        comparisons.append((file.relative_to(ROOT).as_posix(), cls, f"{latency} / {compare(latency,delay_bound)}", f"{loss} / {compare(loss,loss_bound)}", 'IPDV / IPER not bounded or assessed'))
    text += markdown_table(["Intent", "Closest comparator", "Delay ms / numeric relation", "Loss % / numeric relation", "Missing coverage"], comparisons)
    text += "\n\nGenerated profile examples cover every catalogue profile: URLLC1ms/.01% and V2X2ms/.01% are numerically stricter than class0; high-voltage2ms/.001% equals provisional6 loss and is stricter in delay; eMBB20ms/.1% equals class0 loss and is stricter in delay; mMTC20ms/.0001% is stricter than class2 and even provisional6 loss. None proves class compliance because the segment, delay statistic, loss meaning, IPDV and IPER differ. Impossible intents may still have a closest comparator; mapping does not mean admission.\n\n"
    text += "## RTT versus one-way consequences\n\nCode evidence: runtime.py sends then recvfrom and times the whole exchange; probes.py parse_ping explicitly returns RTT and observation never halves it; collector.py record_probe subtracts local send and receive timestamps. Echo service time, OS scheduling and return-path delay are included. D1 one-way and D2 round-trip differ; D3 shows what a real TWAMP implementation would additionally require. On symmetric paths only, RTT is approximately 2 * one-way plus endpoint overhead; halving RTT is not a validated one-way measurement under asymmetry.\n\n"
    text += markdown_table(["Profile", "A / B one-way ms", "Current same-field RTT limit A", "Symmetric equivalent A one-way ms", "Consequence"],
        [("urllc","1 / 4.5",1,.5,"Already refused: shortest nominal one-way6 >1; no conclusion changes"),
         ("v2x","2 / 1.5",2,1,"Already refused; no compliance result exists"),
         ("smart_grid","2 / 1.5",2,1,"Already refused; no compliance result exists"),
         ("embb","20 / 65",20,10,"Planner admits north6 and middle15; nominal RTT12/30 means middle could breach despite one-way feasibility"),
         ("mmtc","20 / 140",20,10,"Same default mismatch; no sustained telemetry compliance measured by profile activation tests")])
    text += "\n\nFor method B the same accidental halving would impose effective one-way limits 2.25/0.75/0.75/32.5/70 ms respectively. These are interpretations, not parameter changes.\n\n"
    threshold_rows = []
    seen = set()
    for row in ROWS:
        if row['parameter'].endswith('intent.guarantee.max_latency_ms'):
            threshold_rows.append((row['parameter'].split(':')[0], row['value'], float(row['value']) / 2, 'Planning uses one-way; runtime uses RTT if this intent is monitored'))
            seen.add(row['parameter'].split(':')[0])
    threshold_rows += [('E1 / E2 / E3 B2/B3 / E4 / E5',35,17.5,'Evaluation latency field is an RTT detector bound in live use; not proof of one-way35ms compliance'),('S6 / E6',22,11,'B3 entry24.2ms RTT / recovery19.8ms RTT -> symmetric12.1/9.9ms one-way; B2 band0 ->11ms')]
    text += markdown_table(["Intent or evaluation", "Same-field RTT threshold ms", "Symmetric effective one-way ms", "Interpretation"], threshold_rows)
    text += """

For the 35 ms B3 bound, 10% hysteresis enters above 38.5 ms RTT and recovers below 31.5 ms RTT, symmetric equivalents 19.25/15.75 ms one-way, after EWMA and N confirmations. E1 duration and E2 detection are operational results against these RTT predicates; they are not durations of violating a normalized one-way standard. E3 event-to-install timings remain measured control-plane timings, independent of how the trigger's delay was named. E4 uses an injected 51 ms/35 ms event, so loss/reordering findings remain update-mechanism observations, not a one-way detector test. E5 rule and packet counts likewise stand. E6 reroute/event-accounting results remain valid for its specified trace, with no claim of standards-compliant QoS. B0 latency is explicitly RTT. E7 admission timings and E8 overhead are not one-way delay measurements. No raw values, summaries, significance tests or outcomes were changed; the standards-compliance interpretation is narrowed.

## Link-delay realism

Using F1's 5 microseconds/km planning figure, propagation-only distance = configured milliseconds * 1000 / 5. Thus northern2 ms =400 km per link, middle5 ms =1000 km, southern12 ms =2400 km. Whole nominal routes6/15/24 ms imply1200/3000/4800 km if all delay were propagation. These are equivalents, not claimed physical cable lengths. Netem can also represent processing, queuing or deliberately injected delay. The project did not measure carrier spans. For an explicitly ASSUMED metro/aggregation comparison of10-100 km, propagation would be0.05-0.5 ms; that range is not asserted to be an industry-wide typical standard (typical-span source NOT VERIFIED). These deliberately large link budgets make alternatives and refusal/recovery visible and are unsuitable as evidence of realistic short-haul URLLC.

## Corrections and unverified items

- **250 ms**: historical documentation in HANDOVER / PROJECT_REPORT / EXPERIMENTAL_RESULTS describes a fixed delay. Current controller.py:465 uses max(0.1, 2*plan.est_latency_ms/1000 +0.1) seconds. This register and current report correct the claim; no published numerical results change. The old rows are historical, not a current implementation guarantee.
- E1's15 s is an analysis censoring window; the fault is installed before admission and not removed by a15 s timer. E5's executable poll target is40 ms despite a20 ms comment. S6's runtime middle-link override is2.5 ms, not nominal topology5 ms. Fault replacement values must not be described as additive increments.
- Numerical detector optimality, general WAN drain sufficiency and universal/typical metro span statistics: **NOT VERIFIED**. No calibration/power analysis is invented. Paper-backed mechanisms do not imply paper-backed constants.
- Hardware timing, physical-switch TCAM, 3GPP service compliance, clinical safety and extreme-reliability loss bounds: **NOT VERIFIED by this emulator**. This is live packet forwarding through software switches in Linux namespaces, not physical network deployment or only an offline simulation.

## Source integrity

"""
    metadata = json.loads((ROOT / 'docs/report_assets/parameter_sources.json').read_text())
    text += markdown_table(['Opened source', 'SHA-256'], [(name, data['sha256']) for name,data in metadata.items()])
    output = ROOT / 'docs/PARAMETER_PROVENANCE.md'
    output.write_text(text + '\n', encoding='utf-8')
    facts = dict(baseline='98ddf64', counts=counts, total=len(ROWS), risks=risks,
                 source_sha256={row['where'].rsplit(':',1)[0]: hashlib.sha256((ROOT / row['where'].rsplit(':',1)[0]).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for row in ROWS})
    (ROOT / 'docs/report_assets/parameter_provenance.json').write_text(json.dumps(facts,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(total=len(ROWS), counts=counts), indent=2))


if __name__ == '__main__':
    build()
