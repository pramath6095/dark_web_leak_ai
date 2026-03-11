"""
dark web leak monitor — web dashboard
flask app for running queries, viewing reports, and browsing history.
"""
import os
import json
import time
import threading
from datetime import datetime

try:
    from flask import Flask, request, jsonify, Response, send_from_directory
except ImportError:
    raise ImportError("Flask required: pip install flask")

app = Flask(__name__)

# job tracking
_jobs = {}
_job_lock = threading.Lock()


def _check_abort(job_id: str) -> bool:
    """check if a job has been flagged for abort"""
    with _job_lock:
        return _jobs.get(job_id, {}).get("abort", False)


def _run_pipeline(job_id: str, query: str, config: dict):
    """run the main pipeline in a background thread."""
    import io
    import sys
    from contextlib import redirect_stdout

    with _job_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started"] = time.time()

    output_buffer = io.StringIO()

    try:
        from search import search_dark_web, save_results, get_urls_from_results
        from scrape import scrape_all, save_scraped_data
        from ioc_extractor import extract_iocs_from_scraped, extract_contacts_from_scraped, format_iocs_summary, format_contacts_summary

        use_ai = config.get("use_ai", True)
        ai_provider = config.get("ai_provider", "gemini")
        num_engines = config.get("num_engines", 16)
        scrape_limit = config.get("scrape_limit", 10)
        threads = config.get("threads", 3)
        depth = config.get("depth", 1)
        max_pages = config.get("max_pages", 1)

        # set the AI provider for this job
        if use_ai:
            from ai_engine import set_provider, set_ollama_model
            set_provider(ai_provider)
            if ai_provider == "ollama":
                set_ollama_model(config.get("ollama_model", ""))

        if _check_abort(job_id): raise InterruptedError("Aborted")

        with _job_lock:
            _jobs[job_id]["progress"] = "searching"

        search_queries = [query]
        if use_ai:
            from ai_engine import refine_query
            keywords = refine_query(query)
            search_queries = keywords + [query]

        all_results = []
        seen_urls = set()
        for sq in search_queries:
            if _check_abort(job_id): raise InterruptedError("Aborted")
            batch = search_dark_web(sq, max_workers=threads, num_engines=num_engines, check_abort=lambda: _check_abort(job_id))
            for item in batch:
                url = item["url"] if isinstance(item, dict) else item
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(item)

        save_results(all_results)

        if _check_abort(job_id): raise InterruptedError("Aborted")

        with _job_lock:
            _jobs[job_id]["progress"] = "filtering"

        if use_ai and len(all_results) > scrape_limit:
            from ai_engine import filter_results
            all_results = filter_results(query, all_results, limit=scrape_limit)

        urls = [r["url"] if isinstance(r, dict) else r for r in all_results]
        urls_to_scrape = urls[:scrape_limit]

        if _check_abort(job_id): raise InterruptedError("Aborted")

        with _job_lock:
            _jobs[job_id]["progress"] = "scraping"

        scraped_data, html_cache = scrape_all(urls_to_scrape, max_workers=threads, depth=depth, max_pages=max_pages, check_abort=lambda: _check_abort(job_id))
        save_scraped_data(scraped_data)

        if _check_abort(job_id): raise InterruptedError("Aborted")

        all_iocs = extract_iocs_from_scraped(scraped_data)
        all_contacts = extract_contacts_from_scraped(scraped_data)

        if all_iocs:
            ioc_text = format_iocs_summary(all_iocs)
            os.makedirs("output", exist_ok=True)
            with open("output/iocs.txt", "w", encoding="utf-8") as f:
                f.write(ioc_text)

        if all_contacts:
            contacts_text = format_contacts_summary(all_contacts)
            os.makedirs("output", exist_ok=True)
            with open("output/contacts.txt", "w", encoding="utf-8") as f:
                f.write(contacts_text)

        summary = ""
        if use_ai:
            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "classifying"

            from ai_engine import classify_threats, generate_summary
            classifications = classify_threats(query, scraped_data)

            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "summarizing"

            summary = generate_summary(query, scraped_data, classifications, regex_iocs=all_iocs, actor_contacts=all_contacts)

            os.makedirs("output", exist_ok=True)
            with open("output/summary.txt", "w", encoding="utf-8") as f:
                f.write(summary)

        with _job_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["finished"] = time.time()
            _jobs[job_id]["results_count"] = len(all_results)
            _jobs[job_id]["scraped_count"] = sum(1 for v in scraped_data.values() if not v.startswith("[ERROR"))
            _jobs[job_id]["summary_preview"] = summary if summary else ""

    except InterruptedError:
        with _job_lock:
            _jobs[job_id]["status"] = "aborted"
            _jobs[job_id]["finished"] = time.time()
        print(f"  [!] Job {job_id} aborted by user.")

    except Exception as e:
        with _job_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)[:200]


# ============================================================
# HTML TEMPLATE
# ============================================================

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dark Web Leak Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --bg: #080b12;
    --surface: #0e1420;
    --surface2: #131929;
    --border: #1e2d45;
    --accent: #00c8ff;
    --accent2: #7c3aed;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text: #e2e8f0;
    --muted: #64748b;
    --mono: 'JetBrains Mono', monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

  /* HEADER */
  .header {
    background: linear-gradient(135deg, #0a0f1e 0%, #0d1528 100%);
    padding: 20px 32px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px;
  }
  .header-icon { font-size: 28px; }
  .header h1 { font-size: 20px; font-weight: 700; background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .header p { color: var(--muted); font-size: 12px; margin-top: 2px; }

  /* LAYOUT */
  .container { max-width: 1100px; margin: 0 auto; padding: 28px 24px; }

  /* CARDS */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 24px;
    margin-bottom: 24px;
  }
  .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
  .card-header h2 { font-size: 15px; font-weight: 600; color: var(--text); }
  .card-icon { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 15px; }
  .card-icon.blue { background: rgba(0,200,255,0.12); }
  .card-icon.purple { background: rgba(124,58,237,0.12); }
  .card-icon.green { background: rgba(16,185,129,0.12); }

  /* FORM */
  label { display: block; color: var(--muted); font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; margin-top: 16px; }
  label:first-child { margin-top: 0; }
  input[type=text], input[type=number], select {
    width: 100%; padding: 10px 14px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text); font-size: 14px; font-family: inherit;
    transition: border-color 0.2s;
  }
  input:focus, select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,200,255,0.08); }
  .row { display: flex; gap: 14px; }
  .row > div { flex: 1; }
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    padding: 11px 22px; border-radius: 8px; font-size: 14px; font-weight: 600;
    cursor: pointer; border: none; transition: all 0.2s; font-family: inherit;
  }
  .btn-primary {
    background: linear-gradient(135deg, var(--accent), #0080ff);
    color: #000; width: 100%; margin-top: 20px;
  }
  .btn-primary:hover { filter: brightness(1.1); transform: translateY(-1px); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-sm {
    padding: 6px 14px; font-size: 12px; border-radius: 6px;
    background: rgba(0,200,255,0.1); color: var(--accent); border: 1px solid rgba(0,200,255,0.2);
  }
  .btn-sm:hover { background: rgba(0,200,255,0.18); }
  .btn-abort {
    background: linear-gradient(135deg, var(--danger), #b91c1c);
    color: #fff; width: 100%; margin-top: 20px;
  }
  .btn-abort:hover { filter: brightness(1.15); transform: translateY(-1px); }

  /* STATUS BADGE */
  .badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
  .badge-queued  { background: rgba(100,116,139,0.15); color: var(--muted); }
  .badge-running { background: rgba(245,158,11,0.12); color: var(--warning); }
  .badge-done    { background: rgba(16,185,129,0.12); color: var(--success); }
  .badge-error   { background: rgba(239,68,68,0.12); color: var(--danger); }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .dot.pulse { animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }

  /* JOB STATUS */
  #job-status { display: none; }
  .job-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .job-stat { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 16px; }
  .job-stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .job-stat .value { color: var(--text); font-size: 18px; font-weight: 700; margin-top: 2px; }
  .progress-step { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; }
  .progress-step.active { color: var(--accent); }
  .summary-preview { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; font-size: 13px; line-height: 1.7; color: #cbd5e1; white-space: normal; max-height: 350px; overflow-y: auto; overflow-x: auto; margin-top: 12px; }

  /* FILE CARDS */
  .files-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
  .file-card {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 12px;
    padding: 18px; transition: border-color 0.2s, box-shadow 0.2s;
  }
  .file-card:hover { border-color: rgba(0,200,255,0.3); box-shadow: 0 0 20px rgba(0,200,255,0.05); }
  .file-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .file-card-icon { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }
  .file-card-icon.summary  { background: rgba(124,58,237,0.15); }
  .file-card-icon.iocs     { background: rgba(239,68,68,0.12); }
  .file-card-icon.contacts { background: rgba(16,185,129,0.12); }
  .file-card-icon.default  { background: rgba(0,200,255,0.12); }
  .file-card-name { font-size: 14px; font-weight: 600; color: var(--text); }
  .file-card-size { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .file-card-actions { display: flex; gap: 8px; }

  /* VIEWER MODAL */
  .modal-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75);
    backdrop-filter: blur(4px); z-index: 100; align-items: center; justify-content: center; padding: 24px;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
    width: 100%; max-width: 1000px; max-height: 90vh; display: flex; flex-direction: column;
    box-shadow: 0 24px 80px rgba(0,0,0,0.5);
  }
  .modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 24px; border-bottom: 1px solid var(--border);
  }
  .modal-title { display: flex; align-items: center; gap: 12px; }
  .modal-title h3 { font-size: 15px; font-weight: 600; }
  .modal-close {
    width: 32px; height: 32px; border-radius: 8px; border: none;
    background: var(--surface2); color: var(--muted); font-size: 18px;
    cursor: pointer; display: flex; align-items: center; justify-content: center;
    transition: background 0.2s, color 0.2s;
  }
  .modal-close:hover { background: rgba(239,68,68,0.15); color: var(--danger); }
  .modal-body { padding: 24px; overflow-y: auto; flex: 1; }

  /* CONTENT RENDERERS */
  .content-section { margin-bottom: 20px; }
  .content-section:last-child { margin-bottom: 0; }
  .section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
  .section-title::after { content: ''; flex: 1; height: 1px; background: var(--border); }
  .ioc-grid { display: flex; flex-wrap: wrap; gap: 8px; }
  .ioc-tag {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 10px; font-size: 12px; font-family: var(--mono);
  }
  .ioc-tag .type-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .ioc-tag.ip    { border-color: rgba(239,68,68,0.3); }   .ioc-tag.ip    .type-dot { background: var(--danger); }
  .ioc-tag.email { border-color: rgba(0,200,255,0.3); }   .ioc-tag.email .type-dot { background: var(--accent); }
  .ioc-tag.btc   { border-color: rgba(245,158,11,0.3); }  .ioc-tag.btc   .type-dot { background: var(--warning); }
  .ioc-tag.url   { border-color: rgba(124,58,237,0.3); }  .ioc-tag.url   .type-dot { background: var(--accent2); }
  .ioc-tag.onion { border-color: rgba(124,58,237,0.3); }  .ioc-tag.onion .type-dot { background: #a855f7; }
  .ioc-tag.other { border-color: var(--border); }         .ioc-tag.other .type-dot { background: var(--muted); }
  .contact-item { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; font-size: 13px; font-family: var(--mono); color: #94a3b8; }
  .plain-text { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; font-size: 13px; line-height: 1.75; color: #cbd5e1; white-space: pre-wrap; font-family: var(--mono); }
  .empty-state { text-align: center; padding: 40px; color: var(--muted); font-size: 14px; }
  .spinner { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; margin: 0 auto 12px; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* MARKDOWN STYLES */
  .markdown-body { font-size: 14px; line-height: 1.6; color: #cbd5e1; font-family: 'Inter', sans-serif; max-height: 60vh; overflow-y: auto; padding-right: 12px; }
  .markdown-body::-webkit-scrollbar { width: 8px; height: 8px; }
  .markdown-body::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); border-radius: 4px; }
  .markdown-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 4px; }
  .markdown-body::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }
  .markdown-body h1, .markdown-body h2, .markdown-body h3, .markdown-body h4 { color: white; margin-top: 24px; margin-bottom: 12px; font-weight: 600; }
  .markdown-body h1 { font-size: 22px; margin-top: 10px; }
  .markdown-body h2 { font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  .markdown-body h3 { font-size: 16px; }
  .markdown-body p, .markdown-body ul, .markdown-body ol { margin-bottom: 16px; }
  .markdown-body ul, .markdown-body ol { padding-left: 24px; }
  .markdown-body li { margin-bottom: 4px; }
  .markdown-body code { background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; font-family: var(--mono); font-size: 12.5px; }
  .markdown-body pre { background: rgba(0,0,0,0.5); padding: 16px; border-radius: 8px; overflow-x: auto; margin-bottom: 16px; border: 1px solid var(--border); }
  .markdown-body pre code { background: none; padding: 0; border: none; }
  .markdown-body table { width: 100%; border-collapse: collapse; margin-bottom: 16px; display: block; overflow-x: auto; }
  .markdown-body th, .markdown-body td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; white-space: normal; word-break: break-word; }
  .markdown-body th { background: rgba(255,255,255,0.05); color: white; font-weight: 600; }
  .markdown-body tr:nth-child(even) { background: rgba(255,255,255,0.02); }
  .markdown-body hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
  .markdown-body a { color: var(--accent); text-decoration: none; }
  .markdown-body a:hover { text-decoration: underline; }
  .markdown-body blockquote { border-left: 4px solid var(--accent); padding-left: 16px; color: var(--muted); margin-bottom: 16px; }
</style>
</head>
<body>
<div class="header">
  <span class="header-icon">🔍</span>
  <div>
    <h1>Dark Web Leak Monitor</h1>
    <p>AI-Powered Threat Intelligence Pipeline</p>
  </div>
</div>
<div class="container">

  <!-- RUN QUERY -->
  <div class="card">
    <div class="card-header">
      <div class="card-icon blue">🚀</div>
      <h2>Run Query</h2>
    </div>
    <form id="query-form">
      <label>Search Query</label>
      <input type="text" id="query" placeholder="e.g. company data breach, leaked credentials…" required>
      <div class="row">
        <div><label>Engines</label><input type="number" id="engines" value="16" min="1" max="16"></div>
        <div><label>Scrape Limit</label><input type="number" id="limit" value="10" min="1" max="50"></div>
        <div><label>Threads</label><input type="number" id="threads" value="3" min="1" max="10"></div>
      </div>
      <div class="row">
        <div><label>Depth</label><select id="depth"><option value="1">1 — landing page</option><option value="2">2 — follow sublinks</option></select></div>
        <div><label>Pages / URL</label><input type="number" id="pages" value="1" min="1" max="10"></div>
        <div><label>AI Pipeline</label><select id="ai"><option value="1">Enabled</option><option value="0">Disabled</option></select></div>
      </div>
      <div class="row">
        <div>
          <label>AI Provider</label>
          <select id="provider" onchange="onProviderChange()">
            <option value="gemini">Gemini (default)</option>
            <option value="ollama">Ollama (Local)</option>
            <option value="anthropic">Anthropic</option>
            <option value="deepseek">DeepSeek</option>
            <option value="groq">Groq</option>
            <option value="mistral">Mistral</option>
          </select>
        </div>
        <div id="ollama-model-wrapper" style="display:none">
          <label>Ollama Model</label>
          <select id="ollama-model">
            <option value="">Loading models…</option>
          </select>
        </div>
        <div></div>
      </div>
      <button type="submit" id="run-btn" class="btn btn-primary">▶ Run Pipeline</button>
    </form>
  </div>

  <!-- JOB STATUS -->
  <div class="card" id="job-status">
    <div class="card-header">
      <div class="card-icon blue">⚡</div>
      <h2>Job Status</h2>
    </div>
    <div id="job-info"></div>
  </div>

  <!-- REPORTS -->
  <div class="card">
    <div class="card-header">
      <div class="card-icon purple">📂</div>
      <h2>Output Reports</h2>
    </div>
    <div id="file-list"><div class="empty-state">No reports yet. Run a pipeline to generate reports.</div></div>
  </div>

</div>

<!-- VIEWER MODAL -->
<div class="modal-overlay" id="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <div class="modal-title">
        <span id="modal-icon" style="font-size:20px"></span>
        <h3 id="modal-title">Report</h3>
      </div>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body" id="modal-body">
      <div class="empty-state"><div class="spinner"></div>Loading…</div>
    </div>
  </div>
</div>

<script>
// ── Pipeline form ─────────────────────────────────────────
const form = document.getElementById('query-form');
const statusDiv = document.getElementById('job-status');
const jobInfo = document.getElementById('job-info');
const runBtn = document.getElementById('run-btn');
let pollInterval = null;
let currentJobId = null;

const STEPS = ['searching','filtering','scraping','classifying','summarizing'];

function setButtonRun() {
  runBtn.textContent = '▶ Run Pipeline';
  runBtn.className = 'btn btn-primary';
  runBtn.disabled = false;
  runBtn.onclick = null;
  runBtn.type = 'submit';
}

function setButtonAbort() {
  runBtn.textContent = '✕ Abort';
  runBtn.className = 'btn btn-abort';
  runBtn.disabled = false;
  runBtn.type = 'button';
  runBtn.onclick = abortJob;
}

async function abortJob() {
  if (!currentJobId) return;
  runBtn.disabled = true;
  runBtn.textContent = '⏳ Aborting…';
  await fetch('/abort/' + currentJobId, { method: 'POST' });
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  runBtn.disabled = true;
  const body = {
    query:        document.getElementById('query').value,
    num_engines:  parseInt(document.getElementById('engines').value),
    scrape_limit: parseInt(document.getElementById('limit').value),
    threads:      parseInt(document.getElementById('threads').value),
    depth:        parseInt(document.getElementById('depth').value),
    max_pages:    parseInt(document.getElementById('pages').value),
    use_ai:       document.getElementById('ai').value === '1',
    ai_provider:  document.getElementById('provider').value,
    ollama_model: document.getElementById('ollama-model').value,
  };
  const res  = await fetch('/run', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  const data = await res.json();
  currentJobId = data.job_id;
  statusDiv.style.display = 'block';
  renderJobRunning('queued', null);
  setButtonAbort();
  pollInterval = setInterval(() => pollJob(data.job_id), 2000);
});

async function pollJob(jobId) {
  const s = await fetch('/status/' + jobId).then(r => r.json());
  if (s.status === 'running' || s.status === 'queued') {
    renderJobRunning(s.status, s.progress);
  } else if (s.status === 'done') {
    renderJobDone(s);
    clearInterval(pollInterval);
    currentJobId = null;
    setButtonRun();
    loadFiles();
  } else if (s.status === 'aborted') {
    renderJobAborted();
    clearInterval(pollInterval);
    currentJobId = null;
    setButtonRun();
    loadFiles();
  } else if (s.status === 'error') {
    renderJobError(s.error);
    clearInterval(pollInterval);
    currentJobId = null;
    setButtonRun();
  }
}

function renderJobRunning(status, progress) {
  const stepHtml = STEPS.map(s =>
    `<span class="progress-step ${progress === s ? 'active' : ''}">
      ${progress === s ? '⟳' : (STEPS.indexOf(s) < STEPS.indexOf(progress) ? '✓' : '○')} ${s}
    </span>`
  ).join('<span style="color:var(--border);margin:0 4px">›</span>');
  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <span class="badge badge-running"><span class="dot pulse"></span>${status}</span>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;font-size:12px;">${stepHtml}</div>`;
}

function renderJobDone(s) {
  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <span class="badge badge-done"><span class="dot"></span>done</span>
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:${s.summary_preview ? '14px' : '0'}">
      <div class="job-stat"><div class="label">URLs Found</div><div class="value">${s.results_count || 0}</div></div>
      <div class="job-stat"><div class="label">Pages Scraped</div><div class="value">${s.scraped_count || 0}</div></div>
    </div>
    ${s.summary_preview ? `<div class="summary-preview markdown-body">${typeof marked !== 'undefined' ? marked.parse(s.summary_preview) : escHtml(s.summary_preview)}</div>` : ''}`;
}

function renderJobAborted() {
  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
      <span class="badge badge-error"><span class="dot"></span>aborted</span>
    </div>
    <div class="plain-text" style="color:var(--warning)">Pipeline was aborted by user. Partial results may be available in Output Reports.</div>`;
}

function renderJobError(err) {
  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
      <span class="badge badge-error"><span class="dot"></span>error</span>
    </div>
    <div class="plain-text" style="color:var(--danger)">${escHtml(err)}</div>`;
}

// ── File listing ──────────────────────────────────────────
async function loadFiles() {
  const res   = await fetch('/results');
  const files = await res.json();
  const el    = document.getElementById('file-list');
  if (!files.length) {
    el.innerHTML = '<div class="empty-state">No reports yet. Run a pipeline to generate reports.</div>';
    return;
  }
  el.innerHTML = `<div class="files-grid">${files.map(f => fileCardHtml(f)).join('')}</div>`;
}

function fileCardHtml(f) {
  const meta = fileMeta(f.name);
  return `
    <div class="file-card">
      <div class="file-card-top">
        <div style="display:flex;align-items:center;gap:12px;">
          <div class="file-card-icon ${meta.cls}">${meta.icon}</div>
          <div>
            <div class="file-card-name">${escHtml(f.name)}</div>
            <div class="file-card-size">${f.size} · ${meta.label}</div>
          </div>
        </div>
      </div>
      <div class="file-card-actions">
        <button class="btn btn-sm" onclick="openFile('${escHtml(f.name)}', '${meta.cls}', '${meta.icon}')">
          👁 View
        </button>
        <a class="btn btn-sm" href="/results/${escHtml(f.name)}" download style="text-decoration:none">⬇ Download</a>
      </div>
    </div>`;
}

function fileMeta(name) {
  if (name.includes('summary'))  return { icon:'📋', cls:'summary',  label:'AI Summary'       };
  if (name.includes('ioc'))      return { icon:'🔴', cls:'iocs',     label:'IOC Indicators'   };
  if (name.includes('contact'))  return { icon:'📬', cls:'contacts', label:'Actor Contacts'   };
  if (name.includes('scrape'))   return { icon:'🕸', cls:'default',  label:'Scraped Data'     };
  if (name.includes('search'))   return { icon:'🔎', cls:'default',  label:'Search Results'   };
  return                                { icon:'📄', cls:'default',  label:'Report'           };
}

// ── Modal viewer ──────────────────────────────────────────
async function openFile(name, cls, icon) {
  document.getElementById('modal-icon').textContent  = icon;
  document.getElementById('modal-title').textContent = name;
  document.getElementById('modal-body').innerHTML    =
    '<div class="empty-state"><div class="spinner"></div>Loading…</div>';
  document.getElementById('modal-overlay').classList.add('open');

  const text = await fetch('/results/' + name).then(r => r.text());
  document.getElementById('modal-body').innerHTML = renderContent(name, cls, text);
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

document.getElementById('modal-overlay').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function renderContent(name, cls, text) {
  // All output files are now markdown — render through marked
  if (typeof marked !== 'undefined') {
    return `<div class="markdown-body" style="background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 24px; max-height: 60vh; overflow-y: auto;">${marked.parse(text)}</div>`;
  }
  return `<div class="plain-text" style="white-space: pre-wrap; max-height: 60vh; overflow-y: auto;">${escHtml(text)}</div>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Ollama model selector ─────────────────────────────────
async function onProviderChange() {
  const provider = document.getElementById('provider').value;
  const wrapper = document.getElementById('ollama-model-wrapper');
  if (provider === 'ollama') {
    wrapper.style.display = '';
    await loadOllamaModels();
  } else {
    wrapper.style.display = 'none';
  }
}

async function loadOllamaModels() {
  const sel = document.getElementById('ollama-model');
  sel.innerHTML = '<option value="">Loading…</option>';
  try {
    const res = await fetch('/ollama/models');
    const data = await res.json();
    if (data.models && data.models.length) {
      sel.innerHTML = data.models.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join('');
    } else {
      sel.innerHTML = '<option value="">No models found</option>';
    }
  } catch {
    sel.innerHTML = '<option value="">Failed to load</option>';
  }
}

// Load files on page open
loadFiles();
</script>
</body>
</html>"""


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    return DASHBOARD_HTML


@app.route("/run", methods=["POST"])
def run_pipeline():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400

    job_id = f"job_{int(time.time())}_{os.getpid()}"
    config = {
        "use_ai":        data.get("use_ai", True),
        "ai_provider":   data.get("ai_provider", "gemini"),
        "ollama_model":  data.get("ollama_model", ""),
        "num_engines":   data.get("num_engines", 16),
        "scrape_limit":  data.get("scrape_limit", 10),
        "threads":       data.get("threads", 3),
        "depth":         data.get("depth", 1),
        "max_pages":     data.get("max_pages", 1),
    }

    with _job_lock:
        _jobs[job_id] = {
            "status":  "queued",
            "query":   query,
            "config":  config,
            "created": time.time(),
        }

    thread = threading.Thread(target=_run_pipeline, args=(job_id, query, config), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id):
    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.route("/results")
def list_results():
    output_dir = "output"
    if not os.path.exists(output_dir):
        return jsonify([])

    files = []
    for name in sorted(os.listdir(output_dir), reverse=True):
        path = os.path.join(output_dir, name)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            files.append({"name": name, "size": size_str})
    return jsonify(files)


@app.route("/results/<filename>")
def get_result(filename):
    if ".." in filename or "/" in filename or "\\" in filename:
        return "invalid", 400
    path = os.path.join("output", filename)
    if not os.path.isfile(path):
        return "not found", 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain")


@app.route("/abort/<job_id>", methods=["POST"])
def abort_job(job_id):
    """flag a running job for abort"""
    with _job_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        if job["status"] in ("done", "error", "aborted"):
            return jsonify({"error": "job already finished"}), 400
        job["abort"] = True
    return jsonify({"status": "abort_requested"})


@app.route("/ollama/models")
def ollama_models():
    """return available ollama models for the dropdown"""
    from ai_engine import list_ollama_models
    models = list_ollama_models()
    return jsonify({"models": models})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
