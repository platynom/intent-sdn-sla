"""Sir's review module: red items in both paper drafts and how each was resolved.

Content is a faithful summary of docs/RED_ITEMS_RESPONSE_2026-11.md (PR #3).
Served at /review (embedded as the "Sir's review" dashboard tab) and
/api/review (JSON). The two-page response PDF is served at /review/response.pdf.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()

_REPO = Path(__file__).resolve().parents[2]
RESPONSE_PDF = _REPO / "docs" / "sir_response" / "Team16_Red_Items_Response.pdf"

CONF = "Conference draft"
JOUR = "Journal draft"

REVIEW: Dict[str, Any] = {
    "ask": ("Dr. Navin Kumar sent two paper drafts (conference and extended journal) with the "
            "places that still needed our data marked in red, and asked us to fill them. "
            "Everything was measured on the current build (commit 75f2d2e), n = 10 per group."),
    "stats": [
        {"value": "14", "label": "red items in the two drafts"},
        {"value": "12", "label": "filled with measured data"},
        {"value": "5", "label": "out-of-date draft sentences corrected"},
        {"value": "~700", "label": "emulated runs (E9 to E16)"},
    ],
    "items": [
        {"id": "C1", "group": "red", "paper": CONF, "where": "p. 3, Sec. IV-A, Table I",
         "red": "[rerun B2 on the current build]", "status": "done", "exp": "E9",
         "did": "Re-ran B2, matched-detector B2 and B3 on the same build (75f2d2e), n = 10 each.",
         "result": ("B2 (k=1): 101.1 ms detection, 458.1 ms recovery. Matched B2 (k=3): 2096.3 / "
                    "454.5 ms. B3: 2094.7 / 628.5 ms. Strict two-phase recovery is 174.0 ms slower "
                    "than matched B2 (p = 5.27e-7, Welch t-test)."),
         "evidence": ["experiments/results/redfill_2026-11/E9/summary.csv",
                      "experiments/results/redfill_2026-11/E9/welch_tests.csv"]},
        {"id": "C2", "group": "red", "paper": CONF, "where": "p. 4, Sec. IV-C, Transitions (E4)",
         "red": "[confirm the old and new paths of E4]", "status": "done", "exp": "Code + E12",
         "did": "Inspected the E4 script and topology, then re-measured with E12 path pair A.",
         "result": ("Old path north s1-s2-s3-s7 with a 40 ms fault on s1-eth2 (44 ms configured); "
                    "new path middle s1-s4-s5-s7 (15 ms). Configured difference 29 ms; measured "
                    "28 reordered packets at 1000 pkt/s = 28.0 ms."),
         "evidence": ["experiments/scenarios/e4_packet_loss.sh", "topology/topology_spec.py",
                      "experiments/results/redfill_2026-11/E12/model_comparison.csv"]},
        {"id": "J1", "why": "Not a data item. Choosing the corresponding author and stating funding is the team's decision, not something an experiment can fill. Suggested: \u201cThis work received no external funding.\u201d",  "group": "red", "paper": JOUR, "where": "p. 1, author/funding footnote",
         "red": "[Corresponding author and funding acknowledgement, if any.]", "status": "team",
         "exp": "Editorial",
         "did": "Not a data item. Left for the team to decide.",
         "result": "Suggested funding sentence: “This work received no external funding.” Corresponding author: team decision.",
         "evidence": []},
        {"id": "J2", "why": "The journal must cite the conference paper, which is not accepted yet. The placeholder stays until acceptance; nothing can be filled now.",  "group": "red", "paper": JOUR, "where": "p. 2, Introduction",
         "red": "[citation once accepted]", "status": "wait", "exp": "Editorial",
         "did": "Left as is by design.",
         "result": "Filled once the conference paper is accepted.",
         "evidence": []},
        {"id": "J3", "group": "red", "paper": JOUR, "where": "p. 7, Sec. 5.1, Table 2",
         "red": "[rerun B2 on the current build]", "status": "done", "exp": "E9",
         "did": "Same same-build rerun as C1, plus O3 bound and unbound re-measured on the same build.",
         "result": ("Table 2 updated with the C1 numbers. O3 on 75f2d2e: unbound 18.74 Mbit/s with "
                    "25.0% loss vs bound 24.995 Mbit/s with 0% loss."),
         "evidence": ["experiments/results/redfill_2026-11/E9/summary.csv"]},
        {"id": "J4", "group": "red", "paper": JOUR, "where": "p. 9, Sec. 5.3, Transitions (E4)",
         "red": "[confirm the old and new paths of E4]", "status": "done", "exp": "Code + E12",
         "did": "Same confirmation as C2.",
         "result": "North (44 ms with fault) to middle (15 ms); 29 ms configured vs 28 ms measured.",
         "evidence": ["experiments/scenarios/e4_packet_loss.sh",
                      "experiments/results/redfill_2026-11/E12/model_comparison.csv"]},
        {"id": "J5", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E9",
         "red": "[result]", "status": "done", "exp": "E9",
         "did": "Same-build rerun of detection and recovery.",
         "result": ("Recovery: B2 458.1 ms, matched B2 454.5 ms, B3 628.5 ms (+174.0 ms, p = 5.27e-7). "
                    "O3 unbound 18.74 Mbit/s (25.0% loss)."),
         "evidence": ["experiments/results/redfill_2026-11/E9/summary.csv"]},
        {"id": "J6", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E10",
         "red": "[result]", "status": "done", "exp": "E10",
         "did": "Swept k = 1 to 5 and sampling interval 0.25 / 0.5 / 1 s (15 settings, 150 runs).",
         "result": ("Measured detection time agrees with Eq. (9), Tdet = (k-1)Δt + t0, within 0.00% "
                    "to -5.46%; fitted t0 = 97.6 ms (R² = 0.99996)."),
         "evidence": ["experiments/results/redfill_2026-11/E10/model_comparison.csv",
                      "experiments/results/redfill_2026-11/E10/t0_fit.json"]},
        {"id": "J7", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E11",
         "red": "[result]", "status": "done", "exp": "E11",
         "did": "Swept dwell time 0 / 5 / 10 / 20 / 30 s on the S6 oscillation scenario (50 ten-minute runs).",
         "result": ("Reroutes per 10 min fell from 60.0 (dwell 0 s) to 49.2 (10 s), 30.0 (20 s) and "
                    "19.4 (30 s), within -0.8% to +10.5% of Eq. (10) using 60 confirmable transitions."),
         "evidence": ["experiments/results/redfill_2026-11/E11/model_comparison.csv"]},
        {"id": "J8", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E12",
         "red": "[result]", "status": "done", "exp": "E12",
         "did": "Three path pairs x 250 / 1000 / 4000 pkt/s x relaxed and strict (180 runs).",
         "result": ("Relaxed updates lost 10.4 to 172.2 packets (update gap 40.5 to 43.2 ms, model 41 ms); "
                    "strict updates lost 0 and reordered 4.1 to 114.3 packets."),
         "evidence": ["experiments/results/redfill_2026-11/E12/model_comparison.csv"]},
        {"id": "J9", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E13",
         "red": "[result]", "status": "done", "exp": "E13",
         "did": "Measured false confirmations under 6 ms normal jitter (n = 10, 600 samples per run).",
         "result": ("Naive detector 0.128 (predicted 0.1255); EWMA with k = 1: 0.00183; k = 2 and k = 3: "
                    "0 false confirmations."),
         "evidence": ["experiments/results/redfill_2026-11/E13/model_comparison.csv"]},
        {"id": "J10", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E14",
         "red": "[result]", "status": "done", "exp": "E14",
         "did": "Concurrent reroutes of 4 to 16 intents, old build cf25af2 vs current 75f2d2e (40 runs each).",
         "result": ("Old build over-committed all 3 middle-path links (up to 1.60x capacity); current build: "
                    "0 over-committed links. The live variant E14b now also passes (27 Nov, n = 11, 0 over-committed links, 0% loss; see L1)."),
         "evidence": ["experiments/results/redfill_2026-11/E14/summary.csv"]},
        {"id": "J11", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E15",
         "red": "[result]", "status": "done", "exp": "E15",
         "did": "Compared shared-clock one-way delay with RTT/2 on all three routes (60 runs).",
         "result": ("Healthy paths agree within 0.02 ms. Under a 40 ms one-direction fault, RTT/2 "
                    "under-reads forward delay by up to 19.02 ms and would wrongly clear the north and middle routes."),
         "evidence": ["experiments/results/redfill_2026-11/E15/model_comparison.csv"]},
        {"id": "J12", "group": "red", "paper": JOUR, "where": "p. 11, Table 5, row E16",
         "red": "[result]", "status": "done", "exp": "E16",
         "did": "Ran admission on the larger Geant2012 topology (40 nodes, 61 links; copy from a third-party mirror).",
         "result": ("Admission time 3.78 ms (1 intent) to 11.06 ms (64 intents), vs 0.94 to 7.32 ms on our "
                    "7-switch topology. Hardware TCAM not measured (no hardware/P4 switch)."),
         "evidence": ["experiments/results/redfill_2026-11/E16/summary.csv"]},
        {"id": "U1", "group": "stale", "paper": JOUR, "where": "Sec. 4.2, p. 7",
         "red": "“...satisfies Proposition 6 only when a single intent is active.”", "status": "done",
         "exp": "Audit D2 + E14",
         "did": "Audit fix D2: reroutes now run residual-capacity admission and isolation checks.",
         "result": "Proposition 6 holds for concurrent multi-intent recovery; validated by E14.",
         "evidence": ["docs/AUDIT_FIXES_2026-11.md", "src/telemetry/loop.py"]},
        {"id": "U2", "group": "stale", "paper": "Both drafts", "where": "Journal p. 11, Conference p. 5",
         "red": "“Recovery does not yet repeat residual admission.”", "status": "done",
         "exp": "Audit D2, M2",
         "did": "Implemented (D2). M2 also re-admits preempted intents when capacity frees up.",
         "result": "Listed as future work in the drafts; now done and measured (E14).",
         "evidence": ["docs/AUDIT_FIXES_2026-11.md"]},
        {"id": "U3", "group": "stale", "paper": "Both drafts", "where": "O3 paragraphs",
         "red": "“...the bound rules share one queue identifier...”", "status": "done",
         "exp": "Audit P1 + E9",
         "did": "Audit fix P1: each bandwidth intent gets its own queue ID per port.",
         "result": "O3 bound and unbound both re-measured on the same build (E9).",
         "evidence": ["src/enforcement/queues.py", "docs/AUDIT_FIXES_2026-11.md"]},
        {"id": "U4", "group": "stale", "paper": "Both drafts", "where": "Conference Sec. IV-C, Journal Sec. 5.3",
         "red": "Strict-vs-relaxed recovery overhead quoted as 70 ms (two different builds)", "status": "done",
         "exp": "E9",
         "did": "Measured both on one build.",
         "result": "Correct same-build overhead is 174.0 ms (454.5 vs 628.5 ms, p = 5.27e-7).",
         "evidence": ["experiments/results/redfill_2026-11/E9/welch_tests.csv"]},
        {"id": "U5", "group": "stale", "paper": JOUR, "where": "Sec. 5.3, Eq. (10), Fig. 4b",
         "red": "90 confirmable fault transitions assumed for the dwell model", "status": "done",
         "exp": "Script check + E11",
         "did": "Checked the S6 schedule: one phase lasts only 1.5 s, too short for k = 3 at 1 Hz.",
         "result": "B3 can confirm 60 transitions (B2 reacts to all 90); both predictions reported in E11.",
         "evidence": ["experiments/scenarios/e6_oscillation.sh"]},
        {"id": "L1", "group": "limit", "paper": "Disclosure", "where": "E14b (resolved 27 Nov 2026)",
         "red": "Live multi-intent contention check", "status": "done", "exp": "E14b",
         "did": ("Was NOT RUN on 19 Nov: the OVS HTB bandwidth queue erased Mininet's netem delay, so the fault "
                 "could not be injected. Fixed on 27 Nov: queues.py now re-attaches the netem delay under every "
                 "HTB queue class. The first live run then exposed a second defect, simultaneous recoveries all "
                 "planning onto the same 40 Mbit/s link (60 Mbit/s reserved), fixed in loop.py by serialised "
                 "planning with an in-flight reservation ledger."),
         "result": ("Passes, n = 11 (build 449aa7e): four 20 Mbit/s intents leave the faulted north path (0 of 44 "
                    "placements left on it), every run ends 2 south + 2 middle, 0 over-committed links (max load "
                    "1.000 of capacity), 19.999 Mbit/s per flow, 0% loss."),
         "evidence": ["experiments/results/redfill_2026-11/E14_LIVE/summary_new.csv",
                      "experiments/results/redfill_2026-11/E14_LIVE/routes_and_load.csv",
                      "tests/test_netem_preservation.py", "tests/test_concurrent_recovery.py"]},
        {"id": "L2", "why": "TCAM is memory inside physical switches; we have no hardware or P4 switch and Open vSwitch has none, so rule counts come from the software model (76 per switch, 152 during two-phase). The topology-zoo.org download reset the connection, so Geant2012 came from a GitHub mirror (SHA-256 recorded). Admission scaling still measured: 3.8 to 11.1 ms.",  "group": "limit", "paper": "Disclosure", "where": "E16",
         "red": "Hardware TCAM usage and official Topology Zoo file", "status": "notrun", "exp": "E16",
         "did": "No hardware/P4 switch available; topology-zoo.org download reset the connection.",
         "result": "Rule counts come from the software model; Geant2012 was taken from a third-party mirror (SHA-256 recorded).",
         "evidence": ["experiments/results/redfill_2026-11/FAILURES.md"]},
        {"id": "L3", "group": "limit", "paper": "Disclosure", "where": "E15, E11",
         "red": "Runs affected by laptop shutdown or pause", "status": "done", "exp": "E11, E15",
         "did": "One E11 run lost (redone); one stale E15 run excluded to E15/excluded/ and replaced.",
         "result": "Every group still has n = 10 valid runs; failures are logged, not hidden.",
         "evidence": ["experiments/results/redfill_2026-11/FAILURES.md"]},
        {"id": "L4", "group": "limit", "paper": "Disclosure", "where": "Scenario scripts",
         "red": "Scripts edited for the sweeps", "status": "done", "exp": "Verification",
         "did": "Only environment-variable overrides added; unset defaults reproduce the original behaviour.",
         "result": "Container tests 326 passed, 11 skipped; summary and manifest verification passed; no src/ change.",
         "evidence": ["docs/RED_ITEMS_RESPONSE_2026-11.md"]},
    ],
    "deliverables": [
        "Two-page response PDF for Sir: docs/sir_response/Team16_Red_Items_Response.pdf",
        "Full item-by-item response with LaTeX-ready text: docs/RED_ITEMS_RESPONSE_2026-11.md",
        "All raw data and summaries: experiments/results/redfill_2026-11/ (merged in PR #3)",
    ],
}


@router.get("/api/review")
def review_data() -> Dict[str, Any]:
    return REVIEW


@router.get("/review/response.pdf")
def review_pdf() -> FileResponse:
    if not RESPONSE_PDF.is_file():
        raise HTTPException(status_code=404, detail="Response PDF not found in this checkout.")
    return FileResponse(str(RESPONSE_PDF), media_type="application/pdf",
                        filename="Team16_Red_Items_Response.pdf")


@router.get("/review", response_class=HTMLResponse)
def review_page() -> str:
    return REVIEW_HTML.replace("__DATA__", json.dumps(REVIEW).replace("</", "<\\/"))


REVIEW_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intent SDN SLA | Sir's Review</title>
<style>
:root{color-scheme:dark;--bg:#07111f;--panel:#0e1d2e;--panel2:#0a1726;--line:#20364b;--txt:#edf5ff;--muted:#93a9bf;--teal:#48e0c0;--blue:#82baff;--red:#ff7185;--amber:#ffd166;--green:#61e5a5}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 12% 0%,#15334a 0,transparent 42%),var(--bg);color:var(--txt);font:14px/1.45 Inter,system-ui,"Segoe UI",sans-serif}
body.embed{background:transparent}body.embed .top{display:none}
button{font:inherit;color:inherit}
.top{display:flex;justify-content:space-between;align-items:center;padding:14px 24px;border-bottom:1px solid var(--line)}
.top a{color:var(--blue);text-decoration:none;border:1px solid var(--line);padding:7px 12px;border-radius:8px}
.wrap{max-width:1380px;margin:0 auto;padding:20px 24px 40px}
h2{margin:0 0 4px;font-size:20px}.ask{color:var(--muted);max-width:980px;margin:0 0 16px}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
.stat{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:14px;padding:14px}
.stat b{display:block;font-size:26px;color:var(--teal)}.stat span{color:var(--muted);font-size:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:#11263a;border:1px solid var(--line);border-radius:999px;padding:6px 12px;cursor:pointer;font-size:12.5px}
.chip.on{background:var(--teal);color:#04131c;border-color:var(--teal);font-weight:700}
.pdf{background:#1a3550;border:1px solid #2c4f70;border-radius:9px;padding:8px 13px;color:var(--txt);text-decoration:none;font-weight:650;font-size:13px}
.list{display:flex;flex-direction:column;gap:8px}
.item{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:12px;overflow:hidden}
.head{display:grid;grid-template-columns:64px minmax(0,1.1fr) minmax(0,1.6fr) 150px 24px;gap:12px;align-items:center;width:100%;background:none;border:0;text-align:left;padding:12px 14px;cursor:pointer}
.head:hover{background:#ffffff06}
.id{font-weight:800;font-size:15px;color:var(--blue)}
.where{font-size:12px;color:var(--muted)}.where b{display:block;color:var(--txt);font-size:13px;font-weight:600}
.red{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;color:#ff9aa9;overflow:hidden;text-overflow:ellipsis}
.badge{position:relative;justify-self:start;font-size:11.5px;font-weight:700;border-radius:999px;padding:4px 10px;border:1px solid;white-space:nowrap}
.s-done{color:var(--green);border-color:#61e5a566;background:#61e5a514}.s-team{color:var(--amber);border-color:#ffd16666;background:#ffd16614}
.s-wait{color:var(--blue);border-color:#82baff66;background:#82baff14}.s-notrun{color:var(--red);border-color:#ff718566;background:#ff718514}
.chev{color:var(--muted);transition:transform .15s}.badge[data-tip]{cursor:help;outline:none}.badge[data-tip]::after{content:' ⓘ';opacity:.85}
.tip{position:fixed;z-index:50;max-width:380px;background:#0b1a2b;border:1px solid #ffd16699;border-radius:10px;padding:10px 12px;font-size:12.5px;line-height:1.45;color:var(--txt);box-shadow:0 10px 30px #000a;pointer-events:none;display:none}
.tip b{display:block;color:var(--amber);margin-bottom:4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.item.open .chev{transform:rotate(90deg)}
.body{display:none;padding:0 14px 14px 90px;border-top:1px solid var(--line)}.item.open .body{display:block}
.body dl{display:grid;grid-template-columns:150px minmax(0,1fr);gap:8px 14px;margin:12px 0 0}
.body dt{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.body dd{margin:0}
.ev{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#b9cbe0;display:block;overflow-wrap:anywhere}.item,.head,.where,.body dd{min-width:0}.body dd,.red{overflow-wrap:anywhere}
.deliv{margin-top:18px;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.deliv h3{margin:0 0 8px;font-size:15px}.deliv li{margin:4px 0;color:var(--muted);overflow-wrap:anywhere}
@media (max-width:900px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.head{grid-template-columns:52px minmax(0,1fr) 24px}.head .red,.head .badge{grid-column:2}.body{padding-left:14px}.body dl{grid-template-columns:1fr}.wrap{padding:16px}}
</style></head><body>
<div class="top"><b>Sir's review: red items and how we resolved them</b><a href="/">← Operator dashboard</a></div>
<main class="wrap">
<h2>Sir's review: what was asked and what we did</h2>
<p class="ask" id="ask"></p>
<section class="stats" id="stats"></section>
<div class="bar"><div class="chips" id="chips"></div><a class="pdf" href="/review/response.pdf" target="_blank" rel="noopener">⬇ Response PDF (22 Nov, before E14b fix)</a></div>
<section class="list" id="list"></section><div class="tip" id="tip" role="tooltip"></div>
<section class="deliv"><h3>Where everything is</h3><ul id="deliv"></ul></section>
</main>
<script>
'use strict';
const D=__DATA__;
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e};
const EMBED=new URLSearchParams(location.search).get('embed')==='1';if(EMBED)document.body.classList.add('embed');
const STATUS={done:'✓ Resolved',team:'Team decision',wait:'Waits for acceptance',notrun:'Not run (disclosed)'};
const FILTERS=[['all','All'],['red','Red items (14)'],['conf','Conference'],['jour','Journal'],['stale','Out-of-date sentences (5)'],['limit','Limitations']];
let filter='all';
function post(){if(EMBED&&window.parent!==window){try{window.parent.postMessage({type:'review-height',height:document.documentElement.scrollHeight},location.origin)}catch(e){}}}
function match(i){if(filter==='all')return true;if(filter==='conf')return i.group==='red'&&i.paper.startsWith('Conference');if(filter==='jour')return i.group==='red'&&i.paper.startsWith('Journal');return i.group===filter}
function badge(i){const b=el('span','badge s-'+i.status,STATUS[i.status]);if(i.why){b.dataset.tip='1';b.tabIndex=0;b.setAttribute('aria-label',STATUS[i.status]+': '+i.why);
 const show=()=>{const t=$('tip');t.replaceChildren(el('b',null,'Why not done'),document.createTextNode(i.why));t.style.display='block';const r=b.getBoundingClientRect();const w=Math.min(380,innerWidth-24);t.style.maxWidth=w+'px';
  const x=Math.min(Math.max(12,r.right-w),innerWidth-w-12);const y=r.bottom+8;t.style.left=x+'px';t.style.top=y+'px';const h=t.getBoundingClientRect().height;if(y+h>innerHeight-8)t.style.top=Math.max(8,r.top-h-8)+'px'};
 const hide=()=>{$('tip').style.display='none'};b.addEventListener('mouseenter',show);b.addEventListener('mouseleave',hide);b.addEventListener('focus',show);b.addEventListener('blur',hide);b.addEventListener('click',e=>{e.stopPropagation();show()})}return b}
function render(){const L=$('list');L.replaceChildren();D.items.filter(match).forEach(i=>{const it=el('article','item');const h=el('button','head');h.type='button';h.setAttribute('aria-expanded','false');
 const w=el('div','where');w.append(el('b',null,i.paper),document.createTextNode(i.where));
 h.append(el('span','id',i.id),w,el('span','red',i.red),badge(i),el('span','chev','›'));
 const b=el('div','body');const dl=el('dl');
 [['Asked (red text)',i.red],['Experiment',i.exp],['What we did',i.did],['Result',i.result]].forEach(([k,v])=>{dl.append(el('dt',null,k),el('dd',null,v))});
 if(i.evidence.length){const dd=el('dd');i.evidence.forEach(p=>dd.append(el('span','ev',p)));dl.append(el('dt',null,'Evidence'),dd)}
 b.append(dl);h.onclick=()=>{const o=it.classList.toggle('open');h.setAttribute('aria-expanded',String(o));post()};it.append(h,b);L.append(it)});post()}
$('ask').textContent=D.ask;
D.stats.forEach(s=>{const a=el('article','stat');a.append(el('b',null,s.value),el('span',null,s.label));$('stats').append(a)});
FILTERS.forEach(([k,t])=>{const c=el('button','chip'+(k===filter?' on':''),t);c.type='button';c.onclick=()=>{filter=k;document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));c.classList.add('on');render()};$('chips').append(c)});
D.deliverables.forEach(d=>$('deliv').append(el('li',null,d)));
render();if('ResizeObserver' in window)new ResizeObserver(post).observe(document.body);
</script></body></html>"""
