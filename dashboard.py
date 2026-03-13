"""
dark web leak monitor — web dashboard
flask app for running queries, viewing reports, and browsing history.
"""
import os
import json
import time
import threading
from datetime import datetime
import functools
print = functools.partial(print, flush=True)

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
        from ioc_extractor import extract_iocs_from_scraped, extract_contacts_from_scraped, format_iocs_summary

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

        if all_iocs or all_contacts:
            ioc_text = format_iocs_summary(all_iocs, all_contacts)
            os.makedirs("output", exist_ok=True)
            with open("output/iocs.txt", "w", encoding="utf-8") as f:
                f.write(ioc_text)

        summary = ""
        if use_ai:
            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "categorizing"

            from ai_engine import categorize_company_relevance, classify_threats, generate_summary
            company_categories = categorize_company_relevance(query, scraped_data)

            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "classifying"

            classifications = classify_threats(query, scraped_data, company_categories=company_categories)

            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "summarizing"

            summary = generate_summary(query, scraped_data, classifications, regex_iocs=all_iocs, actor_contacts=all_contacts, company_categories=company_categories)

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
    --bg: #0a0a0a;
    --surface: #111111;
    --surface2: #1a1a1a;
    --border: #2a2a2a;
    --accent: #22d3ee;
    --accent2: #06b6d4;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text: #e4e4e7;
    --muted: #71717a;
    --mono: 'JetBrains Mono', monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

  /* HEADER */
  .header {
    background: #0d0d0d;
    padding: 20px 32px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 14px;
  }
  .header-logo {
    width: 10px; height: 24px; border-radius: 2px;
    background: linear-gradient(180deg, var(--accent), var(--accent2));
  }
  .header h1 { font-size: 18px; font-weight: 700; color: var(--text); letter-spacing: -0.01em; }
  .header p { color: var(--muted); font-size: 11px; margin-top: 2px; letter-spacing: 0.04em; text-transform: uppercase; }

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
  .card-header h2 { font-size: 14px; font-weight: 600; color: var(--text); text-transform: uppercase; letter-spacing: 0.04em; }
  .card-header .h-bar { width: 3px; height: 18px; border-radius: 2px; background: var(--accent); flex-shrink: 0; }

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
    background: var(--accent); 
    color: #000; width: 100%; margin-top: 20px;
  }
  .btn-primary:hover { filter: brightness(1.1); transform: translateY(-1px); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-sm {
    padding: 6px 14px; font-size: 12px; border-radius: 6px;
    background: rgba(255,255,255,0.06); color: var(--muted); border: 1px solid var(--border);
  }
  .btn-sm:hover { background: rgba(255,255,255,0.10); color: var(--text); }
  .btn-abort {
    background: var(--danger);
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
  .files-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .file-card {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px; transition: border-color 0.2s, background 0.2s;
  }
  .file-card:hover { border-color: #3a3a3a; background: #1e1e1e; }
  .file-card-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .file-card-indicator {
    width: 4px; height: 32px; border-radius: 2px; flex-shrink: 0;
  }
  .file-card-indicator.summary  { background: var(--accent); }
  .file-card-indicator.iocs     { background: var(--danger); }
  .file-card-indicator.contacts { background: var(--success); }
  .file-card-indicator.results  { background: var(--warning); }
  .file-card-indicator.default  { background: var(--muted); }
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
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    width: 100%; max-width: 95vw; max-height: 95vh; display: flex; flex-direction: column;
    box-shadow: 0 24px 80px rgba(0,0,0,0.6);
  }
  .modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 24px; border-bottom: 1px solid var(--border);
  }
  .modal-title { display: flex; align-items: center; gap: 12px; }
  .modal-title h3 { font-size: 15px; font-weight: 600; }
  .modal-close {
    width: 32px; height: 32px; border-radius: 6px; border: none;
    background: var(--surface2); color: var(--muted); font-size: 18px;
    cursor: pointer; display: flex; align-items: center; justify-content: center;
    transition: background 0.2s, color 0.2s;
  }
  .modal-close:hover { background: rgba(255,255,255,0.08); color: var(--text); }
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
  .markdown-body { font-size: 14px; line-height: 1.6; color: #cbd5e1; font-family: 'Inter', sans-serif; max-height: 80vh; overflow-y: auto; padding-right: 12px; }
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
  .markdown-body table { width: 100%; border-collapse: collapse; margin-bottom: 16px; overflow-x: auto; table-layout: fixed; }
  .markdown-body th, .markdown-body td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; white-space: normal; word-break: break-word; }
  .markdown-body th { background: rgba(255,255,255,0.05); color: white; font-weight: 600; position: sticky; top: 0; z-index: 1; }
  .markdown-body tr:nth-child(even) { background: rgba(255,255,255,0.02); }
  .markdown-body tr:hover { background: rgba(255,255,255,0.02); }
  .markdown-body hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
  .markdown-body a { color: var(--accent); text-decoration: none; }
  .markdown-body a:hover { text-decoration: underline; }
  .markdown-body blockquote { border-left: 3px solid var(--accent); padding: 8px 16px; color: var(--muted); margin: 0 0 16px; background: rgba(255,255,255,0.02); border-radius: 0 6px 6px 0; font-size: 13px; }

  /* ── IOC TABLE SCROLL CONTAINER ── */
  .ioc-scroll {
    max-height: 340px; overflow-y: auto; overflow-x: hidden;
    border: 1px solid var(--border); border-radius: 10px;
    margin-bottom: 4px; background: rgba(0,0,0,0.15);
  }
  .ioc-scroll table { margin-bottom: 0; width: 100%; table-layout: fixed; }
  .ioc-scroll thead th:not(:empty) ~ * { } /* keep non-empty headers */
  .ioc-scroll thead { visibility: collapse; }
  .ioc-scroll td { overflow: hidden; text-overflow: ellipsis; }
  .ioc-scroll::-webkit-scrollbar { width: 5px; }
  .ioc-scroll::-webkit-scrollbar-track { background: transparent; }
  .ioc-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 5px; }
  .ioc-scroll::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

  /* ── CLICK-TO-COPY on code cells ── */
  td code {
    cursor: pointer; transition: all 0.15s ease; position: relative;
  }
  td code:hover { background: rgba(255,255,255,0.10); color: var(--accent); }
  td code:active { transform: scale(0.96); }
  td code.copied { background: rgba(16,185,129,0.2); color: var(--success); }
  .copy-toast {
    position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%) translateY(20px);
    background: rgba(16,185,129,0.92); color: #fff; padding: 8px 20px;
    border-radius: 8px; font-size: 13px; font-weight: 500;
    font-family: 'Inter', sans-serif; pointer-events: none;
    opacity: 0; transition: opacity 0.25s, transform 0.25s; z-index: 999;
  }
  .copy-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

  /* ── SHOW MORE / LESS ── */
  .show-toggle {
    display: block; width: 100%; padding: 7px 0;
    margin: 0 0 16px; border: 1px solid var(--border);
    background: rgba(255,255,255,0.02);
    color: var(--muted); border-radius: 6px;
    cursor: pointer; font-size: 12px; font-weight: 500;
    font-family: 'Inter', sans-serif; letter-spacing: 0.02em;
    transition: all 0.2s ease;
  }
  .show-toggle:hover { color: var(--text); border-color: #3a3a3a; background: rgba(255,255,255,0.04); }
</style>
</head>
<body>
<div class="header">
  <div class="header-logo"></div>
  <div>
    <h1>Dark Web Leak Monitor</h1>
    <p>Threat Intelligence Pipeline</p>
  </div>
</div>
<div class="container">

  <!-- RUN QUERY -->
  <div class="card">
    <div class="card-header">
      <div class="h-bar"></div>
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
      <button type="submit" id="run-btn" class="btn btn-primary">Run Pipeline</button>
    </form>
  </div>

  <!-- JOB STATUS -->
  <div class="card" id="job-status">
    <div class="card-header">
      <div class="h-bar"></div>
      <h2>Job Status</h2>
    </div>
    <div id="job-info"></div>
  </div>

  <!-- REPORTS -->
  <div class="card">
    <div class="card-header">
      <div class="h-bar"></div>
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

const STEPS = ['searching','filtering','scraping','categorizing','classifying','summarizing'];

function setButtonRun() {
  runBtn.textContent = 'Run Pipeline';
  runBtn.className = 'btn btn-primary';
  runBtn.disabled = false;
  runBtn.onclick = null;
  runBtn.type = 'submit';
}

function setButtonAbort() {
  runBtn.textContent = 'Abort';
  runBtn.className = 'btn btn-abort';
  runBtn.disabled = false;
  runBtn.type = 'button';
  runBtn.onclick = abortJob;
}

async function abortJob() {
  if (!currentJobId) return;
  runBtn.disabled = true;
  runBtn.textContent = 'Aborting…';
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
      ${progress === s ? '›' : (STEPS.indexOf(s) < STEPS.indexOf(progress) ? '·' : '·')} ${s}
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
          <div class="file-card-indicator ${meta.cls}"></div>
          <div>
            <div class="file-card-name">${meta.displayName}</div>
            <div class="file-card-size">${f.size} · ${meta.label}</div>
          </div>
        </div>
      </div>
      <div class="file-card-actions">
        <button class="btn btn-sm" onclick="openFile('${escHtml(f.name)}', '${meta.cls}', '${meta.displayName}')">View</button>
        <a class="btn btn-sm" href="/results/${escHtml(f.name)}" download style="text-decoration:none">Download</a>
      </div>
    </div>`;
}

function fileMeta(name) {
  if (name.includes('summary'))  return { displayName:'Summary',        cls:'summary',  label:'AI Summary'       };
  if (name.includes('ioc'))      return { displayName:'IOC Indicators',  cls:'iocs',     label:'IOC Indicators'   };
  if (name.includes('contact'))  return { displayName:'Actor Contacts',  cls:'contacts', label:'Actor Contacts'   };
  if (name.includes('scrape'))   return { displayName:'Scraped Data',    cls:'default',  label:'Scraped Data'     };
  if (name.includes('result'))   return { displayName:'Search Results',  cls:'results',  label:'Search Results'   };
  return                                { displayName: name,             cls:'default',  label:'Report'           };
}

// ── Modal viewer ──────────────────────────────────────────
async function openFile(name, cls, displayName) {
  document.getElementById('modal-title').textContent = displayName;
  document.getElementById('modal-body').innerHTML    =
    '<div class="empty-state"><div class="spinner"></div>Loading…</div>';
  document.getElementById('modal-overlay').classList.add('open');

  const text = await fetch('/results/' + name).then(r => r.text());
  document.getElementById('modal-body').innerHTML = renderContent(name, cls, text);
  // post-process IOC tables after DOM is updated
  requestAnimationFrame(() => enhanceIOCView(document.getElementById('modal-body')));
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

document.getElementById('modal-overlay').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

function renderContent(name, cls, text) {
  if (typeof marked !== 'undefined') {
    return `<div class="markdown-body" style="background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 24px; max-height: 80vh; overflow-y: auto;">${marked.parse(text)}</div>`;
  }
  return `<div class="plain-text" style="white-space: pre-wrap; max-height: 80vh; overflow-y: auto;">${escHtml(text)}</div>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── IOC post-processing ─────────────────────────────────────
function enhanceIOCView(root) {
  if (!root) return;

  // ensure toast element exists
  if (!document.getElementById('copy-toast')) {
    const t = document.createElement('div');
    t.id = 'copy-toast'; t.className = 'copy-toast'; t.textContent = '✓ Copied to clipboard';
    document.body.appendChild(t);
  }

  // 1) Click-to-copy on every <code> inside td
  root.querySelectorAll('td code').forEach(code => {
    if (code._copyBound) return;
    code._copyBound = true;
    code.title = 'Click to copy';
    code.addEventListener('click', () => {
      navigator.clipboard.writeText(code.textContent).then(() => {
        code.classList.add('copied');
        setTimeout(() => code.classList.remove('copied'), 900);
        const toast = document.getElementById('copy-toast');
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 1200);
      });
    });
  });

  // 2) Scrollable + collapsible tables
  root.querySelectorAll('.markdown-body table').forEach(tbl => {
    if (tbl.closest('.ioc-scroll')) return; // already wrapped
    const body = tbl.querySelector('tbody') || tbl;
    const rows = Array.from(body.querySelectorAll('tr')).filter(r => !r.querySelector('th'));
    if (rows.length <= 5) return; // small table, leave as-is

    // wrap in scrollable container
    const wrap = document.createElement('div');
    wrap.className = 'ioc-scroll';
    tbl.parentNode.insertBefore(wrap, tbl);
    wrap.appendChild(tbl);

    if (rows.length > 10) {
      // collapse rows > 10
      rows.forEach((r, i) => { if (i >= 10) r.style.display = 'none'; });
      const btn = document.createElement('button');
      btn.className = 'show-toggle';
      btn.textContent = '▾  Show ' + (rows.length - 10) + ' more items';
      let open = false;
      btn.onclick = () => {
        open = !open;
        rows.forEach((r, i) => { if (i >= 10) r.style.display = open ? '' : 'none'; });
        btn.textContent = open ? '▴  Show less' : '▾  Show ' + (rows.length - 10) + ' more items';
        wrap.style.maxHeight = open ? 'none' : '340px';
      };
      wrap.after(btn);
    }
  });
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
