"""Build the final report from the retained Amrita cover and measured summaries.

Run from the repository root with python-docx installed. For PDF export use
PowerShell -File docs/render_final_report.ps1 -InputDocx docs/FINAL_REPORT.docx
-OutputPdf docs/FINAL_REPORT.pdf. Word updates page fields during export.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "experiments/results/summary"
REFERENCE = ROOT.parent / "Team16_Intent_SDN_Literature_Review_and_Progress_Report.docx"
REFERENCE_SHA256 = "b4437154aa7cef630a9b24a9e8ea4f6a7caf80d7add3121899ff19fde3ccb976"


def rows(filename):
    with (SUMMARY / filename).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def result_table(filename, metrics, label=""):
    selected = [r for r in rows(filename) if r["metric"] in metrics]
    lines = [f"### {label}", "", f"Source: experiments/results/summary/{filename}", "",
             "| Group | Metric | n | Mean | Sample SD | 95% t interval | Unit |",
             "|---|---|---|---|---|---|---|"]
    for row in selected:
        group = (row.get("group") or row.get("baseline") or "B1").replace("_", " ")
        unit = {"count_per_10min": "per 10 min", "msgs_per_s": "msg/s", "pct": "%"}.get(row["unit"], row["unit"])
        number = lambda key, fallback: f"{float(row.get(key) or row[fallback]):.3f}"
        mean = f"{float(row['mean']):.3f}"
        deviation = number("stdev", "sample_stddev")
        low = number("ci95_t_low", "ci95_low")
        high = number("ci95_t_high", "ci95_high")
        lines.append("| " + " | ".join([
            group, row["metric"].replace("_", " "), row.get("n") or row["runs"], mean,
            deviation, f"[{low}, {high}]", unit,
        ]) + " |")
    return "\n".join(lines)


def profile_section():
    """Use exported source facts and fail if catalogue or topology changed."""
    payload = json.loads((ROOT / "docs/report_assets/service_profiles.json").read_text(encoding="utf-8"))
    for relative, expected in payload["source_sha256"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise RuntimeError("Profile export is stale; run python -m scripts.export_profile_catalog")
    profiles = payload["profiles"]
    text = """
### 3.1 Standards-derived service profiles

This front-end layer generates ordinary intents and then invokes the unchanged validation/admission handler. The schema and topology remain unchanged. A 5QI describes QoS characteristics, not a slice type. The following facts come from [S1], TS 23.501 Table 5.7.4-1 and Notes 4/5/13, using the pinned Release 17 extraction. Later releases exist. Application mappings are project policy: remote surgery uses a discrete-automation proxy; high-voltage smart-grid protection is delay-critical, not mMTC. The mMTC example deliberately chooses non-GBR 5QI 9 for delay-tolerant buffered traffic; Release 17 has no dedicated massive-IoT 5QI in this table.

| Profile | 5QI | PDB ms | CN PDB ms | PER | CN note |
|---|---|---|---|---|---|
"""
    for row in profiles:
        text += (f"| {row['service_class'].replace('_', ' ')} | {row['five_qi']} | {row['pdb_ms']} | "
                 f"{row['cn_pdb_ms']} | {row['per']:g} | {row['source']['note']} |\n")
    text += """
The CN PDB covers the UPF terminating N6 to 5G-AN segment, closest to the modelled transport network. Method A uses that allocation as the default transport target. Method B, shown only for comparison, is (PDB - CN PDB) times transport_share. The configurable share defaults to 0.5: ASSUMPTION, not standardized. Our review of [S4] and [S5] found interface-dependent latency guidance and slice objectives, not a universal fraction. Giving this emulator the entire CN budget is also an approximation because CN processing can consume part of it.

| Profile | A ms default | B ms comparison | Loss % proxy | Minimum Mbps |
|---|---|---|---|---|
"""
    for row in profiles:
        bandwidth = row["min_bandwidth_mbps"]
        text += (f"| {row['service_class'].replace('_', ' ')} | {row['transport_target_a_ms']:g} | "
                 f"{row['transport_target_b_ms']:g} | {row['max_loss_pct']:g} | "
                 f"{bandwidth if bandwidth is not None else 'None (non-GBR)'} |\n")
    text += """
Loss percentage is PER times 100, a numerical conversion used as a project IP-loss proxy. PER is a non-congestion link-layer error measure, not IP loss. Late-packet handling also differs by resource type. The broadband rate uses the urban-macro experienced downlink target in [S2] Table 7.1-1; its Note 5 says targets are not strict requirements. Other positive rates are engineering assumptions, not surgical, V2X or protection standards. Non-GBR mMTC requests no minimum rate. Standard priorities are not copied to the project's separate priority scale.

The next table is calculated from the unchanged topology and default method A without existing reservations; it is not measured compliance. No route satisfies any selected delay-critical profile. Their CN reference allocations are smaller than this emulator's per-link delays, so the system must refuse them instead of weakening the targets. For method B, mMTC fits all routes; eMBB still excludes the southern bandwidth bottleneck.

| Profile | North A | Middle A | South A |
|---|---|---|---|
"""
    for row in profiles:
        verdicts = ["Yes" if row["feasibility"]["a"][route] else "No"
                    for route in ("north", "middle", "south")]
        text += "| " + " | ".join([row["service_class"].replace("_", " ")] + verdicts) + " |\n"
    text += """
Functional checks under docs/demo_assets/profile_* record explained refusals for the delay-critical defaults and actual installed routes plus matching packet delivery for feasible profiles. These checks do not establish sustained bandwidth, one-way latency, or extremely low loss compliance. The live probe still measures RTT whereas planning and the standard use one-way budgets.

Published E1-E8 results used illustrative intents sized for emulation. They remain evaluations of enforcement and recovery mechanisms; they were not rerun or relabelled as standards-compliant services. The original scenario/demo files now carry an explicit illustrative-values comment.

[S1] ETSI TS 123 501 V17.9.0 (2023-07), 3GPP TS 23.501 Release 17, clauses 5.7.3.4/5.7.3.5 and Table 5.7.4-1, Notes 4/5/13. https://www.etsi.org/deliver/etsi_ts/123500_123599/123501/17.09.00_60/ts_123501v170900p.pdf

[S2] ETSI TS 122 261 V17.10.0 (2022-05), 3GPP TS 22.261 Release 17, Tables 7.1-1 and 7.2.3.2-1. The latter is an ITS infrastructure-backhaul example; its reliability/availability figures are not PER or collision-avoidance targets. https://www.etsi.org/deliver/etsi_ts/122200_122299/122261/17.10.00_60/ts_122261v171000p.pdf

[S3] ITU-R M.2410-0 (11/2017), clauses 4.7.1, 4.8 and 4.10. Its latency/reliability/density requirements concern radio-interface evaluation; they are context only, not transport inputs. https://www.itu.int/dms_pub/itu-r/opb/rep/R-REP-M.2410-2017-PDF-E.pdf

[S4] ITU-T GSTR-TN5G (2018-10), section 7.2 / Table 7-2. https://www.itu.int/dms_pub/itu-t/opb/tut/T-TUT-HOME-2018-2-PDF-E.pdf

[S5] RFC 9543 (2024), section 5.1.1.1. https://datatracker.ietf.org/doc/html/rfc9543#section-5.1.1.1

"""
    return text


def narrative():
    cpu_payload = json.loads((SUMMARY / "e8v2_control_overhead_summary.json").read_text())
    cpu = {(r["group"], r["metric"]): float(r["mean"])
           for r in cpu_payload["summaries"]}
    ratio = cpu[("B3", "control_stack_cpu_pct")] / cpu[("B1", "control_stack_cpu_pct")]
    text = """# Intent Based SDN for 5G SLA Enforcement

## Abstract

We implement and evaluate a transport-network service-assurance prototype. An operator submits a structured intent, the system validates it and checks residual resources, computes a feasible route, programs software switches, measures the service, and responds to confirmed violations. Strict intents use versioned consistent updates; relaxed intents use direct replacement. The results show the benefit of preserving packets during tested route transitions and suppressing oscillation, together with costs in reaction time, rule space, reordering, and control-stack CPU. The artifact integrates established methods and makes no algorithmic novelty claim. Demonstrations run on a live Mininet/Open vSwitch datapath inside Docker; illustrative dashboard samples are explicitly labelled and excluded from evaluation.

## 1 Introduction and objectives

Manual switch configuration requires an operator to map a service request onto routes, matches, ports, queues, and subsequent repairs. A service promise also needs ongoing measurement: installing a rule does not prove the requested service is delivered. This project makes that lifecycle explicit and reproducible on one machine.

Our objectives are to validate structured requests with explainable refusals; account for existing reservations; choose constraint-satisfying routes; enforce matches and bandwidth queues; detect sustained service violations; replan through a durable event boundary; and expose an understandable audit trail. Evaluation measures both benefits and costs of consistency and damping. The scope is a transport-network reference implementation motivated by 5G-style services, rather than a deployed radio or mobile-core system.

## 2 Literature review

Leivadeas and Falkner [1] survey the intent lifecycle, including expression, translation, resolution, activation, and assurance. Their discussion motivates a feedback loop that measures service behavior after activation. We instantiate those stages using a frozen structured grammar and path-level remediation. Natural-language interpretation and machine-learning assurance are outside the implementation.

Martini, Gharbaoui, and Castoldi [2] describe intent-based vertical-service slicing with feasibility checks, translation, deployment, and assurance over cloud and NFV infrastructure. Their recovery redeploys a slice. Our corrective action changes a transport path, so the workloads and timing scopes differ; we do not claim a direct speedup over their system.

Park and colleagues [3] review SDN and assurance across network-slicing domains. Their hybrid monitoring discussion motivates active observations together with passive counters. Our planner uses bottleneck bandwidth and summed link delays inside one transport domain. The implementation does not include RAN scheduling, a mobile core, FlexE, or segment routing.

Foerster, Schmid, and Vissicchio [4] survey consistent network updates and the tradeoffs among correctness properties, update rounds, and extra rules. This provides the design space for our strict and relaxed modes. A software-switch rule-capacity pilot cannot substitute for hardware TCAM evaluation.

Reitblatt and colleagues [5] establish consistent-update abstractions and a versioned two-phase method. Our strict implementation stages tagged rules, synchronizes processing, flips ingress classification, drains the old path, and removes the old version. The method is cited as prior work. The emulated drain interval is a deployment assumption rather than a general proof about packet lifetime.

Zhou and colleagues' CCG [6] enforces customizable consistency properties with verification and update scheduling. Our per-intent strict/relaxed choice follows the principle that stronger consistency has a cost. We do not implement CCG's invariant verifier, uncertainty model, or automatic fallback. These distinctions prevent presenting an educational integration as a new consistency algorithm.

## 3 System design

The processing pipeline is YAML or JSON intent -> M1 validation and persistence -> M2 admission -> M3 constrained path -> M4 rules and queues -> live software datapath -> M5 measurements and detector -> durable violation -> control-loop replanning. M6 reads the shared state and causal audit. SQLite provides the process boundary between telemetry and the Ryu controller. These are logical modules, not a requirement for a separate server per module. Compose provides the privileged SDN runtime, an API service, a read-only dashboard service, and a one-shot seed job. The Ryu controller and live collector run inside the SDN runtime during scenarios.

The topology is defined in topology/topology_spec.py and instantiated by topology/team16_topo.py. It contains seven switches, eight hosts, eight inter-switch links, and eight host-access links. A single Ryu controller programs the OVS switches. Three link-disjoint alternatives between the protected hosts have unequal budgets so the system has a meaningful selection problem. The s3-s7 and s6-s7 links are marked inferred and remain modelling assumptions. These counts describe configuration, rather than measured performance.

![Topology reproduced from the supplied Team 16 literature report with inferred links dashed](report_assets/topology.png)

The frozen grammar contains traffic endpoints and protocol, optional destination port, priority, service guarantees, consistency, violation policy, and dwell. Supported guarantee types are minimum bandwidth, maximum latency, maximum loss, isolation from selected tenants, and avoided links. Actions are reroute, degrade, or alert_only. The schema and semantic validator define acceptance; no LLM interprets the request. Application names such as remote surgery label illustrative configurations and do not certify a clinical or standards-compliant service class.

## 4 Implementation

M1 parses the request, applies JSON Schema and semantic checks, stores an IntentRecord, and returns a decision with field-specific explanations. A schema rejection is distinct from a valid request rejected by admission.

M2 constructs a residual-capacity graph using persisted reservations and checks feasibility. Priority preemption is accompanied by durable state and removal of the victim's flow rules. M3 resolves endpoint addresses to access switches, enumerates bounded Yen candidate paths, prunes constraints, and selects deterministically. Modelled route bandwidth is the narrowest link and modelled delay is the sum of edge delays.

M4 generates bidirectional OpenFlow matches and actions with per-intent cookies. IPv4 protocol matches include the required Ethernet type. HTB queues use bits per second, derive egress ceilings from topology, and are selected by SET_QUEUE forwarding actions. Strict mode uses the established versioned update procedure; relaxed mode accepts a transient interruption during direct replacement.

M5 runs a separate live process with UDP echo observations and OVS flow-counter deltas. The live probe measures round trip, whereas planning uses configured one-way delays. The detector combines EWMA, a hysteresis band, consecutive confirmation, and a dwell timer. Confirmed events are persisted before Ryu dispatches them. ControlLoop computes an alternative excluding current route edges, installs it, persists the new path, and records a causal explanation.

M6 serves a read-only dashboard and JSON API. It displays intent state, computed or installed routes, recent measurements, and audit entries. The startup seed job provides application examples and labelled simulated samples when samples are absent. Subsequent live samples are displayed separately. Simulated samples never count as evaluation observations. CODE_WALKTHROUGH.md supplies file/function references and the full trace.

## 5 Evaluation methodology

The baseline contract comes from Section 11 of the supplied project plan. B0 uses static shortest-path forwarding without intents or monitoring. B1 installs intents open loop. B2 uses naive closed-loop recovery with relaxed updates and an immediate detector. B3 uses the full system. A matched-detector relaxed ablation helps distinguish detector cost from update cost. Historical and current-code run families remain separate in RESULT_PROVENANCE.md.

E1 measures violation duration; E2 measures detection latency; E3 measures event-to-install recovery; E4 counts packet loss and reordering around a route change; E5 measures peak rule populations; E6 counts reroutes over a fixed oscillation window; E7 times admission versus active-intent count; E8 measures control traffic and CPU. O3 separately checks data-plane queue binding under competing traffic. API response latency is not switch-install latency. E8's capture-based traffic field estimates control traffic using TCP PSH segments; it is not a parser that proves each segment contains exactly one OpenFlow message.

Each registered headline family uses independent repetitions, with its n shown in the generated tables. Intervals are two-sided Student-t intervals using sample standard deviation. Welch comparisons are used for nonzero variances; exact two-sided permutation comparisons are used when a group has zero sample variance. Deterministic repeated observations do not justify an infinite t statistic with a reported probability of zero. Open-loop violation duration is explicitly right-censored at the observation boundary.

Experiments run inside the Linux Docker image under WSL on the Windows host, using the project's pinned Python/Ryu stack and OVS software datapath. No claim is made about physical switching hardware. Raw CSV files are retained; changed-code runs and regression checks use distinct prefixes. An independent verifier checks registered summaries against raw values. The E6 event-accounting follow-up is documented with direct SQL counts and complete-sample checks; historical uncertain event counts are not treated as established causal evidence.

## 6 Results

The following tables are generated from registered summary files. They report measured means, sample deviations, and intervals rather than values transcribed into the builder. Historical baselines remain identified where current-code reruns are compared with them. The corrected E6 durable accounting series (n=10) is included alongside the retained oscillation series, verifying that each reroute matches an emitted durable violation event.
"""
    text = text.replace("## 4 Implementation", profile_section() + "## 4 Implementation")
    blocks = [
        ("b0_baseline_summary_20261025.csv", {"throughput", "rtt_avg", "loss"}, "B0 static forwarding baseline"),
        ("b1_open_loop_20261025.csv", {"intent_post_response_latency"}, "B1 API response timing pilot"),
        ("e1_violation_duration_summary.csv", {"sla_violation_duration_s"}, "E1 violation duration"),
        ("b2_b3_closed_loop_20261025.csv", {"detection_latency", "recovery_latency"}, "Historical E2 and E3 baselines"),
        ("b3_current_closed_loop_summary.csv", {"detection_latency", "recovery_latency"}, "Current code B3 E2 and E3"),
        ("e4_current_packet_loss_summary.csv", {"packets_lost", "packets_reordered"}, "Current code E4 transition behavior"),
        ("e5_flow_table_summary.csv", {"peak_rules_max_switch", "packets_lost"}, "Historical E5 rule and loss tradeoff"),
        ("e6_oscillation_summary.csv", {"reroute_count_10min", "dwell_suppressions"}, "E6 retained oscillation series"),
        ("e7_admission_scaling_summary.csv", {"admission_decision_latency_ms"}, "E7 admission scaling"),
        ("e8v2_control_overhead_summary.csv", {"control_stack_cpu_pct", "openflow_msgs_per_s"}, "E8 corrected control stack overhead"),
        ("o3_current_queue_binding_summary.csv", {"intent_throughput_mbps", "intent_loss_pct"}, "Current code O3 bound queue"),
        ("o3_queue_binding_summary.csv", {"intent_throughput_mbps", "intent_loss_pct"}, "Historical O3 bound and unbound comparison"),
    ]
    if (SUMMARY / "e6_accounting_summary.csv").exists():
        blocks.append(("e6_accounting_summary.csv", {"reroute_count_10min", "raw_reroute_count", "violations_emitted", "measurement_count", "duration_s"}, "Corrected E6 durable accounting"))
    for filename, metrics, label in blocks:
        text += "\n\n" + result_table(filename, metrics, label)
    comparisons = json.loads((SUMMARY / "e4_current_packet_loss_summary.json").read_text(encoding="utf-8"))
    text += "\n\n### E4 exact comparisons\n\n"
    for test in comparisons["statistical_tests"]:
        if test["metric"] in {"packets_lost", "packets_reordered"}:
            text += (f"{test['metric'].replace('_', ' ')}: {test['test_method']}; "
                     f"two-sided p = {test['p_value_two_sided']:.8g}. "
                     "Source: e4_current_packet_loss_summary.json.\n\n")
    environment_path = ROOT / "docs/report_assets/environment.json"
    if environment_path.exists():
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        text += ("\n\n### Captured runtime environment\n\n"
                 f"Python {environment['python']}; Ryu {environment['ryu']}; "
                 f"Mininet {environment['mininet']}; {environment['ovs']}; "
                 f"kernel {environment['kernel']}. Captured by docs/capture_report_environment.py "
                 f"at {environment['captured_utc']}.\n")
    text += "\n\n### Evaluation figures\n\n"
    for stem, caption in [
        ("e1_violation_duration", "Violation duration with open-loop censoring"),
        ("e2_detection_latency", "Detection latency with code-version provenance"),
        ("e3_recovery_latency", "Recovery latency with code-version provenance"),
        ("e4_packet_loss", "Transition packet loss and reordering"),
        ("e5_rules_vs_loss", "Historical E5 rule-space and packet-preservation tradeoff; mixed code versions"),
        ("e6_oscillation", "Oscillation over the fixed observation window; series provenance is labelled"),
        ("e7_admission_scaling", "Admission decision scaling"),
        ("e8_control_overhead", "Corrected full-stack overhead"),
        ("o3_queue_binding", "Historical O3 queue-binding comparison under competing traffic"),
    ]:
        text += f"![{caption}](../experiments/figures/{stem}.png)\n\n"
    text += f"""## 7 Discussion

Strict updates preserve packets in the tested transitions, while damping reduces route changes during alternating faults. Those benefits have measurable costs: confirmation delays detection, staging and draining delay installation, new packets can overtake old packets, and overlapping versions consume extra rules. The corrected mean B3-to-B1 control-stack CPU ratio is {ratio:.3f}, calculated from E8v2's measured group means. It must not be interpreted as whole-machine CPU or extrapolated to a production deployment.

Low-rate probes establish reachability and detector behavior but do not load-test a bandwidth promise. O3 therefore offers sustained protected traffic with competing load and measures receiver throughput. The E4 interpretation is consistent with the configured path-delay difference and sequence rate; this is a timing explanation rather than a new theoretical guarantee. For E6, the historical event-count shortfall is addressed by the corrected durable accounting rerun (n=10, 90 reroutes reconciling exactly with 90 durable violations and 90 restorations per run; see E6_ACCOUNTING.md). Historical runs remain disclosed as a provenance limitation, while the oscillation comparison remains a path-revision comparison.

## 8 Limitations

The fixed topology and single-machine emulation limit generalization. Inferred links are design assumptions. Candidate search is bounded. Planning checks a one-way link-delay sum while live detection compares UDP round-trip delay with the same latency field; the implementation does not convert that budget between the two definitions. Its measurements therefore do not certify a common one-way latency SLA. A software-switch table pilot does not demonstrate hardware TCAM pressure. The drain interval is calibrated for the experiment, not a proven WAN lifetime bound. Forwarding selects a shared queue id on an egress port, so the single-protected-flow bandwidth experiment does not establish independent per-intent bandwidth isolation for concurrent services. Recovery computes an alternative directly on its topology graph without repeating M2 residual admission; contention-safe multi-intent recovery is not established. Queue reservations do not alone prove sustained delivered application throughput. Exact tests and confidence intervals describe these runs and do not remove workload, platform, or code-version confounders. Simulated dashboard data is for presentation only.

## 9 Conclusion and future work

The project implements a reproducible intent-to-enforcement and measurement loop with explainable admission, durable violation handling, and per-intent update consistency. Its evaluated strengths and costs are both visible in the generated results. The contribution is an integrated engineering artifact based on cited methods. Future work includes larger and changing topologies, controlled hardware experiments, stronger workload validation, durable provenance for each run, and validation of update-drain assumptions under wider delay distributions.

## References

[1] A. Leivadeas and M. Falkner. A Survey on Intent-Based Networking. IEEE Communications Surveys and Tutorials, 2023. DOI: 10.1109/COMST.2022.3215919.

[2] B. Martini, M. Gharbaoui, and P. Castoldi. Intent-based network slicing for SDN vertical services with assurance: Context, design and preliminary experiments. Future Generation Computer Systems, 2023. DOI: 10.1016/j.future.2022.12.033.

[3] K. Park, S. Sung, H. Kim, and J.-i. Jung. Technology trends and challenges in SDN and service assurance for end-to-end network slicing. Computer Networks, 2023. DOI: 10.1016/j.comnet.2023.109908.

[4] K.-T. Foerster, S. Schmid, and S. Vissicchio. Survey of Consistent Software-Defined Network Updates. IEEE Communications Surveys and Tutorials, 2019. DOI: 10.1109/COMST.2018.2876749.

[5] M. Reitblatt, N. Foster, J. Rexford, C. Schlesinger, and D. Walker. Abstractions for Network Update. ACM SIGCOMM, 2012. DOI: 10.1145/2342356.2342427.

[6] W. Zhou, D. Jin, J. Croft, M. Caesar, and P. B. Godfrey. Enforcing Customizable Consistency Properties in Software-Defined Networks. USENIX NSDI, 2015. https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/zhou.
"""
    return text


def plain(text):
    return re.sub(r"\*\*|`", "", text)


def format_table(table):
    table.autofit = False
    widths = {4: [2.45, 1.4, 1.4, 1.4], 5: [2.05, 1.15, 1.15, 1.15, 1.15],
              6: [2.15, 0.6, 0.7, 0.7, 1.2, 1.3],
              7: [0.9, 1.5, 0.3, 0.85, 0.7, 1.7, 0.7]}[len(table.columns)]
    for column, width in zip(table.columns, widths):
        column.width = Inches(width)
    for i, row in enumerate(table.rows):
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for index, cell in enumerate(row.cells):
            cell.width = Inches(widths[index])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for name in ("top", "left", "bottom", "right"):
                edge = OxmlElement("w:" + name)
                for key, val in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    edge.set(qn("w:" + key), val)
                borders.append(edge)
            tcpr.append(borders)
            if i == 0:
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "E7E6E6")
                tcpr.append(shade)
            for p in cell.paragraphs:
                if index in (2, 5):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif index in (3, 4):
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.space_before = Pt(4)
                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(10)
                    run.bold = i == 0
        if i == 0:
            repeat = OxmlElement("w:tblHeader")
            row._tr.get_or_add_trPr().append(repeat)


def build(markdown):
    asset_dir = ROOT / "docs/report_assets"
    asset_dir.mkdir(exist_ok=True)
    template = asset_dir / "cover_template.docx"
    profile = asset_dir / "template_provenance.json"
    if REFERENCE.exists() and hashlib.sha256(REFERENCE.read_bytes()).hexdigest() != REFERENCE_SHA256:
        raise RuntimeError("Reference changed; inspect it before rebuilding")
    if template.exists():
        expected = json.loads(profile.read_text(encoding="utf-8"))["cover_template_sha256"]
        if hashlib.sha256(template.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Retained cover template changed")
        doc = Document(template)
    else:
        doc = Document(REFERENCE)
        topology_shape = doc.inline_shapes[1]
        image_id = topology_shape._inline.graphic.graphicData.pic.blipFill.blip.embed
        (asset_dir / "topology.png").write_bytes(doc.part.related_parts[image_id].blob)
        start = next(p._p for p in doc.paragraphs if p.text == "1. Project Overview and Status")
        body = doc._element.body
        removing = False
        for child in list(body):
            if child is start:
                removing = True
            if removing and child.tag != qn("w:sectPr"):
                body.remove(child)
        doc.save(template)
        profile.write_text(json.dumps({
            "original_reference": REFERENCE.name,
            "original_reference_sha256": REFERENCE_SHA256,
            "cover_template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
            "intentional_changes": "Remove old report body; retain Amrita cover, logo, styles, and geometry",
        }, indent=2) + "\n", encoding="utf-8")
    for p in doc.paragraphs:
        if p.text == "Literature Review, Implementation Analysis and Current Progress":
            p.runs[0].text = "Final Project Report"
        if p.text == "Dr. Naveen Kumar":
            p.runs[0].text = "Dr. Navin Kumar"
    for table in doc.tables:
        for row in table.rows:
            if row.cells[0].text == "Dheepak":
                row.cells[0].paragraphs[0].runs[0].text = "Dheepak K"
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles["Normal"].font.size = Pt(11)
    for name, size in (("Heading 1", 13), ("Heading 2", 12), ("Heading 3", 11)):
        doc.styles[name].font.size = Pt(size)
        doc.styles[name].font.bold = True
        doc.styles[name].paragraph_format.keep_with_next = True
    for section in doc.sections:
        borders = section._sectPr.find(qn("w:pgBorders"))
        if borders is not None:
            borders.set(qn("w:display"), "allPages")
            borders.set(qn("w:zOrder"), "front")
            for edge in borders:
                edge.set(qn("w:val"), "single")
                edge.set(qn("w:sz"), "8")
                edge.set(qn("w:color"), "000000")
        section.footer_distance = Inches(0.48)
        for story in (section.footer, section.first_page_footer):
            footer = story.paragraphs[0]
            footer.clear()
            footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
            footer.add_run("Team 16 – Intent-Based SDN for 5G SLA Enforcement | Page ")
            for field_name, following in (("PAGE", " of "), ("NUMPAGES", "")):
                field = OxmlElement("w:fldSimple")
                field.set(qn("w:instr"), field_name)
                footer._p.append(field)
                footer.add_run(following)
            for run in footer.runs:
                run.font.name = "Times New Roman"
                run.font.size = Pt(9)
    first = True
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("# "):
            i += 1
            continue
        if line.startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                parts = [plain(x.strip()) for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", x) for x in parts):
                    table_rows.append(parts)
                i += 1
            table = doc.add_table(rows=0, cols=len(table_rows[0]))
            for parts in table_rows:
                cells = table.add_row().cells
                for cell, value in zip(cells, parts):
                    cell.text = value
            format_table(table)
            doc.add_paragraph()
            continue
        image_match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", line)
        if image_match:
            image_path = (ROOT / "docs" / image_match.group(2)).resolve()
            p = doc.add_paragraph()
            p.paragraph_format.keep_with_next = True
            p.add_run().add_picture(str(image_path), width=Inches(6.65))
            caption = doc.add_paragraph(image_match.group(1))
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in caption.runs:
                run.italic = True
                run.font.size = Pt(10)
        elif line.startswith("## "):
            p = doc.add_heading(plain(line[3:]), level=1)
            if line in ("## References", "## 7 Discussion"):
                p.paragraph_format.page_break_before = True
            if first:
                p.paragraph_format.page_break_before = True
                first = False
        elif line.startswith("### "):
            doc.add_heading(plain(line[4:]), level=2)
        else:
            p = doc.add_paragraph(plain(line))
            if line.startswith("Source:"):
                p.paragraph_format.keep_with_next = True
                for run in p.runs:
                    run.font.size = Pt(9.5)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.05
        i += 1
    doc.settings.element.append(OxmlElement("w:updateFields"))
    doc.settings.element[-1].set(qn("w:val"), "true")
    doc.save(ROOT / "docs/FINAL_REPORT.docx")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-markdown", action="store_true", help="Use manually reviewed FINAL_REPORT.md")
    args = parser.parse_args()
    source = ROOT / "docs/FINAL_REPORT.md"
    markdown = source.read_text(encoding="utf-8") if args.from_markdown else narrative()
    if not args.from_markdown:
        source.write_text(markdown, encoding="utf-8")
    build(markdown)
    print("Created docs/FINAL_REPORT.md and docs/FINAL_REPORT.docx from retained cover and registered summaries")


if __name__ == "__main__":
    main()
