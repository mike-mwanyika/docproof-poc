"""Build a self-contained local dashboard from the Stage 1 and Stage 2 results.

  python scripts/build_dashboard.py        then open results/dashboard/index.html

Needs results/stage2_cases.json, results/stage2_findings.json (run scripts/run_stage2.py first) and the Stage 1
cache. Renders each distinct PDF page once as an image; the page overlays boxes using coordinates in PDF points.
Nothing leaves the machine and no server is needed.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RES = ROOT / "results"
OUT = RES / "dashboard"
SCALE = 1.4  # image resolution; boxes are drawn from points, so this only affects sharpness
ENGINE = "rapidocr"
PIPELINE_VERSION = "v2-text-layer-tables"  # keep in step with scripts/run_stage2.py


def stage1_rows() -> list[dict]:
    p = RES / "stage1_summary.md"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines()[2:]:
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 9:
            rows.append(dict(zip(["engine", "category", "files", "failed", "cer", "wer", "table", "trace", "sec"], c)))
    return rows


def render_file(path: Path, sha: str, rendered: dict) -> list:
    if sha not in rendered:
        pdf = pdfium.PdfDocument(str(path))
        pages = []
        for i in range(len(pdf)):
            img = f"pages/{sha[:12]}_p{i + 1}.png"
            if not (OUT / img).exists():
                pdf[i].render(scale=SCALE).to_pil().convert("RGB").save(OUT / img, optimize=True)
            w, h = pdf[i].get_size()
            pages.append({"w": round(w, 1), "h": round(h, 1), "img": img})
        rendered[sha] = pages
    return rendered[sha]


def elements_of(sha: str) -> list:
    cache = RES / "cache" / ENGINE / PIPELINE_VERSION / f"{sha}.json"
    els = []
    if cache.exists():
        for e in json.loads(cache.read_text(encoding="utf-8"))["elements"]:
            if e.get("bbox") and e.get("page"):
                label = e["element_type"] if e["element_type"] != "table_cell" else f"cell {e['table_ref'].split('.', 1)[1]}"
                els.append({"p": e["page"], "b": e["bbox"], "t": e["element_type"], "l": label, "x": (e["text"] or "")[:90]})
    return els


def main():
    stage = "3" if "--stage3" in sys.argv else "2"
    cases_p, find_p = RES / f"stage{stage}_cases.json", RES / f"stage{stage}_findings.json"
    if not cases_p.exists() or not find_p.exists():
        sys.exit(f"Run scripts/run_stage{stage}.py first.")
    cases = json.loads(cases_p.read_text(encoding="utf-8"))
    findings = json.loads(find_p.read_text(encoding="utf-8"))
    (OUT / "pages").mkdir(parents=True, exist_ok=True)

    files: dict[str, dict] = {}
    rendered: dict[str, list] = {}
    case_list = []
    for name, c in cases.items():
        for d in c["docs"]:
            key = f"{name}/{d['file']}"
            if key in files:
                continue
            sha = d["sha"]
            render_file(ROOT / d["path"], sha, rendered)
            els = elements_of(sha)
            files[key] = {"pages": rendered[sha], "elements": els, "path": d["path"]}
        case_list.append({"name": name, "expected": c["expected"], "score": c["score"], "docs": c["docs"],
                          "findings": findings[name]})

    # guideline documents, so AI findings can show the requirement they relied on
    from docproof.ingest import sha256_of
    for kd in json.loads((ROOT / "config" / "knowledge.json").read_text(encoding="utf-8"))["documents"]:
        kp = ROOT / kd["file"]
        sha = sha256_of(kp)
        files[f"knowledge/{kp.name}"] = {"pages": render_file(kp, sha, rendered), "elements": elements_of(sha), "path": kd["file"]}

    data = {"stage": stage, "generated": datetime.now().strftime("%d %b %Y %H:%M"), "engine": ENGINE, "cases": case_list,
            "files": files, "stage1": stage1_rows()}
    (OUT / "data.js").write_text("window.DATA = " + json.dumps(data, ensure_ascii=False, default=str) + ";", encoding="utf-8")
    (OUT / "index.html").write_text(HTML, encoding="utf-8")
    print(f"Dashboard: {OUT / 'index.html'}  ({len(case_list)} cases, {len(files)} documents, {sum(len(v) for v in rendered.values())} page images)")


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>docproof results</title>
<style>
:root{--bg:#f4f6f8;--surface:#fff;--ink:#17212b;--muted:#5b6773;--line:#d8dee4;--accent:#0e6b66;--accent-soft:#e1f0ee;
--pass:#2b7a3d;--pass-bg:#e2f2e5;--fail:#b3261e;--fail-bg:#fbe4e2;--nd:#8a5a00;--nd-bg:#fbefd2;--na:#5b6773;--na-bg:#eceff2;
--mono:ui-monospace,Menlo,Consolas,monospace;--sans:"Segoe UI",system-ui,-apple-system,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#10171d;--surface:#18212a;--ink:#e6ecf1;--muted:#9aa8b4;--line:#2b3844;--accent:#4fc2b8;--accent-soft:#163a39;
--pass:#7bcb8a;--pass-bg:#1b3322;--fail:#ff8a80;--fail-bg:#3d1f1d;--nd:#e8b44a;--nd-bg:#3a2f15;--na:#9aa8b4;--na-bg:#222d37}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans)}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:baseline;padding:14px 20px;background:var(--surface);border-bottom:1px solid var(--line)}
header h1{margin:0;font-size:18px}header small{color:var(--muted)}
nav{display:flex;gap:4px;margin-left:auto}nav button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:6px 14px;border-radius:6px;cursor:pointer}
nav button[aria-selected=true]{background:var(--accent);border-color:var(--accent);color:#fff}
.wrap{display:grid;grid-template-columns:250px minmax(0,1fr);gap:18px;padding:18px 20px;max-width:1500px;margin:0 auto}
aside{position:sticky;top:12px;align-self:start;display:grid;gap:6px}
aside button{text-align:left;font:inherit;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px;cursor:pointer;display:grid;gap:3px}
aside button[aria-current=true]{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
aside .n{font-weight:600;font-size:13.5px}aside .badges{display:flex;gap:4px;flex-wrap:wrap}
.chip{display:inline-block;font:600 11.5px var(--mono);padding:2px 8px;border-radius:999px;white-space:nowrap}
.pass{background:var(--pass-bg);color:var(--pass)}.fail{background:var(--fail-bg);color:var(--fail)}
.not_determined,.nd{background:var(--nd-bg);color:var(--nd)}.not_applicable,.na{background:var(--na-bg);color:var(--na)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}
h2{margin:0 0 4px;font-size:20px}h3{margin:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
.muted{color:var(--muted)}.stack{display:grid;gap:16px}
.exp{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin-top:6px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:7px 9px;border-bottom:1px solid var(--line)}
th{font:600 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
tr.click{cursor:pointer}tr.click:hover td,tr.sel td{background:var(--accent-soft)}tr:last-child td{border-bottom:0}
.tw{overflow-x:auto}.mono{font-family:var(--mono);font-size:12.5px}
.split{display:grid;grid-template-columns:minmax(300px,2fr) minmax(0,3fr);gap:16px;align-items:start}
.doc{border:1px solid var(--line);border-radius:8px;margin-bottom:10px;overflow:hidden}
.doc>header{padding:8px 10px;background:var(--bg);border:0;display:block}
.doc .flags{color:var(--nd);font-size:13px;margin-top:2px}
.warn{color:var(--nd)}
.viewer{position:sticky;top:12px}
.bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px;font-size:13.5px}
.bar button,.pg{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:3px 9px;border-radius:6px;cursor:pointer}
.pg[aria-current=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.page{position:relative;border:1px solid var(--line);background:#fff;line-height:0}
.page img{width:100%;height:auto;display:block}
.box{position:absolute;pointer-events:none;border:1.5px solid rgba(120,120,120,.55);background:rgba(120,120,120,.06)}
.box.el{pointer-events:auto}.box.t-table_cell{border-color:rgba(33,111,200,.6);background:rgba(33,111,200,.07)}
.box.t-heading{border-color:rgba(150,60,170,.7);background:rgba(150,60,170,.08)}.box.t-figure{border-color:rgba(220,110,0,.8);background:rgba(220,110,0,.1)}
.box.hl{border:2.5px solid #e0242b;background:rgba(224,36,43,.16);box-shadow:0 0 0 2px rgba(255,255,255,.7)}
.quote{margin-top:10px;padding:10px 12px;border-left:3px solid var(--accent);background:var(--accent-soft);font-size:14px;line-height:1.45}
.ev button{display:block;width:100%;text-align:left;font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 9px;margin-bottom:5px;cursor:pointer}
.ev button[aria-current=true]{border-color:var(--accent)}
label.t{display:flex;gap:6px;align-items:center;cursor:pointer}
.hint{font-size:13px;color:var(--muted)}
@media (max-width:1000px){.wrap{grid-template-columns:minmax(0,1fr)}aside{position:static;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}.split{grid-template-columns:minmax(0,1fr)}.viewer{position:static}}
</style></head><body>
<header><h1>docproof results</h1><small id="gen"></small>
<nav role="tablist"><button role="tab" id="tab-cases" aria-selected="true">Cases</button><button role="tab" id="tab-s1" aria-selected="false">Stage 1 benchmark</button></nav></header>
<div class="wrap" id="cases"><aside id="caselist" aria-label="Cases"></aside><main class="stack" id="detail"></main></div>
<div class="wrap" id="s1" hidden style="grid-template-columns:minmax(0,1fr)"><main class="stack" id="s1body"></main></div>
<script src="data.js"></script>
<script>
const D = window.DATA, S = {case:null, file:null, page:1, hl:[], els:false, sel:null};
const OUTCOME = {pass:"pass", fail:"FAIL", not_determined:"not determined", not_applicable:"n/a"};
function h(tag, attrs, ...kids){const e=document.createElement(tag);for(const[k,v]of Object.entries(attrs||{})){if(k==="class")e.className=v;else if(k.startsWith("on"))e[k]=v;else if(v!==false&&v!=null)e.setAttribute(k,v)}
 for(const c of kids.flat()){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)))}return e}
const chip=(o,deferred)=>h("span",{class:"chip "+o},OUTCOME[o]+(deferred?" (AI)":""));
const keyFor=(c,e)=>e.label==="guideline"?"knowledge/"+e.file:c.name+"/"+e.file;
const clsName=c=>c?c.replace(/^K\d_/,"").replace(/_/g," "):"unreadable";
document.getElementById("gen").textContent=`Results: Stage ${D.stage} · Stage 1 engine: ${D.engine} · built ${D.generated} · synthetic documents only`;

function counts(c){const f=c.findings.filter(x=>!x.deferred);return{fail:f.filter(x=>x.outcome==="fail").length,nd:f.filter(x=>x.outcome==="not_determined").length}}
function renderList(){const el=document.getElementById("caselist");el.replaceChildren(...D.cases.map(c=>{const k=counts(c);
 return h("button",{"aria-current":S.case===c.name,onclick:()=>selectCase(c.name)},h("span",{class:"n"},c.name.replace(/^case/,"Case ").replace(/_/g," ")),
 h("span",{class:"badges"},k.fail?h("span",{class:"chip fail"},k.fail+" fail"):null,k.nd?h("span",{class:"chip nd"},k.nd+" nd"):null,!k.fail&&!k.nd?h("span",{class:"chip pass"},"clean"):null))}))}

function selectCase(name){S.case=name;const c=D.cases.find(x=>x.name===name);renderList();
 const sc=c.score,detail=document.getElementById("detail");
 const exp=c.expected.length?c.expected.map(e=>{const k=sc.caught.includes(e.check)?["fail","caught"]:sc.escalated.includes(e.check)?["nd","escalated"]:sc.needs_ai.includes(e.check)?["na","needs AI"]:["fail","MISSED"];
  return h("span",{},h("span",{class:"chip "+k[0]},e.check+" "+k[1])," ",h("span",{class:"hint"},e.description))}):[h("span",{class:"hint"},"No defect planted. Every rule check should pass.")];
 detail.replaceChildren(
  h("div",{class:"card"},h("h2",{},c.name.replace(/_/g," ")),h("div",{class:"hint"},"Planted defects and what the system did with them"),h("div",{class:"exp"},...exp),
   sc.false_fails.length?h("div",{class:"exp"},h("span",{class:"chip fail"},"false fail"),h("span",{class:"hint"},sc.false_fails.join(", "))):null),
  h("div",{class:"card"},h("h3",{},"Checks (click one to see its evidence)"),h("div",{class:"tw"},checksTable(c))),
  h("div",{class:"split"},h("div",{id:"docs"},h("h3",{},"Documents and extracted fields"),...c.docs.map(d=>docCard(c,d))),
   h("div",{class:"card viewer",id:"viewer"})));
 const first=c.findings.find(f=>f.outcome==="fail"&&!f.deferred)||c.findings.find(f=>f.outcome==="not_determined"&&!f.deferred);
 if(first)showCheck(c,first);else openDoc(c,c.docs[0]);}

function checksTable(c){const rows=c.findings.map(f=>h("tr",{class:"click",id:"chk-"+f.check_id,onclick:()=>showCheck(c,f)},
  h("td",{class:"mono"},f.check_id),h("td",{},f.title),h("td",{},chip(f.outcome,f.deferred)),h("td",{class:"hint"},f.severity),h("td",{class:"hint"},f.confidence),h("td",{},f.description,f.reason?h("div",{class:"hint"},f.reason):null)));
 return h("table",{},h("thead",{},h("tr",{},...["Check","What it tests","Outcome","Severity","Confidence","Finding"].map(x=>h("th",{},x)))),h("tbody",{},...rows))}

function docCard(c,d){const fields=Object.entries(d.fields||{});
 return h("div",{class:"doc"},h("header",{},h("strong",{},d.file)," ",h("span",{class:"chip na"},clsName(d.cls))," ",h("span",{class:"hint"},d.pages.length>1?"pages "+d.pages[0]+"–"+d.pages[d.pages.length-1]:d.pages.length?"page "+d.pages[0]:""),
   d.flags.length?h("div",{class:"flags"},d.flags.join("; ")):null,h("div",{},h("button",{class:"pg",onclick:()=>openDoc(c,d)},"view document"))),
  fields.length?h("table",{},h("tbody",{},...fields.map(([n,r])=>h("tr",{class:r.page?"click":"",onclick:r.page?()=>openField(c,d,n,r):null},
    h("td",{class:"mono"},n),h("td",{},r.status==="found"?String(r.value):h("span",{class:"hint"},"("+r.status+")"),r.warnings&&r.warnings.length?h("div",{class:"warn hint"},"⚠ "+r.warnings.join("; ")):null),
    h("td",{class:"hint"},r.status==="found"?(r.grounded?"grounded":"NOT in source"):"")))) ):null)}

function viewerFor(c,key,page){S.file=key;S.page=page;draw(c)}
function openDoc(c,d){S.hl=[];S.sel=null;viewerFor(c,c.name+"/"+d.file,d.pages[0]||1)}
function openField(c,d,n,r){S.hl=[{file:d.file,page:r.page,bbox:r.bbox}];S.sel={label:n,quote:r.quote,warn:r.warnings};viewerFor(c,c.name+"/"+d.file,r.page)}
function showCheck(c,f){document.querySelectorAll("#checks tr.sel,tr.sel").forEach(t=>t.classList.remove("sel"));const row=document.getElementById("chk-"+f.check_id);if(row)row.classList.add("sel");
 const ev=(f.evidence||[]).filter(e=>e.file);S.evList=ev;S.hl=ev.filter(e=>e.bbox).map(e=>({file:e.file,page:e.page,bbox:e.bbox}));
 const e0=ev.find(e=>e.page)||ev[0];S.sel={finding:f,quote:e0&&e0.quote};S.evKey=e0?keyFor(c,e0):null;
 if(e0){viewerFor(c,keyFor(c,e0),e0.page||1)}else{S.file=null;draw(c)}}

function draw(c){const v=document.getElementById("viewer"),f=S.sel&&S.sel.finding;const info=S.file&&D.files[S.file];
 const kids=[];
 if(f){kids.push(h("h3",{},f.check_id+" · "+OUTCOME[f.outcome]),h("div",{},f.description),f.reason?h("div",{class:"hint"},f.reason):null,
   f.requirement_ref?h("div",{class:"hint"},"Requirement applied: "+f.requirement_ref):null,
   f.method&&f.method.model?h("div",{class:"hint"},`AI: ${f.method.model} · prompt ${f.method.prompt_version} · ${f.method.runs} runs · ${f.method.passages} passages`+(f.ai_runs?" · run verdicts: "+f.ai_runs.map(r=>r.model_verdict||r.verdict).join(" / "):"")):null);
  if(f.evidence&&f.evidence.length){kids.push(h("div",{class:"ev",style:"margin-top:8px"},...f.evidence.map(e=>h("button",{"aria-current":S.file===keyFor(c,e)&&S.page===e.page,onclick:()=>{S.hl=e.bbox?[{file:e.file,page:e.page,bbox:e.bbox}]:[];S.sel={...S.sel,quote:e.quote};viewerFor(c,keyFor(c,e),e.page||1)}},
    h("span",{class:"mono"},(e.label||"evidence")+" "),h("span",{class:"hint"},e.file+(e.page?" p"+e.page:"")),e.value!=null&&e.value!==undefined?h("span",{}," → "+String(e.value)):null,e.status?h("span",{class:"hint"}," ("+e.status+")"):null))))}}
 else if(S.sel&&S.sel.label){kids.push(h("h3",{},"Field · "+S.sel.label))}
 if(info){const pg=info.pages[S.page-1]||info.pages[0];
  kids.push(h("div",{class:"bar",style:"margin-top:10px"},h("strong",{},S.file.split("/")[1])," ",...info.pages.map((_,i)=>h("button",{class:"pg","aria-current":S.page===i+1,onclick:()=>{S.page=i+1;draw(c)}},"p"+(i+1))),
   h("label",{class:"t"},h("input",{type:"checkbox",checked:S.els,onchange:e=>{S.els=e.target.checked;draw(c)}}),"show everything Stage 1 read")));
  const box=h("div",{class:"page"},h("img",{src:pg.img,alt:"page "+S.page}));
  const add=(b,cls,title)=>{if(!b)return;const[x0,y0,x1,y1]=b;box.append(h("div",{class:"box "+cls,title:title||null,style:`left:${x0/pg.w*100}%;top:${y0/pg.h*100}%;width:${(x1-x0)/pg.w*100}%;height:${(y1-y0)/pg.h*100}%`}))};
  if(S.els)info.elements.filter(e=>e.p===S.page).forEach(e=>add(e.b,"el t-"+e.t,e.l+": "+e.x));
  S.hl.filter(x=>x.file+""===S.file.split("/")[1]&&x.page===S.page).forEach(x=>add(x.bbox,"hl"));
  kids.push(box);
  if(S.sel&&S.sel.quote)kids.push(h("div",{class:"quote"},h("div",{class:"hint"},"Source text the value came from"),S.sel.quote));
  if(S.sel&&S.sel.warn&&S.sel.warn.length)kids.push(h("div",{class:"hint warn",style:"margin-top:6px"},"⚠ "+S.sel.warn.join("; ")));
  const missing=S.hl.some(x=>x.file===S.file.split("/")[1]&&x.page!==S.page);
  if(!S.hl.length&&f&&f.evidence&&f.evidence.length)kids.push(h("div",{class:"hint",style:"margin-top:6px"},"This evidence has no position box (for example a missing document); nothing to highlight."));
 }else if(f){kids.push(h("div",{class:"hint",style:"margin-top:10px"},"No document is attached to this finding."))}
 v.replaceChildren(...kids)}

function renderS1(){const rows=D.stage1,b=document.getElementById("s1body");
 const num=x=>parseFloat(x);const cellCls=(k,x)=>{const v=num(x);if(isNaN(v))return"";const bad=k==="cer"||k==="wer"?v:1-v;return bad>=0.3?"fail":bad>=0.08?"nd":"pass"};
 b.replaceChildren(h("div",{class:"card"},h("h2",{},"Stage 1: reading the documents"),h("div",{class:"hint"},"Error rates (CER, WER): lower is better. Table accuracy and traceability: higher is better. Source: results/stage1_summary.md. Synthetic documents only."),
  h("div",{class:"tw",style:"margin-top:10px"},h("table",{},h("thead",{},h("tr",{},...["Engine","Category","Files","Failed","CER","WER","Table acc","Traceability","Sec/file"].map(x=>h("th",{},x)))),
   h("tbody",{},...rows.map(r=>h("tr",{},h("td",{},r.engine),h("td",{},r.category),h("td",{},r.files),h("td",{},r.failed),
    h("td",{},h("span",{class:"chip "+cellCls("cer",r.cer)},r.cer)),h("td",{},h("span",{class:"chip "+cellCls("wer",r.wer)},r.wer)),
    h("td",{},r.table==="n/a"?"n/a":h("span",{class:"chip "+cellCls("table",r.table)},r.table)),h("td",{},h("span",{class:"chip "+cellCls("trace",r.trace)},r.trace)),h("td",{},r.sec))))))))};
const tabs={cases:document.getElementById("tab-cases"),s1:document.getElementById("tab-s1")};
function tab(n){for(const[k,b]of Object.entries(tabs)){b.setAttribute("aria-selected",k===n);document.getElementById(k).hidden=k!==n}}
tabs.cases.onclick=()=>tab("cases");tabs.s1.onclick=()=>tab("s1");
renderList();renderS1();selectCase((D.cases.find(c=>counts(c).fail)||D.cases[0]).name);
</script></body></html>
"""

if __name__ == "__main__":
    main()
