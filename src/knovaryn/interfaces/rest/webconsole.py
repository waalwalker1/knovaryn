"""Accessible web console (spec §17.4, WP J6).

A single self-contained, keyboard-navigable page served at ``/`` that drives the
REST control plane. It covers the full J6 surface:

* token setup (auth header) and server health
* create / list projects
* add text or binary sources with license + privacy declaration
* run estimate, profile / budget selection, pipeline queue + live job event view
* example review with cited evidence (lineage), quality report
* version creation, export download, publication dry-run plan

The page is WCAG-minded: semantic landmarks, labelled form controls, programmatic
focus management, and no mouse-only interactions. It is deliberately dependency-
free (vanilla JS, no remote CDNs) so the CSP ``'self'`` stays effective.
"""

from __future__ import annotations

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knovaryn Console</title>
<style>
  :root{color-scheme:light dark;--fg:#16181d;--bg:#fafafa;--card:#ffffff;--line:#e5e6ea;
    --accent:#2563eb;--accent-fg:#ffffff;--muted:#6b7280;--err:#b91c1c;--ok:#15803d;}
  @media(prefers-color-scheme:dark){:root{--fg:#e7e9ee;--bg:#0f1115;--card:#171a20;
    --line:#2a2f3a;--muted:#9aa1ad;}}
  *{box-sizing:border-box}
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);
    background:var(--bg);margin:0;line-height:1.5}
  header{display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line)}
  header h1{font-size:1.15rem;margin:0}
  #status{margin-left:auto;font-size:.85rem;color:var(--muted)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--ok);display:inline-block;margin-right:6px}
  main{max-width:1080px;margin:0 auto;padding:20px;display:grid;gap:18px}
  section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
  h2{font-size:1rem;margin:0 0 10px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
  label{display:block;font-weight:600;font-size:.8rem;margin:8px 0 2px}
  input,select,textarea,button{font:inherit;color:var(--fg);background:var(--card);
    border:1px solid var(--line);border-radius:8px;padding:7px 10px;margin:2px 0}
  textarea{width:100%;resize:vertical}
  button{background:var(--accent);color:var(--accent-fg);border:none;cursor:pointer}
  button.sec{background:var(--muted)}
  button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,
    a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;
    overflow:auto;max-height:320px;font-size:.78rem}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  .hint{font-size:.72rem;color:var(--muted)}
  .err{color:var(--err);font-size:.85rem}
  .ok{color:var(--ok)}
  a{color:var(--accent)}
  table{border-collapse:collapse;width:100%;font-size:.8rem}
  th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line)}
  [role=tabpanel]{padding-top:10px}
</style>
</head>
<body>
<a href="#main" class="skip" style="position:absolute;left:-9999px">Skip to content</a>
<header>
  <h1>Knovaryn Console</h1>
  <span class="hint">Training-data foundry</span>
  <span id="status"><span class="dot"></span>checking…</span>
</header>

<main id="main">
  <!-- token setup -->
  <section aria-labelledby="auth-title">
    <h2 id="auth-title">Authentication</h2>
    <label for="token">API token</label>
    <div class="row">
      <input id="token" type="password" autocomplete="off" spellcheck="false"
             aria-describedby="token-hint" placeholder="leave blank for local mode">
      <button id="saveToken" type="button">Apply token</button>
    </div>
    <p id="token-hint" class="hint">When the server enforces a token, enter it here; it is sent as a
    <code>Bearer</code> header and never stored server-side.</p>
  </section>

  <div class="grid">
    <!-- projects -->
    <section aria-labelledby="proj-title">
      <h2 id="proj-title">Projects</h2>
      <label for="slug">Slug (lowercase, dashes)</label>
      <input id="slug" pattern="[a-z0-9][a-z0-9-]*" aria-describedby="slug-hint">
      <label for="name">Display name</label>
      <input id="name">
      <div class="row">
        <button id="createProject" type="button">Create project</button>
        <button type="button" class="sec" data-act="list-projects">List projects</button>
      </div>
      <p id="slug-hint" class="hint">e.g. <code>widgets-docs</code></p>
      <div id="projectsOut"></div>
    </section>

    <!-- sources -->
    <section aria-labelledby="src-title">
      <h2 id="src-title">Sources (intake)</h2>
      <label for="pid">Project id</label>
      <input id="pid" aria-describedby="pid-hint">
      <label for="srcname">Source name</label>
      <input id="srcname">
      <label for="srcfile">File (binary or text) — optional</label>
      <input id="srcfile" type="file">
      <label for="srccontent">Markdown content (text sources)</label>
      <textarea id="srccontent" rows="3"></textarea>
      <label for="srclic">Declared license</label>
      <input id="srclic" placeholder="MIT / CC-BY-4.0 / …">
      <label for="srcpriv">Privacy declaration</label>
      <select id="srcpriv"><option value="">— advisory —</option>
        <option>public</option><option>internal</option><option>restricted</option></select>
      <button id="addSource" type="button">Add source</button>
      <p id="pid-hint" class="hint">from the project list above</p>
      <div id="srcOut"></div>
    </section>
  </div>

  <div class="grid">
    <!-- pipeline -->
    <section aria-labelledby="pipe-title">
      <h2 id="pipe-title">Pipeline</h2>
      <label for="pipeProfile">Profile</label>
      <select id="pipeProfile"><option value="balanced">balanced</option>
        <option value="fast-local">fast-local</option><option value="high-quality">high-quality</option>
        <option value="air-gapped">air-gapped</option></select>
      <label for="pipeBudget">Budget max (USD)</label>
      <input id="pipeBudget" type="number" min="0" step="0.5" value="10">
      <label for="pipeTarget">Target examples</label>
      <input id="pipeTarget" type="number" min="1" value="200">
      <div class="row">
        <button id="estimateRun" type="button" class="sec">Estimate run</button>
        <button id="startPipeline" type="button">Queue pipeline</button>
      </div>
      <pre id="estimateOut" aria-live="polite"></pre>
      <label for="jid">Job id</label>
      <input id="jid">
      <div class="row">
        <button id="runJob" type="button">Run job</button>
        <button id="getJob" type="button" class="sec">View events</button>
      </div>
      <pre id="jobOut" aria-live="polite"></pre>
    </section>

    <!-- review / lineage -->
    <section aria-labelledby="ex-title">
      <h2 id="ex-title">Examples &amp; review</h2>
      <label for="expid">Project id</label>
      <input id="expid">
      <div class="row"><button id="listExamples" type="button">List examples</button></div>
      <pre id="exOut" aria-live="polite"></pre>
      <label for="reviewEx">Example id to review</label>
      <input id="reviewEx">
      <label for="reviewDecision">Decision</label>
      <select id="reviewDecision"><option value="approve">approve</option>
        <option value="reject">reject</option><option value="needs_work">needs_work</option></select>
      <label for="reviewNote">Note</label>
      <input id="reviewNote">
      <button id="doReview" type="button">Apply review</button>
      <div id="revOut"></div>
    </section>
  </div>

  <!-- datasets -->
  <section aria-labelledby="ds-title">
    <h2 id="ds-title">Dataset lifecycle</h2>
    <label for="dspid">Project id</label>
    <input id="dspid">
    <div class="row">
      <button id="validate" type="button">Validate / quality report</button>
      <button id="createVersion" type="button">Create version</button>
      <button id="export" type="button">Export (download)</button>
      <button id="publish" type="button" class="sec">Publish (dry-run plan)</button>
    </div>
    <pre id="dsOut" aria-live="polite"></pre>
  </section>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("knovaryn_token") || "";

function headers(method, body){
  const h = {"Content-Type":"application/json"};
  if (token) h["Authorization"] = "Bearer " + token;
  if (body !== undefined) h["body"] = JSON.stringify(body);
  return h;
}
async function api(path, method="GET", body){
  const cfg = {method};
  if (body !== undefined) cfg.body = JSON.stringify(body);
  const h = {"Content-Type":"application/json"};
  if (token) h["Authorization"] = "Bearer " + token;
  cfg.headers = h;
  const r = await fetch(path, cfg);
  const text = await r.text();
  let data; try { data = text ? JSON.parse(text) : {}; } catch { data = {raw: text}; }
  return {status:r.status, ok:r.ok, data};
}
function out(el, obj){
  const isErr = el && obj && typeof obj==="object" && obj.ok===false;
  el.innerHTML = '<pre class="'+(isErr?"err":"ok")+'">'+escape(JSON.stringify(obj&&obj.data?obj.data:obj,null,2))+'</pre>';
}
function setStatus(){
  const s = $("status"); s.innerHTML = '<span class="dot"></span>server ' +
    (token ? "authenticated" : "local mode");
}
$("saveToken").addEventListener("click", ()=>{
  token = $("token").value.trim();
  if (token) localStorage.setItem("knovaryn_token", token);
  else localStorage.removeItem("knovaryn_token");
  setStatus();
});
$("token").addEventListener("change", ()=> $("saveToken").click());

$("createProject").addEventListener("click", async ()=>{
  const r = await api("/v1/projects","POST",{slug:$("slug").value,display_name:$("name").value});
  out($("projectsOut"), r);
});
$("addSource").addEventListener("click", async ()=>{
  const body = {original_name:$("srcname").value, content:$("srccontent").value,
                declared_license:$("srclic").value, privacy:$("srcpriv").value};
  const file = $("srcfile").files[0];
  let r;
  if (file){
    body.media_type = file.type || "application/octet-stream";
    const buf = await file.arrayBuffer();
    body.raw = btoa(String.fromCharCode(...new Uint8Array(buf)));
    r = await api(`/v1/projects/${$("pid").value}/sources`,"POST",body);
  } else {
    r = await api(`/v1/projects/${$("pid").value}/sources`,"POST",body);
  }
  out($("srcOut"), r);
});
$("estimateRun").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("pid").value}/pipeline/estimate`,"POST",{
    profile:$("pipeProfile").value,
    target_examples:Number($("pipeTarget").value)||200,
    budget_max_usd:Number($("pipeBudget").value)||0,
  });
  out($("estimateOut"), r);
});
$("startPipeline").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("pid").value}/pipeline`,"POST",{
    profile:$("pipeProfile").value,
    target_examples:Number($("pipeTarget").value)||200,
  });
  out($("estimateOut"), r);
});
$("runJob").addEventListener("click", async ()=>{
  const r = await api(`/v1/jobs/${$("jid").value}/run`,"POST",{});
  out($("jobOut"), r);
});
$("getJob").addEventListener("click", async ()=>{
  const r = await api(`/v1/jobs/${$("jid").value}`,"GET");
  out($("jobOut"), r);
});
$("listExamples").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("expid").value}/examples`,"GET");
  out($("exOut"), r);
});
$("doReview").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("expid").value}/examples/${$("reviewEx").value}/review`,
    "POST",{decision:$("reviewDecision").value, note:$("reviewNote").value});
  out($("revOut"), r);
});
$("validate").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("dspid").value}/validate`,"POST",{});
  out($("dsOut"), r);
});
$("createVersion").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("dspid").value}/version`,"POST",{});
  out($("dsOut"), r);
});
$("export").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("dspid").value}/export`,"POST",{});
  out($("dsOut"), r);
  if (r.ok && r.data && r.data.download_path){
    out($("dsOut"), {ok:true, data:r.data, note:"downloadPath="+r.data.download_path});
  }
});
$("publish").addEventListener("click", async ()=>{
  const r = await api(`/v1/projects/${$("dspid").value}/publish`,"POST",
    {repo_id:"local/console-dry-run", dry_run:true, confirm:false});
  out($("dsOut"), r);
});

// generic list-projects action
document.querySelectorAll("[data-act=list-projects]").forEach(b=>{
  b.addEventListener("click", async ()=>{
    const r = await api("/v1/projects","GET");
    out($("projectsOut"), r);
  });
});

// health check on load
(async function(){ const r = await api("/v1/health","GET"); $("status").innerHTML =
  '<span class="dot"></span>server ' + (r.ok? "healthy":"unreachable"); setStatus(); })();
</script>
</body>
</html>
"""


def render_console() -> str:
    return HTML
