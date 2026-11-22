"""Self-contained HTML for the hands-on intent playground (no CDN, no external assets)."""

PLAYGROUND_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intent SDN SLA | Try an Intent</title>
<meta name="description" content="Team 16 hands-on intent playground: describe an SLA, see the controller's decision, submit it">
<style>
:root{color-scheme:dark;--bg:#07111f;--panel:#0e1d2e;--panel2:#0a1726;--line:#20364b;--txt:#edf5ff;--muted:#93a9bf;--teal:#48e0c0;--blue:#82baff;--red:#ff7185;--amber:#ffd166;--green:#61e5a5}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at 12% 0%,#15334a 0,transparent 42%),var(--bg);color:var(--txt);font:14px/1.45 Inter,system-ui,"Segoe UI",sans-serif}
button,input,select,textarea{font:inherit;color:inherit}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 24px;border-bottom:1px solid var(--line);background:#07111fcc;position:sticky;top:0;z-index:5;backdrop-filter:blur(6px)}
header h1{margin:0;font-size:17px}header p{margin:0;color:var(--muted);font-size:12px}
a.back{color:var(--blue);text-decoration:none;border:1px solid var(--line);padding:7px 12px;border-radius:8px}
a.back:hover{border-color:var(--blue)}
.wrap{max-width:1380px;margin:0 auto;padding:20px 24px 40px}
.intro{color:var(--muted);margin:0 0 16px;max-width:900px}
.grid{display:grid;grid-template-columns:minmax(0,440px) minmax(0,1fr);gap:18px;align-items:start}
.panel{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:18px}
.panel h2{margin:0 0 4px;font-size:15px}.panel .sub{margin:0 0 12px;color:var(--muted);font-size:12px}
.step{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#173049;color:var(--teal);font-size:12px;margin-right:8px;font-weight:700}
.presets{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.chip{background:#11263a;border:1px solid var(--line);border-radius:999px;padding:5px 11px;cursor:pointer;font-size:12px}
.chip:hover{border-color:var(--teal)}
.form{display:grid;grid-template-columns:1fr 1fr;gap:9px 10px}
.form label{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.form .full{grid-column:1/-1}
input,select,textarea{background:#081523;border:1px solid var(--line);border-radius:8px;padding:7px 9px;text-transform:none;letter-spacing:0}
input:focus,select:focus,textarea:focus{outline:2px solid #48e0c055;border-color:var(--teal)}
textarea{width:100%;min-height:210px;font:12px/1.5 ui-monospace,Consolas,monospace;resize:vertical}
.links{display:flex;flex-wrap:wrap;gap:6px}
.links label{flex-direction:row;align-items:center;gap:5px;background:#081523;border:1px solid var(--line);border-radius:7px;padding:4px 8px;text-transform:none;letter-spacing:0;font-size:12px;color:var(--txt)}
.faults{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
.faults label{display:flex;justify-content:space-between;align-items:center;gap:6px;font-size:12px;background:#081523;border:1px solid var(--line);border-radius:8px;padding:4px 4px 4px 9px}
.faults select{padding:3px 5px;font-size:12px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.btn{border:0;border-radius:9px;padding:10px 14px;font-weight:650;cursor:pointer}
.btn.primary{background:var(--teal);color:#04131c}.btn.secondary{background:#1a3550;color:var(--txt);border:1px solid #2c4f70}
.btn.ghost{background:transparent;border:1px solid var(--line);color:var(--muted)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.hint{font-size:12px;color:var(--muted);margin:8px 0 0}
svg{width:100%;height:auto;display:block}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-top:6px}
.sw{display:inline-block;width:18px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px}
.verdict{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.badge{font-size:12px;font-weight:700;border-radius:999px;padding:4px 10px;border:1px solid}
.b-admit{color:var(--green);border-color:#61e5a566;background:#61e5a514}
.b-preempt{color:var(--amber);border-color:#ffd16666;background:#ffd16614}
.b-reject,.b-error{color:var(--red);border-color:#ff718566;background:#ff718514}
.b-info{color:var(--blue);border-color:#82baff66;background:#82baff14}
.reason{background:#081523;border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin:0 0 10px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
tr.chosen td{background:#48e0c012}
.ok{color:var(--green)}.bad{color:var(--red)}
.warn{color:var(--amber);font-size:12.5px;margin:6px 0}
.mono{font-family:ui-monospace,Consolas,monospace}
pre{background:#081523;border:1px solid var(--line);border-radius:9px;padding:10px;overflow:auto;font-size:12px;margin:8px 0 0;max-height:260px}
.empty{color:var(--muted);font-size:13px}
.live li{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
.live ul{list-style:none;margin:0;padding:0}
.small{font-size:12px;color:var(--muted)}
.note{font-size:12px;color:var(--muted);border-left:3px solid var(--amber);padding:4px 10px;margin:8px 0 0}
@media (max-width:980px){.grid{grid-template-columns:1fr}.wrap{padding:16px}header{padding:12px 16px}}
@media (max-width:520px){.form,.faults{grid-template-columns:1fr}}
</style></head>
<body>
<header><div><h1>Try an intent</h1><p>Hands-on · say what the service needs, the controller decides how</p></div><a class="back" href="/">← Operator dashboard</a></header>
<main class="wrap">
<p class="intro">Describe a service-level requirement in plain fields (or edit the YAML). <b>Explain</b> shows how admission control and path selection would decide on the current network, without changing anything. <b>Submit</b> sends it to the real intent API, exactly as an operator would, and it then appears on the dashboard.</p>
<div class="grid">
<div>
<section class="panel"><h2><span class="step">1</span>Describe the intent</h2><p class="sub">Start from a preset or fill in the fields.</p>
<div class="presets" id="presets"></div>
<div class="form">
<label>Intent ID<input id="f-id" value="INT-101" maxlength="12"></label>
<label>Tenant<input id="f-tenant" value="guest-urllc" maxlength="64"></label>
<label>Source host<select id="f-src"></select></label>
<label>Destination host<select id="f-dst"></select></label>
<label>Protocol<select id="f-proto"><option>udp</option><option>tcp</option><option>icmp</option><option>any</option></select></label>
<label>Port<input id="f-dport" type="number" min="1" max="65535" value="5701"></label>
<label>Min bandwidth (Mbit/s)<input id="f-bw" type="number" min="0" step="any" value="20" placeholder="blank = none"></label>
<label>Max latency (ms)<input id="f-lat" type="number" min="0" step="any" value="20" placeholder="blank = none"></label>
<label>Max loss (%)<input id="f-loss" type="number" min="0" max="100" step="any" value="0.5" placeholder="blank = none"></label>
<label>Priority (1 = highest)<select id="f-prio"><option>1</option><option selected>2</option><option>3</option><option>4</option><option>5</option></select></label>
<label>Consistency<select id="f-cons"><option value="strict">strict (two-phase, lossless)</option><option value="relaxed">relaxed (direct install)</option></select></label>
<label>On violation<select id="f-viol"><option>reroute</option><option>degrade</option><option>alert_only</option></select></label>
<label class="full">Avoid links<div class="links" id="f-avoid"></div></label>
</div>
<p class="hint">Hosts: h1 → h2 crosses the whole network (three possible routes). Other pairs are shorter.</p>
</section>

<section class="panel"><h2><span class="step">2</span>What-if faults <span class="small">(planning only)</span></h2><p class="sub">Break or slow a link and see where the controller would route instead. This changes only the dry run, never the live network.</p>
<div class="faults" id="faults"></div>
</section>

<section class="panel"><h2><span class="step">3</span>Intent document</h2><p class="sub">This exact YAML is what the API receives. You can edit it by hand.</p>
<textarea id="yaml" spellcheck="false" aria-label="Intent YAML"></textarea>
<div class="row"><button class="btn ghost" id="regen" type="button">Rebuild from fields</button></div>
<div class="row">
<button class="btn secondary" id="explain" type="button">Explain decision (dry run)</button>
<button class="btn primary" id="submit" type="button">Submit to controller</button>
</div>
<p class="note" id="mode-note">Submit and withdraw go through the real intent API with all its checks (validation, duplicate and overlap refusal).</p>
</section>
</div>

<div>
<section class="panel"><h2>Network view</h2><p class="sub" id="topo-sub">Link labels show free capacity / total (Mbit/s) and delay. Thicker teal = chosen path.</p>
<svg id="topo" viewBox="0 0 640 380" role="img" aria-label="Network topology"></svg>
<div class="legend"><span><i class="sw" style="background:var(--teal)"></i>chosen path</span><span><i class="sw" style="background:var(--red)"></i>rejected route</span><span><i class="sw" style="background:#5d7690"></i>link</span><span><i class="sw" style="background:var(--amber)"></i>what-if fault</span></div>
</section>

<section class="panel" id="result-panel"><h2>Controller decision</h2>
<div id="result"><p class="empty">Press <b>Explain decision</b> to see how the controller would handle this intent, or <b>Submit</b> to send it.</p></div>
</section>

<section class="panel live"><h2>Live intents</h2><p class="sub">Intents currently holding capacity. Withdraw one to free its bandwidth.</p>
<div id="live"><p class="empty">Loading…</p></div>
</section>
</div>
</div>
</main>
<script>
'use strict';
const $=id=>document.getElementById(id);
const S={topo:null,plan:null,yamlDirty:false};
const POS={s1:[120,110],s2:[320,60],s3:[520,110],s4:[240,195],s5:[400,195],s6:[120,300],s7:[520,300],
 h1:[40,60],h2:[600,255],h3:[200,262],h4:[440,262],h5:[320,14],h6:[40,345],h7:[600,60],h8:[600,345]};
const PRESETS=[
 {label:'URLLC h1→h2 (fits)',v:{tenant:'guest-urllc',src:'h1',dst:'h2',proto:'udp',dport:5701,bw:20,lat:20,loss:0.5,prio:2,cons:'strict',viol:'reroute',avoid:[]}},
 {label:'Ultra-low latency 8 ms',v:{tenant:'guest-haptics',src:'h1',dst:'h2',proto:'udp',dport:5702,bw:10,lat:8,loss:0.1,prio:1,cons:'strict',viol:'reroute',avoid:[]}},
 {label:'Big video 60 Mbit/s',v:{tenant:'guest-video',src:'h1',dst:'h2',proto:'tcp',dport:5703,bw:60,lat:30,loss:1,prio:3,cons:'relaxed',viol:'degrade',avoid:[]}},
 {label:'Avoid the fast route',v:{tenant:'guest-secure',src:'h1',dst:'h2',proto:'udp',dport:5704,bw:10,lat:40,loss:1,prio:2,cons:'strict',viol:'reroute',avoid:['s2-s3']}},
 {label:'Impossible (500 Mbit/s)',v:{tenant:'guest-bulk',src:'h1',dst:'h2',proto:'tcp',dport:5705,bw:500,lat:50,loss:'',prio:4,cons:'relaxed',viol:'degrade',avoid:[]}},
];
const INVALID_YAML="# Invalid on purpose: max_jitter_ms is not one of the five frozen constraints\nintent:\n  id: INT-190\n  tenant: rogue\n  priority: 2\n  match: {src: 10.0.0.1/32, dst: 10.0.0.2/32}\n  guarantee:\n    min_bandwidth_mbps: 10\n    max_jitter_ms: 5\n";
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const svgEl=(tag,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e};
const num=v=>v===null||v===undefined||v===''?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
function hostIp(name){const h=(S.topo?.hosts||[]).find(x=>x.name===name);return h?h.ip:'10.0.0.1'}
function linkNames(){return (S.topo?.links||[]).map(l=>l.name)}

function buildYaml(){
 const g=[];const bw=$('f-bw').value.trim(),lat=$('f-lat').value.trim(),loss=$('f-loss').value.trim();
 if(bw!=='')g.push('    min_bandwidth_mbps: '+bw);
 if(lat!=='')g.push('    max_latency_ms: '+lat);
 if(loss!=='')g.push('    max_loss_pct: '+loss);
 const avoid=[...document.querySelectorAll('#f-avoid input:checked')].map(i=>i.value);
 if(avoid.length)g.push('    avoid_links: ['+avoid.join(', ')+']');
 const proto=$('f-proto').value,port=$('f-dport').value.trim();
 const m=['    src: '+hostIp($('f-src').value)+'/32','    dst: '+hostIp($('f-dst').value)+'/32','    proto: '+proto];
 if(port!==''&&proto!=='icmp'&&proto!=='any')m.push('    dport: '+port);
 return ['intent:','  id: '+$('f-id').value.trim(),'  tenant: '+$('f-tenant').value.trim(),'  priority: '+$('f-prio').value,
  '  match:',...m,'  guarantee:',...(g.length?g:['    {}']),'  consistency: '+$('f-cons').value,'  on_violation: '+$('f-viol').value,'  dwell_seconds: 10',''].join('\n');
}
function syncYaml(){if(!S.yamlDirty)$('yaml').value=buildYaml()}
function nextId(){const used=new Set([...(S.topo?.intents||[]).map(i=>i.id),...(S.allIds||[])]);for(let n=101;n<999;n++){const id='INT-'+n;if(!used.has(id))return id}return 'INT-999'}

function applyPreset(p){const v=p.v;$('f-id').value=nextId();$('f-tenant').value=v.tenant;$('f-src').value=v.src;$('f-dst').value=v.dst;$('f-proto').value=v.proto;$('f-dport').value=v.dport;
 $('f-bw').value=v.bw;$('f-lat').value=v.lat;$('f-loss').value=v.loss;$('f-prio').value=String(v.prio);$('f-cons').value=v.cons;$('f-viol').value=v.viol;
 document.querySelectorAll('#f-avoid input').forEach(i=>{i.checked=v.avoid.includes(i.value)});S.yamlDirty=false;syncYaml();explain()}

function buildControls(){
 const pr=$('presets');pr.replaceChildren();
 PRESETS.forEach(p=>{const b=el('button','chip',p.label);b.type='button';b.onclick=()=>applyPreset(p);pr.append(b)});
 const inv=el('button','chip','Invalid document');inv.type='button';inv.onclick=()=>{$('yaml').value=INVALID_YAML;S.yamlDirty=true;explain()};pr.append(inv);
 for(const id of ['f-src','f-dst']){const s=$(id);s.replaceChildren();S.topo.hosts.forEach(h=>{const o=el('option',null,h.name+' · '+h.ip+' (on '+h.switch+')');o.value=h.name;s.append(o)})}
 $('f-src').value='h1';$('f-dst').value='h2';
 const av=$('f-avoid');av.replaceChildren();const fl=$('faults');fl.replaceChildren();
 linkNames().forEach(n=>{const l=el('label');const c=el('input');c.type='checkbox';c.value=n;c.onchange=()=>{S.yamlDirty=false;syncYaml()};l.append(c,document.createTextNode(n));av.append(l);
  const fw=el('label');fw.append(document.createTextNode(n));const s=el('select');s.dataset.link=n;
  [['ok','normal'],['delay','+40 ms delay'],['down','link down']].forEach(([v,t])=>{const o=el('option',null,t);o.value=v;s.append(o)});
  s.onchange=()=>{drawTopo();if(S.plan)explain()};fw.append(s);fl.append(fw)});
 document.querySelectorAll('.form input,.form select').forEach(i=>i.addEventListener('input',()=>{S.yamlDirty=false;syncYaml()}));
 $('yaml').addEventListener('input',()=>{S.yamlDirty=true});
 $('regen').onclick=()=>{S.yamlDirty=false;syncYaml()};
 $('explain').onclick=explain;$('submit').onclick=submit;
 if(S.topo.read_only){$('submit').disabled=true;$('mode-note').textContent='Read-only mode: submit and withdraw are disabled on this dashboard.'}
}
function faults(){return [...document.querySelectorAll('#faults select')].filter(s=>s.value!=='ok').map(s=>({link:s.dataset.link,mode:s.value,extra_delay_ms:40}))}

function drawTopo(){
 const svg=$('topo');svg.replaceChildren();if(!S.topo)return;
 const fmap=Object.fromEntries(faults().map(f=>[f.link,f.mode]));
 const chosen=new Set(S.plan?.chosen?.links||[]);
 const rejected=new Set();(S.plan?.candidates||[]).filter(c=>!c.feasible).forEach(c=>c.links.forEach(l=>{if(!chosen.has(l))rejected.add(l)}));
 S.topo.hosts.forEach(h=>{const [x1,y1]=POS[h.name],[x2,y2]=POS[h.switch];svg.append(svgEl('line',{x1,y1,x2,y2,stroke:'#2a4058','stroke-width':1.5,'stroke-dasharray':'3 3'}))});
 S.topo.links.forEach(l=>{const [x1,y1]=POS[l.a],[x2,y2]=POS[l.b];const f=fmap[l.name];
  let stroke='#5d7690',w=3,dash='';
  if(rejected.has(l.name)){stroke='#ff7185';w=3;dash='7 5'}
  if(chosen.has(l.name)){stroke='#48e0c0';w=7}
  if(f==='down'||l.down){stroke='#ffd166';dash='4 6';w=3}else if(f==='delay'&&!chosen.has(l.name)){stroke='#ffd166'}
  svg.append(svgEl('line',{x1,y1,x2,y2,stroke,'stroke-width':w,'stroke-linecap':'round','stroke-dasharray':dash}));
  const mx=(x1+x2)/2,my=(y1+y2)/2;const delay=l.delay_ms+(f==='delay'?40:0);
  const label=(f==='down'||l.down)?'DOWN':(num(l.residual_mbps)+'/'+num(l.capacity_mbps)+' · '+num(delay)+' ms');
  const t=svgEl('text',{x:mx,y:my-7,'text-anchor':'middle','font-size':11,fill:f?'#ffd166':'#b9cbe0','paint-order':'stroke',stroke:'#07111f','stroke-width':4});t.textContent=label;svg.append(t)});
 const ends=new Set([S.plan?.intent?.src_switch,S.plan?.intent?.dst_switch]);
 S.topo.switches.forEach(s=>{const [x,y]=POS[s];const on=(S.plan?.chosen?.switches||[]).includes(s);
  svg.append(svgEl('rect',{x:x-20,y:y-15,width:40,height:30,rx:8,fill:on?'#123d3a':'#11263a',stroke:on?'#48e0c0':ends.has(s)?'#82baff':'#3b5875','stroke-width':2}));
  const t=svgEl('text',{x,y:y+5,'text-anchor':'middle','font-size':13,'font-weight':700,fill:'#edf5ff'});t.textContent=s;svg.append(t)});
 const src=$('f-src').value,dst=$('f-dst').value;
 S.topo.hosts.forEach(h=>{const [x,y]=POS[h.name];const sel=h.name===src||h.name===dst;
  svg.append(svgEl('circle',{cx:x,cy:y,r:13,fill:sel?'#1d3352':'#0b1928',stroke:sel?'#82baff':'#2f4862','stroke-width':sel?2:1.5}));
  const t=svgEl('text',{x,y:y+4,'text-anchor':'middle','font-size':11,fill:sel?'#edf5ff':'#93a9bf'});t.textContent=h.name;svg.append(t)});
}

function verdictBadge(v){const map={admit:['ADMITTED','b-admit'],preempt:['ADMITTED BY PREEMPTION','b-preempt'],reject:['REJECTED','b-reject']};const [t,c]=map[v]||[String(v).toUpperCase(),'b-info'];return el('span','badge '+c,t)}

function renderPlan(p){
 const box=$('result');box.replaceChildren();
 const head=el('div','verdict');
 if(!p.ok){head.append(el('span','badge b-error','INVALID INTENT · HTTP 422'));box.append(head);
  box.append(el('p','reason','The intent grammar is frozen to five constraint types. The API would refuse this document with these reasons:'));
  const ul=el('ul');p.errors.forEach(e=>{const li=el('li');li.append(el('span','mono',e.path+': '),document.createTextNode(e.message));ul.append(li)});box.append(ul);return}
 head.append(el('span','badge b-info','DRY RUN'),verdictBadge(p.decision.verdict));
 if(p.would_be_status===409)head.append(el('span','badge b-error','SUBMIT WOULD GET 409'));
 box.append(head);
 box.append(el('p','reason',p.decision.reason));
 if(p.decision.preempted_intent_id)box.append(el('p','warn','Lower-priority intent '+p.decision.preempted_intent_id+' would lose its reservation.'));
 p.warnings.forEach(w=>box.append(el('p','warn','⚠ '+w)));
 if(p.faults_applied.length)box.append(el('p','small','What-if faults applied: '+p.faults_applied.map(f=>f.link+(f.mode==='down'?' down':' +'+f.extra_delay_ms+' ms')).join(', ')));
 if(p.chosen){const c=p.chosen;box.append(el('p',null,'Chosen path: '+c.switches.join(' → ')+'  ·  estimated delay '+num(c.est_latency_ms)+' ms  ·  '+(p.intent.consistency==='strict'?'would be installed with the two-phase (lossless) update':'would be installed directly')))}
 if(p.candidates.length){const t=el('table');const tr=el('tr');['Candidate route','Delay','Free Mbit/s','Result'].forEach(h=>tr.append(el('th',null,h)));const th=el('thead');th.append(tr);t.append(th);const tb=el('tbody');
  p.candidates.forEach(c=>{const r=el('tr',c.chosen?'chosen':'');r.append(el('td','mono',c.switches.join('-')),el('td',null,num(c.delay_ms)+' ms'),el('td',null,num(c.residual_mbps)));
   const res=el('td');res.append(el('span',c.feasible?'ok':'bad',c.chosen?'✔ chosen':c.feasible?'✔ feasible':'✘ '),document.createTextNode(c.feasible&&!c.chosen?' (a better one was picked)':c.feasible?'':c.reason));r.append(res);tb.append(r)});
  t.append(tb);box.append(el('p','small','The three shortest routes the controller considered, checked against the guarantees on the capacity left after existing reservations:'));box.append(t)}
}

function renderSubmit(r){
 const box=$('result');box.replaceChildren();const head=el('div','verdict');
 const ok=r.status>=200&&r.status<300;head.append(el('span','badge '+(ok?'b-admit':'b-error'),'HTTP '+r.status));
 const b=r.body||{};
 if(ok&&b.state)head.append(verdictBadge(b.state==='admitted'?(b.preempted_intent_id?'preempt':'admit'):b.state==='rejected'?'reject':b.state));
 box.append(head);
 let msg='';
 if(r.status===201&&b.state==='admitted')msg='Accepted. '+b.id+' is admitted on '+(b.switches||[]).join(' → ')+'. Its bandwidth is now reserved and it appears on the operator dashboard with its audit trail. Flow rules reach the switches when the Ryu controller is running (shown live in the closed-loop demo).'+(b.preempted_intent_id?' It preempted '+b.preempted_intent_id+'.':'');
 else if(r.status===201)msg='Recorded as '+b.state+': '+((b.reasons&&b.reasons.admission)||'no feasible path')+'. The refusal is explained and audited, never silent.';
 else if(r.status===204)msg='Withdrawn. Its reserved bandwidth is free again.';
 else if(r.status===409)msg='Refused: '+(b.detail||'conflict');
 else if(r.status===422)msg='Invalid intent: the API refused the document.';
 else msg=(b&&b.detail)?String(b.detail):'Unexpected response.';
 box.append(el('p','reason',msg));
 const pre=el('pre');pre.textContent=JSON.stringify(r.body,null,2);box.append(el('p','small','Raw API response:'),pre);
}

async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let j=null;try{j=await r.json()}catch(e){}if(!r.ok)throw Error((j&&j.detail)||('HTTP '+r.status));return j}
function showError(e){const box=$('result');box.replaceChildren();const h=el('div','verdict');h.append(el('span','badge b-error','ERROR'));box.append(h,el('p','reason',String(e.message||e)))}

async function explain(){$('explain').disabled=true;try{S.plan=await post('/api/try/plan',{yaml:$('yaml').value,faults:faults()});renderPlan(S.plan);if(!S.plan.ok)S.plan=null;drawTopo()}catch(e){showError(e)}finally{$('explain').disabled=false}}
async function submit(){$('submit').disabled=true;try{const r=await post('/api/try/submit',{yaml:$('yaml').value});S.plan=null;renderSubmit(r);await loadTopo();
  if(r.status===201&&r.body&&r.body.switches){S.plan={chosen:{switches:r.body.switches,links:r.body.path||[]},candidates:[],intent:{}};drawTopo()}
  if(r.status===201){$('f-id').value=nextId();S.yamlDirty=false;syncYaml()}}catch(e){showError(e)}finally{$('submit').disabled=!!S.topo?.read_only}}
async function withdraw(id){try{const r=await post('/api/try/withdraw/'+encodeURIComponent(id));renderSubmit(r);S.plan=null;await loadTopo()}catch(e){showError(e)}}

function renderLive(){const box=$('live');box.replaceChildren();const xs=S.topo.intents;
 if(!xs.length){box.append(el('p','empty','No intents are holding capacity.'));return}
 const ul=el('ul');xs.forEach(i=>{const li=el('li');const d=el('div');d.append(el('b',null,i.id+' '),el('span','small',i.tenant+' · priority '+i.priority+' · '+(i.min_bandwidth_mbps?num(i.min_bandwidth_mbps)+' Mbit/s':'no bandwidth reserved')+' · '+(i.switches.length?i.switches.join('-'):'no path')));
  const b=el('button','btn ghost','Withdraw');b.type='button';b.style.padding='5px 10px';b.disabled=!!S.topo.read_only;b.onclick=()=>withdraw(i.id);li.append(d,b);ul.append(li)});box.append(ul)}

async function loadTopo(){const r=await fetch('/api/try/topology',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);S.topo=await r.json();
 try{const d=await (await fetch('/api/dashboard',{cache:'no-store'})).json();S.allIds=(d.intents||[]).map(i=>i.id)}catch(e){S.allIds=[]}
 renderLive();drawTopo()}

(async()=>{try{await loadTopo();buildControls();$('f-id').value=nextId();syncYaml();drawTopo();$('f-src').addEventListener('change',drawTopo);$('f-dst').addEventListener('change',drawTopo)}
 catch(e){showError(e)}})();
</script></body></html>"""
