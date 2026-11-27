from pathlib import Path
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

REPO = Path(__file__).resolve().parents[2]
OUT_DOCX = REPO / "docs" / "sir_response" / "Team16_Red_Items_Response.docx"
OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)

NAVY = RGBColor(0x1B, 0x36, 0x5D)
DARK = RGBColor(0x1E, 0x24, 0x2B)
MUTED = RGBColor(0x4A, 0x55, 0x68)

FONT_NAME = "Calibri"


def set_cell_shading(cell, fill_hex: str) -> None:
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def set_cell_margins(cell, top=35, bottom=35, left=75, right=75) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def set_table_borders(table, color="CBD5E1") -> None:
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="6" w:space="0" w:color="1B365D"/>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="0" w:color="1B365D"/>'
        f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
        f'  <w:left w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


def prevent_row_split(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def repeat_header_row(row) -> None:
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))


def add_heading_line(doc: Document, text: str, space_before=6, space_after=3) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = FONT_NAME
    r.font.size = Pt(10.5)
    r.font.bold = True
    r.font.color.rgb = NAVY
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="1" w:color="1B365D"/>'
        f'</w:pBdr>'
    )
    p._p.get_or_add_pPr().append(pBdr)


def format_run(run, size=8.5, bold=False, italic=False, color=DARK) -> None:
    run.font.name = FONT_NAME
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def add_table(doc: Document, headers, rows, col_widths_mm, body_size=7.8, keep_together=False):
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    set_table_borders(tbl)

    hdr_row = tbl.rows[0]
    repeat_header_row(hdr_row)
    prevent_row_split(hdr_row)
    for j, title in enumerate(headers):
        cell = hdr_row.cells[j]
        cell.width = Mm(col_widths_mm[j])
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_shading(cell, "1B365D")
        set_cell_margins(cell, top=42, bottom=42, left=65, right=65)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        p.paragraph_format.keep_with_next = True
        r = p.add_run(title)
        format_run(r, size=body_size, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))

    for i, rdata in enumerate(rows):
        row = tbl.rows[i + 1]
        prevent_row_split(row)
        bg = "F8FAFC" if i % 2 == 1 else "FFFFFF"
        is_last = i == len(rows) - 1
        for j, val in enumerate(rdata):
            cell = row.cells[j]
            cell.width = Mm(col_widths_mm[j])
            cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            set_cell_shading(cell, bg)
            set_cell_margins(cell, top=34, bottom=34, left=65, right=65)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.10
            if keep_together and not is_last:
                p.paragraph_format.keep_with_next = True
            r = p.add_run(val)
            format_run(r, size=body_size, bold=(j == 0), color=DARK)
    return tbl


def main():
    doc = Document()

    # A4 page setup with balanced narrow margins so entire brief fits cleanly in <= 4 pages
    sec = doc.sections[0]
    sec.page_width = Mm(210)
    sec.page_height = Mm(297)
    sec.top_margin = Mm(13.5)
    sec.bottom_margin = Mm(13.5)
    sec.left_margin = Mm(15)
    sec.right_margin = Mm(15)
    # Printable width = 210 - 30 = 180 mm

    # Subtle page number footer ("Page X of Y")
    sec.different_first_page_header_footer = False
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r1 = fp.add_run("Team 16  |  Red-Items Data Summary  |  Page ")
    format_run(r1, size=7.5, color=MUTED)
    fld1 = parse_xml(r'<w:fldSimple %s w:instr="PAGE"/>' % nsdecls("w"))
    fp._p.append(fld1)
    r2 = fp.add_run(" of ")
    format_run(r2, size=7.5, color=MUTED)
    fld2 = parse_xml(r'<w:fldSimple %s w:instr="NUMPAGES"/>' % nsdecls("w"))
    fp._p.append(fld2)

    # Title (exact required string)
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2)
    r_title = p_title.add_run(
        "Red-Item Data for 'Closed-Loop Intent-Based SDN for 5G SLA Enforcement with Per-Intent Update Consistency'"
    )
    format_run(r_title, size=12.5, bold=True, color=NAVY)

    # Line 2 & Line 3 (exact required strings)
    p_l2 = doc.add_paragraph()
    p_l2.paragraph_format.space_before = Pt(0)
    p_l2.paragraph_format.space_after = Pt(1)
    r_l2 = p_l2.add_run("Team 16 - Tanmaya Kumar, Srikanth Dinesh, Dheepak K")
    format_run(r_l2, size=9.0, bold=True, color=DARK)

    p_l3 = doc.add_paragraph()
    p_l3.paragraph_format.space_before = Pt(0)
    p_l3.paragraph_format.space_after = Pt(5)
    r_l3 = p_l3.add_run("20 November 2026")
    format_run(r_l3, size=8.5, color=MUTED)

    # 1-paragraph summary (max 5 sentences)
    p_sum = doc.add_paragraph()
    p_sum.paragraph_format.space_before = Pt(0)
    p_sum.paragraph_format.space_after = Pt(5)
    p_sum.paragraph_format.line_spacing = 1.12
    r_sum = p_sum.add_run(
        "All experimental red-item runs (E9 through E16, plus code inspection for E4 path verification) were completed on the current main build at github.com/platynom/intent-sdn-sla (commit 75f2d2e) inside our Docker and Mininet emulated testbed, providing 95% t-confidence-interval replacement text for both the conference and extended journal drafts. "
        "Same-build Table I/Table 2 reruns (E9), detection-delay scaling (E10, 150 runs), dwell-timer sweeps (E11, 50 runs), packet-loss and reordering sweeps (E12, 180 runs), jitter false-confirmation filtering (E13, 40 runs), offline multi-intent contention testing (E14a, 80 runs), shared-clock one-way delay evaluation (E15, 60 runs), and Geant2012 control-plane scaling (E16, 140 runs) all ran cleanly to completion. "
        "The secondary live Mininet contention check (E14b) now passes (11 runs on build 449aa7e) after we fixed the two defects it exposed: an Open vSwitch linux-htb queue erased Mininet's netem delay on bandwidth-intent ports, and simultaneous recoveries could all plan onto the same link. "
        "In E16, hardware or P4 switch TCAM usage was not run because no hardware switch is available, so rule counts are reported strictly from the software model. "
        "Finally, journal placeholders J1 (corresponding author and funding wording) and J2 (acceptance citation) remain team editorial decisions rather than experimental items."
    )
    format_run(r_sum, size=8.5, color=DARK)

    # Table "Red items"
    add_heading_line(doc, "Red items", space_before=3, space_after=3)

    red_rows = [
        (
            "C1",
            "Conference p. 3 (Sec. IV-A, Table I): [rerun B2 on the current build]",
            "Measured on the current main build (n = 10 per row): B2 immediate (k = 1) 101.1 [96.3, 105.9] ms detection, 458.1 [421.1, 495.1] ms recovery; matched-detector B2 (k = 3) 2096.3 [2091.9, 2100.7] ms detection, 454.5 [414.2, 494.8] ms recovery; B3 damped (k = 3) 2094.7 [2092.4, 2097.0] ms detection, 628.5 [601.0, 656.1] ms recovery. Strict B3 recovery is 174.0 ms slower than matched B2 (p = 5.27e-7, Welch t-test). Both B2 and B3 increased relative to the earlier draft build; the exact per-change cause is not isolated (waiting for OpenFlow barrier replies is the most likely contributor).",
        ),
        (
            "C2",
            "Conference p. 4 (Sec. IV-C): [confirm the old and new paths of E4]",
            "Code inspection of the E4 scenario and topology specification confirms initial placement on north path s1-s2-s3-s7 (6 ms configured nominal one-way delay) with a 40 ms netem fault on egress port s1-eth2 (44 ms total configured), and rerouting to middle path s1-s4-s5-s7 (15 ms configured). Configured delta-D = 44 - 15 = 29 ms, agreeing within 1 packet with the 28 ms inferred at 1000 pkt/s and directly re-measured in E12 Pair A (28.000 [28.000, 28.000] reordered packets; measured delta-D = 28.001 ms).",
        ),
        (
            "J1",
            "Journal p. 1 (Author/funding footnote): [Corresponding author and funding acknowledgement, if any.]",
            "TEAM DECISION REQUIRED: select corresponding author; suggested default funding sentence: 'This work received no external funding.'",
        ),
        (
            "J2",
            "Journal p. 2 (Intro, last para.): [citation once accepted]",
            "LEAVE AS IS until the conference paper is accepted.",
        ),
        (
            "J3",
            "Journal p. 7 (Sec. 5.1, Table 2): [rerun B2 on the current build]",
            "Identical to C1 for Table 2 (n = 10 per row, 174.0 ms recovery difference between matched B2 and B3, p = 5.27e-7; cause vs. earlier build not isolated, barrier wait likely). Same-build O3 (n = 10): unbound 18.737 [18.039, 19.435] Mbit/s with 25.038% [22.245, 27.832] loss vs. bound 24.995 [24.995, 24.996] Mbit/s with 0.000% loss and 74.400 Mbit/s cross-traffic (p = 8.05e-9 Welch t-test for intent throughput; p = 1.08e-5 exact permutation test for loss).",
        ),
        (
            "J4",
            "Journal p. 9 (Sec. 5.3): [confirm the old and new paths of E4]",
            "Same as C2: initial north route s1-s2-s3-s7 with 40 ms fault on s1-eth2 (44 ms configured) and repaired middle route s1-s4-s5-s7 (15 ms configured), yielding 29 ms configured delta-D against 28 ms inferred at 1000 pkt/s.",
        ),
        (
            "J5",
            "Journal p. 11 (Table 5, row E9): [result]",
            "B2 recovery 458.1 [421.1, 495.1] ms, matched B2 454.5 [414.2, 494.8] ms, B3 628.5 [601.0, 656.1] ms (+174.0 ms difference on current build, p = 5.27e-7; shift vs. earlier build not isolated, barrier wait likely); O3 unbound 18.74 [18.04, 19.44] Mbit/s (25.0% loss).",
        ),
        (
            "J6",
            "Journal p. 11 (Table 5, row E10): [result]",
            "Across 15 (k, delta-t) cells (150 runs), measured detection delay agrees within 0.00% to -5.46% of Eq. (9) with fixed t0 = 0.1 s; least squares fits t0-hat = 97.6 ms (SD = 7.1 ms, R^2 = 0.99996).",
        ),
        (
            "J7",
            "Journal p. 11 (Table 5, row E11): [result]",
            "Reroutes fell from 60.0 [60.0, 60.0] (delta = 0 s) to 49.2 [45.5, 52.9] (10 s), 30.0 [30.0, 30.0] (20 s), and 19.4 [18.7, 20.1] (30 s), within -0.8% to +10.5% of Eq. (10) using effective B3 confirmable count Nf = 60 (derived from the S6 fault schedule: Phase 5 lasts 1.5 s vs. 4.2 s and 3.0 s in Phases 1 and 3, not measured per phase; strict bound held in all 50 runs).",
        ),
        (
            "J8",
            "Journal p. 11 (Table 5, row E12): [result]",
            "Across 180 runs (250 to 4000 pkt/s, pairs A\u2011C), relaxed updates lost 10.4 to 172.2 packets (T_gap = 40.5 to 43.2 ms, -1.2% to +5.4% vs. 41 ms); strict updates lost 0 packets and reordered 4.1 to 114.3 packets (within ±7.7% except -18.0% at 250 pkt/s pair B from integer packet quantization).",
        ),
        (
            "J9",
            "Journal p. 11 (Table 5, row E13): [result]",
            "At 6 ms synthetic jitter (n = 10, 600 samples/run), false confirmations fell from 0.1280 [0.1135, 0.1425] (76.8/run; predicted 0.1255, +2.0%) under naive detection to 0.00183 [0.00052, 0.00315] (1.1/run; predicted 0.00216) at EWMA k = 1, and 0 of 5990 (k = 2) and 0 of 5980 (k = 3) windows (95% rule-of-three upper bound 5.0e\u20114).",
        ),
        (
            "J10",
            "Journal p. 11 (Table 5, row E14): [result]",
            "Across N in {4, 8, 12, 16} (80 Mbit/s total floor), the earlier baseline build over-committed all 3 links of the middle path in every run (max res/cap 1.20 to 1.40 all-intents fault; 1.47 to 1.60 north-fault), whereas the current main build recorded 0 over-committed links (max res/cap ≤ 1.000) across all 40 runs; the live Mininet/OVS check E14b (build 449aa7e, n = 11) moved all north intents off the faulted path with 0 over-committed links (2 x 20 Mbit/s on the 40 Mbit/s south path, 2 x 20 on the 50 Mbit/s middle path), 19.999 Mbit/s per flow and 0% loss.",
        ),
        (
            "J11",
            "Journal p. 11 (Table 5, row E15): [result]",
            "Shared-clock forward OWD matched healthy path budgets (6.70, 15.82, 24.94 ms vs. 6, 15, 24 ms configured) with RTT/2 within 0.02 ms; under asymmetric 40 ms forward faults, true forward OWD reached 44.92, 51.07, and 52.96 ms (0% ≤ 35 ms compliance) while RTT/2 underestimated forward delay by -19.02, -17.51, and -14.03 ms, falsely clearing North (25.90 ms) and Middle (33.56 ms).",
        ),
        (
            "J12",
            "Journal p. 11 (Table 5, row E16): [result]",
            "On a copy of Geant2012 from a third-party GitHub mirror (not compared byte for byte with the Topology Zoo original; 40 nodes, 61 links; configured 100 Mbit/s, 0.05 ms delay floor, 3 fallback 1 ms links; SHA\u2011256 8487b2fb...d4786e), mean admission latency grew from 3.78 [2.73, 4.83] ms (k = 1) to 11.06 [8.76, 13.36] ms (k = 64) vs. 0.94 to 7.32 ms on Team16 7-switch; software rule-count proxy reached 76 rules/switch (152 strict 2x overlap); hardware/P4 TCAM NOT RUN (no hardware switch available).",
        ),
    ]
    add_table(
        doc,
        ["Item", "Paper & Red Placeholder", "Replacement Data / Measured Result (95% t-CI)"],
        red_rows,
        [12, 50, 118],
        body_size=7.6,
    )

    # Normal Table I (3 rows) — keep entire heading + 3 rows together on same page
    add_heading_line(
        doc,
        "Table I (Conference) / Table 2 (Journal): Same-Build Detection and Recovery Latency (ms), Mean [95% CI], n = 10",
        space_before=8,
        space_after=4,
    )
    table1_rows = [
        ("B2", "immediate (k = 1)", "101.1 [96.3, 105.9]", "458.1 [421.1, 495.1]"),
        ("B2", "as B3 (k = 3)", "2096.3 [2091.9, 2100.7]", "454.5 [414.2, 494.8]"),
        ("B3", "damped (k = 3)", "2094.7 [2092.4, 2097.0]", "628.5 [601.0, 656.1]"),
    ]
    add_table(
        doc,
        ["Baseline", "Detector Setting", "Detection Latency (ms)", "Recovery Latency (ms)"],
        table1_rows,
        [24, 42, 57, 57],
        body_size=8.2,
        keep_together=True,
    )

    # Sentences now out of date (1-5 short paragraphs)
    add_heading_line(doc, "Sentences now out of date", space_before=7, space_after=3)
    outdated = [
        ("1. Journal Sec. 4.2 (after Proposition 6): ",
         "The statement that recovery repairs omit step 1 and satisfy Proposition 6 only for a single active intent is out of date. Residual-capacity and bidirectional isolation checks now execute in the control loop on every recovery, verified by zero over-committed links in E14a across all 40 runs on the current build versus 3 over-committed links per run on the earlier baseline build."),
        ("2. Journal Sec. 6.3 and Conference Sec. IV-D / V: ",
         "The phrasing 'Recovery does not yet repeat residual admission' (and listing contention-safe residual recovery under next steps) is out of date. Concurrent recovery now repeats residual admission on current main, while E1-E8 remain documented as baseline measurements taken prior to those engineering audit fixes."),
        ("3. Journal Sec. 5.2 and Conference Sec. IV-B (O3): ",
         "The statement that bound O3 rules share queue identifier 1 (and that unbound O3 came from an earlier build) is out of date. Per-port HTB queue ID allocation now assigns distinct queues per active bandwidth intent, and E9 re-measured both O3 unbound (18.737 [18.039, 19.435] Mbit/s, 25.038% loss) and bound (24.995 [24.995, 24.996] Mbit/s, 0.000% loss, p = 8.05e-9) on the same build."),
        ("4. Conference Sec. IV-C and Journal Sec. 5.3 (strict-vs.-relaxed gap): ",
         "The earlier 70 ms figure (537.9 vs. 467.7 ms across two builds) is superseded by the same-build E9 measurement comparing matched-detector B2 (454.5 [414.2, 494.8] ms) against B3 (628.5 [601.0, 656.1] ms), a 174.0 ms difference (p = 5.27e\u20117). Relative to the earlier draft build, both B2 (458.1 vs. 279.4 ms) and B3 (628.5 vs. 537.9 ms) increased, and the individual contribution of each post-draft change has not been isolated (waiting for OpenFlow barrier replies is the most likely contributor)."),
        ("5. Journal Sec. 5.3 / Eq. (10) and Fig. 4b (S6 transitions): ",
         "Scenario S6 injects 30 macro-cycles of 20 s each (90 raw fault/restoration transitions over 600 s, all seen by B2 immediate k = 1), but from the S6 fault schedule, Phase 5 holds an 18 ms spike for only 1.5 s (vs. 4.2 s in Phase 1 and 3.0 s in Phase 3). Because B3 requires k = 3 consecutive breaches at 1 s sampling, this 1.5 s spike is filtered out, leaving effective confirmable count Nf = 60 transitions (derived from the S6 fault schedule, not measured per phase)."),
    ]
    for lead, body in outdated:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3.5)
        p.paragraph_format.line_spacing = 1.12
        r_lead = p.add_run(lead)
        format_run(r_lead, size=8.4, bold=True, color=DARK)
        r_body = p.add_run(body)
        format_run(r_body, size=8.4, color=DARK)

    # Points to note (5 bullets)
    add_heading_line(doc, "Points to note", space_before=8, space_after=4)
    bullets = [
        "Strict two-phase recovery is 174.0 ms slower than relaxed replacement on the current build (p = 5.27e-7); the cause of the increase over the earlier build is not isolated, the barrier-reply wait (audit fix P3) is the most likely contributor.",
        "Eq. (10) fits the dwell sweep when Nf = 60: in each 20 s cycle of the S6 fault, the third breach lasts only 1.5 s, which gives at most two 1 s samples, so the k = 3 detector cannot confirm it (the k = 1 detector sees all 90 transitions).",
        "Under a one-direction fault, RTT/2 under-reads one-way delay by up to 19.0 ms and would wrongly report the 35 ms budget as met on two routes (E15).",
        "The live E14 check found two defects, now fixed: an OVS HTB queue erased Mininet's netem delay on bandwidth-intent ports (only O3 used such intents, so earlier latency results are unaffected), and simultaneous recoveries all planned onto the same 40 Mbit/s link (60 Mbit/s reserved), which the sequential E14a did not exercise.",
        "Not run: hardware/P4 TCAM measurement for E16 (no hardware switch available).",
    ]
    for body in bullets:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Mm(4.5)
        p.paragraph_format.first_line_indent = Mm(-4.5)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3.0)
        p.paragraph_format.line_spacing = 1.12
        r_t = p.add_run("• " + body)
        format_run(r_t, size=8.4, color=DARK)

    # Exact required last line
    p_last = doc.add_paragraph()
    p_last.paragraph_format.space_before = Pt(7)
    p_last.paragraph_format.space_after = Pt(0)
    r_last = p_last.add_run(
        "Full data, scripts and audit trail: docs/RED_ITEMS_RESPONSE_2026-11.md on branch exp/red-items-2026-11."
    )
    format_run(r_last, size=8.5, bold=True, color=NAVY)

    doc.save(str(OUT_DOCX))
    print(f"Wrote {OUT_DOCX}")


if __name__ == "__main__":
    main()
