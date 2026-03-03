"""
dark web leak monitor — web dashboard
minimal flask app for running queries, viewing reports, and browsing history.
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


def _run_pipeline(job_id: str, query: str, config: dict):
    """run the main pipeline in a background thread."""
    import io
    import sys
    from contextlib import redirect_stdout

    with _job_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started"] = time.time()

    # capture stdout
    output_buffer = io.StringIO()
    
    try:
        # import pipeline components
        from search import search_dark_web, save_results, get_urls_from_results
        from scrape import scrape_all, save_scraped_data
        from ioc_extractor import extract_iocs_from_scraped, extract_contacts_from_scraped, format_iocs_summary, format_contacts_summary

        use_ai = config.get("use_ai", True)
        num_engines = config.get("num_engines", 17)
        scrape_limit = config.get("scrape_limit", 10)
        threads = config.get("threads", 3)
        depth = config.get("depth", 1)
        max_pages = config.get("max_pages", 1)

        with _job_lock:
            _jobs[job_id]["progress"] = "searching"

        # search
        search_queries = [query]
        if use_ai:
            from ai_engine import refine_query
            keywords = refine_query(query)
            search_queries = keywords + [query]

        all_results = []
        seen_urls = set()
        for sq in search_queries:
            batch = search_dark_web(sq, max_workers=threads, num_engines=num_engines)
            for item in batch:
                url = item["url"] if isinstance(item, dict) else item
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(item)

        save_results(all_results)

        with _job_lock:
            _jobs[job_id]["progress"] = "filtering"

        # filter
        if use_ai and len(all_results) > 20:
            from ai_engine import filter_results
            all_results = filter_results(query, all_results)

        urls = [r["url"] if isinstance(r, dict) else r for r in all_results]
        urls_to_scrape = urls[:scrape_limit]

        with _job_lock:
            _jobs[job_id]["progress"] = "scraping"

        # scrape
        scraped_data, html_cache = scrape_all(urls_to_scrape, max_workers=threads, depth=depth, max_pages=max_pages)
        save_scraped_data(scraped_data)

        # IOC extraction
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
            with _job_lock:
                _jobs[job_id]["progress"] = "classifying"

            from ai_engine import classify_threats, generate_summary
            classifications = classify_threats(query, scraped_data)

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
            _jobs[job_id]["summary_preview"] = summary[:500] if summary else ""

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
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0a0f; color: #e0e0e0; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 24px 32px; border-bottom: 1px solid #2a2a3e; }
.header h1 { font-size: 22px; font-weight: 600; color: #00d4ff; }
.header p { color: #888; font-size: 13px; margin-top: 4px; }
.container { max-width: 900px; margin: 0 auto; padding: 24px; }
.card { background: #12121a; border: 1px solid #2a2a3e; border-radius: 10px; padding: 24px; margin-bottom: 20px; }
.card h2 { font-size: 16px; color: #00d4ff; margin-bottom: 16px; }
label { display: block; color: #aaa; font-size: 13px; margin-bottom: 6px; margin-top: 12px; }
input, select { width: 100%; padding: 10px 14px; background: #1a1a28; border: 1px solid #333; border-radius: 6px; color: #e0e0e0; font-size: 14px; }
input:focus, select:focus { outline: none; border-color: #00d4ff; }
.row { display: flex; gap: 12px; }
.row > div { flex: 1; }
button { background: linear-gradient(135deg, #00d4ff, #0090ff); color: #000; border: none; padding: 12px 24px; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 20px; transition: opacity 0.2s; }
button:hover { opacity: 0.9; }
button:disabled { opacity: 0.4; cursor: not-allowed; }
.status-badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.status-running { background: #1a3a1a; color: #4caf50; }
.status-done { background: #1a2a3a; color: #00d4ff; }
.status-error { background: #3a1a1a; color: #ff4444; }
.result-item { padding: 12px 16px; border-bottom: 1px solid #222; }
.result-item:last-child { border-bottom: none; }
.result-item .label { color: #888; font-size: 12px; }
.result-item .value { color: #e0e0e0; font-size: 14px; }
pre { background: #0a0a12; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 13px; line-height: 1.5; color: #ccc; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
.file-list { list-style: none; }
.file-list li { padding: 8px 0; border-bottom: 1px solid #1a1a28; }
.file-list a { color: #00d4ff; text-decoration: none; }
.file-list a:hover { text-decoration: underline; }
#job-status { display: none; }
</style>
</head>
<body>
<div class="header">
<h1>🔒 Dark Web Leak Monitor</h1>
<p>AI-Powered Intelligence Pipeline</p>
</div>
<div class="container">

<div class="card">
<h2>Run Query</h2>
<form id="query-form">
<label>Search Query</label>
<input type="text" id="query" placeholder="e.g. company data breach" required>
<div class="row">
<div><label>Engines</label><input type="number" id="engines" value="17" min="1" max="17"></div>
<div><label>Scrape Limit</label><input type="number" id="limit" value="10" min="1" max="50"></div>
<div><label>Threads</label><input type="number" id="threads" value="3" min="1" max="10"></div>
</div>
<div class="row">
<div><label>Depth</label><select id="depth"><option value="1">1 (landing)</option><option value="2">2 (sublinks)</option></select></div>
<div><label>Pages/URL</label><input type="number" id="pages" value="1" min="1" max="10"></div>
<div><label>AI Pipeline</label><select id="ai"><option value="1">Enabled</option><option value="0">Disabled</option></select></div>
</div>
<button type="submit" id="run-btn">Run Pipeline</button>
</form>
</div>

<div class="card" id="job-status">
<h2>Job Status</h2>
<div id="job-info"></div>
</div>

<div class="card">
<h2>Past Reports</h2>
<div id="file-list"><p style="color:#666">Loading...</p></div>
</div>

</div>

<script>
const form = document.getElementById('query-form');
const statusDiv = document.getElementById('job-status');
const jobInfo = document.getElementById('job-info');
let pollInterval = null;

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    document.getElementById('run-btn').disabled = true;
    
    const body = {
        query: document.getElementById('query').value,
        num_engines: parseInt(document.getElementById('engines').value),
        scrape_limit: parseInt(document.getElementById('limit').value),
        threads: parseInt(document.getElementById('threads').value),
        depth: parseInt(document.getElementById('depth').value),
        max_pages: parseInt(document.getElementById('pages').value),
        use_ai: document.getElementById('ai').value === '1',
    };
    
    const res = await fetch('/run', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const data = await res.json();
    
    statusDiv.style.display = 'block';
    jobInfo.innerHTML = '<span class="status-badge status-running">Running...</span>';
    
    pollInterval = setInterval(async () => {
        const s = await fetch('/status/' + data.job_id).then(r => r.json());
        let html = `<span class="status-badge status-${s.status}">${s.status}</span>`;
        if (s.progress) html += ` <span style="color:#888">${s.progress}</span>`;
        if (s.status === 'done') {
            html += `<div class="result-item"><span class="label">Results:</span> <span class="value">${s.results_count} found, ${s.scraped_count} scraped</span></div>`;
            if (s.summary_preview) html += `<pre>${s.summary_preview}</pre>`;
            clearInterval(pollInterval);
            document.getElementById('run-btn').disabled = false;
            loadFiles();
        }
        if (s.status === 'error') {
            html += `<pre style="color:#ff4444">${s.error}</pre>`;
            clearInterval(pollInterval);
            document.getElementById('run-btn').disabled = false;
        }
        jobInfo.innerHTML = html;
    }, 2000);
});

async function loadFiles() {
    const res = await fetch('/results');
    const files = await res.json();
    if (files.length === 0) {
        document.getElementById('file-list').innerHTML = '<p style="color:#666">No reports yet.</p>';
        return;
    }
    let html = '<ul class="file-list">';
    for (const f of files) {
        html += `<li><a href="/results/${f.name}" target="_blank">${f.name}</a> <span style="color:#666">(${f.size})</span></li>`;
    }
    html += '</ul>';
    document.getElementById('file-list').innerHTML = html;
}

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
        "use_ai": data.get("use_ai", True),
        "num_engines": data.get("num_engines", 17),
        "scrape_limit": data.get("scrape_limit", 10),
        "threads": data.get("threads", 3),
        "depth": data.get("depth", 1),
        "max_pages": data.get("max_pages", 1),
    }

    with _job_lock:
        _jobs[job_id] = {
            "status": "queued",
            "query": query,
            "config": config,
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
            if size > 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            files.append({"name": name, "size": size_str})
    return jsonify(files)


@app.route("/results/<filename>")
def get_result(filename):
    # safety: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return "invalid", 400
    path = os.path.join("output", filename)
    if not os.path.isfile(path):
        return "not found", 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
