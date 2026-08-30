"""Build the Team 16 development progress report from live repository evidence."""

from __future__ import annotations

import datetime
import html
import re
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "progress_report.pdf"

NAVY = colors.HexColor("#12304A")
BLUE = colors.HexColor("#1E5C83")
TEAL = colors.HexColor("#218A8D")
PALE_BLUE = colors.HexColor("#EAF2F7")
PALE_TEAL = colors.HexColor("#E8F5F4")
INK = colors.HexColor("#1C2730")
MUTED = colors.HexColor("#536571")
RULE = colors.HexColor("#B9C8D2")
WHITE = colors.white


def run(args: Sequence[str]) -> str:
    """Run an evidence command from the repository and return its real output."""
    result = subprocess.run(
        list(args),
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError("command failed: {}\n{}".format(" ".join(args), output))
    return output


def line_count(relative_path: str) -> int:
    """Count physical lines in a repository file."""
    data = (ROOT / relative_path).read_bytes()
    return len(data.splitlines())


def file_label(relative_path: str) -> str:
    """Render one evidence-backed file and line count."""
    return "{} ({} lines)".format(relative_path, line_count(relative_path))


def escaped(text: str) -> str:
    """Escape command output for safe ReportLab paragraph rendering."""
    return html.escape(text).replace("\n", "<br/>")


def chunked(lines: List[str], size: int) -> Iterable[List[str]]:
    """Yield bounded command-output chunks that can paginate cleanly."""
    for start in range(0, len(lines), size):
        yield lines[start : start + size]


def pytest_summary(output: str) -> str:
    """Keep real pytest progress and result lines without machine-specific paths."""
    selected = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.match(r"^[.]+\s+\[\s*\d+%\]$", stripped):
            selected.append(stripped)
        elif re.match(r"^\d+ passed(?:, \d+ warnings?)? in ", stripped):
            selected.append(stripped)
    if not selected:
        raise RuntimeError("could not extract pytest summary lines")
    return "\n".join(selected)


def collect_evidence() -> Dict[str, object]:
    """Collect all volatile evidence at report build time."""
    git_oneline = run(["git", "log", "--oneline"])
    git_dated = run(["git", "log", "--pretty=%h|%ad|%s", "--date=short"])
    pytest_output = run([sys.executable, "-m", "pytest", "tests", "-q"])
    lint_output = run(
        [sys.executable, "-m", "ruff", "check", "src", "tests", "topology", "experiments"]
    )
    demo_output = run([sys.executable, "demo_st4.py"])
    collected = run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"])

    test_counts: Counter[str] = Counter()
    for line in collected.splitlines():
        if line.startswith("tests/") and "::" in line:
            test_counts[line.split("::", 1)[0]] += 1

    pytest_match = re.search(r"(\d+) passed", pytest_output)
    if not pytest_match:
        raise RuntimeError("could not find pytest pass count in captured output")

    routes: List[Tuple[str, str, str]] = []
    route_pattern = re.compile(
        r"^\s*(s1\s+->.*?s7)\s+(\d+) Mbps\s+(\d+\.\d+) ms\s*$"
    )
    for line in demo_output.splitlines():
        match = route_pattern.match(line)
        if match:
            routes.append(
                (
                    re.sub(r"\s+", " ", match.group(1)),
                    match.group(2) + " Mbps",
                    match.group(3) + " ms",
                )
            )
    if len(routes) != 3:
        raise RuntimeError("expected three routes in demo_st4.py output")

    commits = []
    for row in git_dated.splitlines():
        commit_hash, date, subject = row.split("|", 2)
        commits.append((commit_hash, date, subject))

    complete_ids = set()
    for _commit_hash, _date, subject in commits:
        match = re.match(r"ST-(\d+)", subject)
        if match and int(match.group(1)) <= 5:
            complete_ids.add(int(match.group(1)))

    return {
        "git_oneline": git_oneline,
        "commits": commits,
        "pytest_output": pytest_output,
        "pytest_count": int(pytest_match.group(1)),
        "lint_output": lint_output,
        "demo_output": demo_output,
        "test_counts": test_counts,
        "routes": routes,
        "complete_count": len(complete_ids),
        "report_date": datetime.date.today().isoformat(),
    }


def make_styles():
    """Define the report's restrained professional visual system."""
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverKicker",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=TEAL,
            spaceAfter=8,
            uppercase=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=28,
            leading=33,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSub",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=15,
            leading=20,
            textColor=BLUE,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Subsection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyReport",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=13.2,
            textColor=INK,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.7,
            leading=10.5,
            textColor=MUTED,
        )
    )
    styles.add(
        ParagraphStyle(
            name="EvidenceCode",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=6.2,
            leading=8.0,
            leftIndent=6,
            rightIndent=6,
            borderColor=RULE,
            borderWidth=0.5,
            borderPadding=7,
            backColor=colors.HexColor("#F5F7F8"),
            textColor=colors.HexColor("#18242B"),
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Callout",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=NAVY,
            backColor=PALE_TEAL,
            borderColor=TEAL,
            borderWidth=0.8,
            borderPadding=9,
            spaceBefore=6,
            spaceAfter=10,
        )
    )
    return styles


def table(data, widths, header=True, font_size=8.2):
    """Create a consistent, repeatable report table."""
    result = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEADING", (0, 0), (-1, -1), font_size + 2.5),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [WHITE, colors.HexColor("#F6F8F9")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    result.setStyle(TableStyle(commands))
    return result


def header_footer(canvas, doc):
    """Add restrained navigation and page numbering after the cover."""
    canvas.saveState()
    if doc.page > 1:
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 284 * mm, 192 * mm, 284 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 287 * mm, "TEAM 16 - DEVELOPMENT PROGRESS REPORT")
        canvas.drawRightString(192 * mm, 10 * mm, "Page {}".format(doc.page))
    canvas.restoreState()


def add_command_output(story, title, output, styles, chunk_size=34):
    """Add captured terminal output in paginatable monospace blocks."""
    story.append(Paragraph(title, styles["Subsection"]))
    lines = []
    for raw_line in output.splitlines() or ["(no output)"]:
        lines.extend(
            textwrap.wrap(
                raw_line,
                width=116,
                subsequent_indent="  ",
                replace_whitespace=False,
                drop_whitespace=False,
            )
            or [""]
        )
    for part in chunked(lines, chunk_size):
        story.append(Preformatted("\n".join(part), styles["EvidenceCode"]))


def build_report(evidence: Dict[str, object]) -> None:
    """Compose the complete report from collected evidence."""
    styles = make_styles()
    story = []
    body = styles["BodyReport"]
    small = styles["Small"]
    total_subtasks = 14
    complete_count = evidence["complete_count"]

    story.extend(
        [
            Spacer(1, 30 * mm),
            Paragraph("TEAM 16", styles["CoverKicker"]),
            Paragraph(
                "Intent-Based SDN for 5G Service-Level Agreement Enforcement",
                styles["CoverTitle"],
            ),
            HRFlowable(width="100%", thickness=2.5, color=TEAL, spaceAfter=18),
            Paragraph("Team 16 - Development Progress Report", styles["CoverSub"]),
            Spacer(1, 10 * mm),
            Paragraph("REPORT DATE", small),
            Paragraph(str(evidence["report_date"]), body),
            Spacer(1, 3 * mm),
            Paragraph("DELIVERY STATUS", small),
            Paragraph(
                "{} of {} subtasks complete".format(complete_count, total_subtasks),
                styles["Callout"],
            ),
            Paragraph("EVIDENCE BASIS", small),
            Paragraph(
                "Live git, pytest, Ruff, demo, repository inventory, and line-count commands",
                body,
            ),
            Spacer(1, 36 * mm),
            Paragraph(
                "Prepared as an evidence-backed engineering status document. No live-network result is claimed.",
                styles["Small"],
            ),
            PageBreak(),
        ]
    )

    story.append(Paragraph("1. Executive summary", styles["Section"]))
    story.append(
        Paragraph(
            "This system lets an operator write a machine-readable promise about a network connection, "
            "including bandwidth, latency, and loss. The software validates that intent, computes a path "
            "that satisfies its constraints, and translates the result into OpenFlow rules for enforcement. "
            "The intent pipeline works end to end in software: validation, persistence, path search, constraint "
            "pruning, deterministic selection, and enforcement rule generation are covered by the current test "
            "suite. Live-network execution begins at ST-5, but it has not yet been verified on hardware, Mininet, "
            "or a live Open vSwitch datapath.",
            body,
        )
    )
    story.append(
        Paragraph(
            "Current verified position: {} tests pass and Ruff reports no findings across src, tests, topology, "
            "and experiments. The git history contains completed milestone commits from ST-1 through ST-5."
            .format(evidence["pytest_count"]),
            styles["Callout"],
        )
    )

    story.append(Paragraph("2. What was built", styles["Section"]))
    story.append(
        Paragraph(
            "Line counts below are physical line counts collected from the current working tree. They are shown "
            "to make scope visible, not as a productivity metric.",
            body,
        )
    )

    st_rows = [
        [
            "Subtask",
            "Delivered capability",
            "Current files and physical line counts",
        ],
        [
            "ST-1",
            Paragraph(
                "Container and grammar foundation. Python 3.9 and Ryu 4.34 are explicitly pinned. The Dockerfile "
                "installs Mininet and Open vSwitch from Ubuntu 22.04 apt without exact package pins, so the requested "
                "Mininet 2.3.1b4 and OVS 2.17 claim is not verified by the current repository. The frozen JSON Schema "
                "contains 5 constraint types, 3 violation actions, and priority bounds 1 through 5. The inventory "
                "contains 8 scenario intents, 6 invalid examples, continuous integration, and 3 ADRs.",
                small,
            ),
            Paragraph(
                "<br/>".join(
                    file_label(path)
                    for path in [
                        "Dockerfile",
                        "docker-compose.yml",
                        "requirements.txt",
                        ".github/workflows/ci.yml",
                        "src/intent_manager/schema.json",
                        "src/intent_manager/validator.py",
                        "docs/decisions.md",
                    ]
                ),
                small,
            ),
        ],
        [
            "ST-2",
            Paragraph(
                "Topology specification with 7 switches, 8 hosts, and 3 link-disjoint paths from s1 to s7; "
                "Mininet topology construction; B0 baseline harness; flow-table pilot; and architecture document.",
                small,
            ),
            Paragraph(
                "<br/>".join(
                    file_label(path)
                    for path in [
                        "topology/topology_spec.py",
                        "topology/team16_topo.py",
                        "experiments/scenarios/b0_baseline.sh",
                        "experiments/scenarios/flow_table_pilot.sh",
                        "docs/architecture.md",
                        "tests/test_topology.py",
                        "tests/test_topo_script.py",
                    ]
                ),
                small,
            ),
        ],
        [
            "ST-3",
            Paragraph(
                "Frozen shared interfaces: intent and path models, typed event bus, SQLite persistence schema, "
                "and an audit log that preserves the causal chain from measurement to action.",
                small,
            ),
            Paragraph(
                "<br/>".join(
                    file_label(path)
                    for path in [
                        "src/common/models.py",
                        "src/common/events.py",
                        "src/common/db.py",
                        "src/common/audit.py",
                        "tests/test_common.py",
                    ]
                ),
                small,
            ),
        ],
        [
            "ST-4",
            Paragraph(
                "M1 REST API and M3 path computation using Yen k-shortest paths, constraint pruning, readable "
                "rejection reasons, and deterministic best-path selection.",
                small,
            ),
            Paragraph(
                "<br/>".join(
                    file_label(path)
                    for path in [
                        "src/intent_manager/api.py",
                        "src/pathing/yen_ksp.py",
                        "src/pathing/prune.py",
                        "src/pathing/compute.py",
                        "tests/test_pathing_and_api.py",
                        "demo_st4.py",
                    ]
                ),
                small,
            ),
        ],
        [
            "ST-5",
            Paragraph(
                "M4 enforcement: OpenFlow 1.3 rule generation, deterministic cookies, OVS HTB queue command "
                "construction, a Ryu controller, and the Scenario S1 shell workflow. This code is unit-tested "
                "without Ryu, Mininet, root, or real ovs-vsctl execution.",
                small,
            ),
            Paragraph(
                "<br/>".join(
                    file_label(path)
                    for path in [
                        "src/enforcement/flowmod.py",
                        "src/enforcement/queues.py",
                        "src/enforcement/controller.py",
                        "experiments/scenarios/s1_single_intent.sh",
                        "tests/test_enforcement.py",
                    ]
                ),
                small,
            ),
        ],
    ]
    story.append(table(st_rows, [17 * mm, 73 * mm, 84 * mm], font_size=7.4))

    story.append(PageBreak())
    story.append(Paragraph("3. Architecture", styles["Section"]))
    story.append(
        Paragraph(
            "The design separates intent interpretation, feasibility, routing, enforcement, observation, and "
            "explanation. Each module is accountable for one operational question.",
            body,
        )
    )
    module_rows = [["Module", "Responsibility", "Question answered"]]
    module_rows.extend(
        [
            ["M1", "Intent management", "What does the user want?"],
            ["M2", "Admission control", "Can we provide it?"],
            ["M3", "Path computation", "How can we provide it?"],
            ["M4", "Network enforcement", "Can we make the network do it?"],
            ["M5", "Telemetry and detection", "Is it actually working?"],
            ["M6", "Dashboard and audit", "What is happening and why?"],
        ]
    )
    story.append(table(module_rows, [22 * mm, 58 * mm, 94 * mm]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Topology alternatives", styles["Subsection"]))
    route_rows = [["Route", "Bottleneck", "One-way delay"]]
    route_rows.extend([list(route) for route in evidence["routes"]])
    story.append(table(route_rows, [88 * mm, 43 * mm, 43 * mm]))
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Three link-disjoint paths are mandatory because a closed-loop controller needs a materially different "
            "route when the active path violates an SLA or loses a link. Without alternatives there is nothing to "
            "re-plan to, so rerouting behavior and recovery metrics cannot be tested.",
            styles["Callout"],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4. Evidence of working software", styles["Section"]))
    story.append(
        Paragraph(
            "The following blocks are captured directly by the report builder. They are proof of software behavior, "
            "not live-network evidence.",
            body,
        )
    )
    add_command_output(
        story,
        "python demo_st4.py - captured output",
        str(evidence["demo_output"]),
        styles,
        chunk_size=30,
    )
    add_command_output(
        story,
        "pytest tests -q - captured summary",
        pytest_summary(str(evidence["pytest_output"])),
        styles,
        chunk_size=28,
    )

    story.append(PageBreak())
    story.append(Paragraph("5. Verification", styles["Section"]))
    story.append(Paragraph("Test inventory by file", styles["Subsection"]))
    test_rows = [["Test file", "Collected cases"]]
    for path, count in sorted(evidence["test_counts"].items()):
        test_rows.append([path, str(count)])
    test_rows.append(["Total", str(evidence["pytest_count"])])
    story.append(table(test_rows, [132 * mm, 42 * mm]))
    story.append(Spacer(1, 5 * mm))
    lint_text = "No findings; command exited successfully."
    if evidence["lint_output"]:
        lint_text = str(evidence["lint_output"])
    story.append(Paragraph("Lint status", styles["Subsection"]))
    story.append(Paragraph(escaped(lint_text), styles["Callout"]))
    story.append(Paragraph("Git commit evidence", styles["Subsection"]))
    commit_rows = [["Commit", "Date", "Subject"]]
    for commit_hash, date, subject in evidence["commits"]:
        commit_rows.append(
            [
                commit_hash,
                date,
                Paragraph(html.escape(subject), small),
            ]
        )
    story.append(table(commit_rows, [24 * mm, 27 * mm, 123 * mm], font_size=7.4))

    story.append(PageBreak())
    story.append(Paragraph("6. Honest limitations", styles["Section"]))
    limitations = [
        "Nothing has been executed on Mininet or Open vSwitch yet; docker compose build has not been run.",
        "ST-5 enforcement code is written but unverified against a live datapath.",
        "No novelty is claimed; this is a reference implementation and evaluation.",
        "Metric E5 may return a flat result because software switches have no TCAM scarcity; a pilot is scheduled to confirm.",
        "The current Dockerfile does not pin exact Mininet or Open vSwitch package versions; it installs the Ubuntu 22.04 apt packages.",
    ]
    for index, item in enumerate(limitations, start=1):
        story.append(
            Paragraph(
                "<b>{}.</b> {}".format(index, html.escape(item)),
                styles["Callout"] if index <= 2 else body,
            )
        )

    story.append(Paragraph("7. Remaining work", styles["Section"]))
    remaining = [
        ("ST-6", "Telemetry collection and probes"),
        ("ST-7", "Close the feedback loop"),
        ("ST-8", "Admission control"),
        ("ST-9", "Preemption and hysteresis"),
        ("ST-10", "Two-phase versioned updates"),
        ("ST-11", "Dashboard and operator explanation"),
        ("ST-12", "Evaluation phase one"),
        ("ST-13", "Evaluation phase two"),
        ("ST-14", "Final report"),
    ]
    remaining_rows = [["Subtask", "Outcome"]]
    remaining_rows.extend([list(row) for row in remaining])
    story.append(table(remaining_rows, [30 * mm, 144 * mm]))
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "ST-12 and ST-13 are protected evaluation time. If implementation slips, cut features, never measurement. "
            "The value of the project depends on defensible evidence rather than an expanded but unevaluated feature set.",
            styles["Callout"],
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            "Evidence note: this report was generated from live repository commands on {}. The working suite returned "
            "{} passing tests; the earlier 133-test expectation is superseded by the added ST-5 enforcement coverage."
            .format(evidence["report_date"], evidence["pytest_count"]),
            small,
        )
    )

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=24 * mm,
        bottomMargin=17 * mm,
        title="Intent-Based SDN for 5G SLA Enforcement - Development Progress Report",
        author="Team 16",
        subject="Evidence-backed development progress report",
    )
    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main() -> int:
    """Collect evidence, build the PDF, and report the created relative path."""
    evidence = collect_evidence()
    build_report(evidence)
    print("Created docs/progress_report.pdf")
    print("Evidence: {} tests passed; Ruff clean; {} git commits.".format(
        evidence["pytest_count"], len(evidence["commits"])
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
