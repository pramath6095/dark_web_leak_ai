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

from search import SEARCH_ENGINES
MAX_ENGINES = len(SEARCH_ENGINES)

# job tracking
_jobs = {}
_job_lock = threading.Lock()

# automation state
_AUTO_SETTINGS_FILE = os.path.join("output", "automation_settings.json")
_ALERTS_FILE = os.path.join("output", "alerts.json")
_auto_timer = None  # reference to the scheduler timer
_auto_lock = threading.Lock()


def _load_auto_settings():
    """load automation settings from disk"""
    if os.path.isfile(_AUTO_SETTINGS_FILE):
        try:
            with open(_AUTO_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {"enabled": False, "interval_hours": 6.0, "webhook_url": ""}


def _save_auto_settings(settings):
    """persist automation settings to disk"""
    os.makedirs("output", exist_ok=True)
    with open(_AUTO_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def _load_alerts():
    """load alerts history from disk"""
    if os.path.isfile(_ALERTS_FILE):
        try:
            with open(_ALERTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _save_alerts(alerts):
    """persist alerts to disk"""
    os.makedirs("output", exist_ok=True)
    with open(_ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2)


def _add_alert(severity, title, evidence="", category=""):
    """append a new alert to the alerts history"""
    alerts = _load_alerts()
    entry = {
        "timestamp": datetime.now().strftime("%b %d, %I:%M %p"),
        "severity": severity,
        "title": title,
        "evidence": evidence[:500] if evidence else "",
    }
    if category:
        entry["category"] = category
    alerts.insert(0, entry)
    # keep latest 50 alerts
    alerts = alerts[:50]
    _save_alerts(alerts)
    return alerts


def _generate_alerts_from_classifications(query, classifications, company_categories):
    """extract company-specific key findings from classifications and add as alerts.
    deduplicates against existing alerts to avoid showing the same finding twice."""
    if not classifications:
        return

    # build dedup fingerprints from existing alerts: (category, evidence_lowercase)
    existing_alerts = _load_alerts()
    existing_fingerprints = set()
    for a in existing_alerts:
        cat = a.get("category", "")
        ev = a.get("evidence", "").strip().lower()
        if cat and ev:
            existing_fingerprints.add((cat, ev))

    # filter for company-specific pages only
    cs_findings = []
    for url, cls in classifications.items():
        relevance = "general"
        if company_categories:
            relevance = cls.get("company_relevance", company_categories.get(url, "general"))
        if relevance == "company_specific":
            cs_findings.append(cls)

    # only use company-specific findings for alerts
    findings_to_alert = cs_findings

    if not findings_to_alert:
        _add_alert("clear", f"Scan complete for \"{query}\"",
                   f"Scanned {len(classifications)} pages. No high-severity threats found.")
        return

    # sort by severity: critical > high > medium > low
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings_to_alert.sort(key=lambda x: sev_order.get(x.get("severity", "low"), 3))

    # add individual alerts for the top findings (max 5), skipping duplicates
    added = 0
    for finding in findings_to_alert:
        if added >= 5:
            break

        cat = finding.get("category", "other")
        evidence = finding.get("evidence", "")
        fingerprint = (cat, evidence.strip().lower())

        # skip if this exact (category, evidence) already exists
        if fingerprint in existing_fingerprints:
            continue

        sev = finding.get("severity", "medium")
        reason = finding.get("reason", "")

        alert_sev = "critical" if sev in ("critical", "high") else "medium"
        title = f"{cat.replace('_', ' ').title()}: {reason}" if reason else f"{cat.replace('_', ' ').title()} detected"

        _add_alert(alert_sev, title, evidence, category=cat)
        existing_fingerprints.add(fingerprint)
        added += 1

    if added == 0:
        # all findings were duplicates — log a quiet heartbeat
        _add_alert("clear", f"Scan complete for \"{query}\"",
                   f"No new findings. {len(findings_to_alert)} findings already tracked.")


def _cancel_auto_timer():
    """cancel any pending automated timer"""
    global _auto_timer
    with _auto_lock:
        if _auto_timer is not None:
            _auto_timer.cancel()
            _auto_timer = None


def _schedule_next_run_after_complete(query, config):
    """schedule the next automated run AFTER the current one finishes.
    The timer only starts counting down once this function is called."""
    global _auto_timer
    _cancel_auto_timer()

    settings = _load_auto_settings()
    if not settings.get("enabled"):
        return

    interval_secs = settings.get("interval_hours", 6) * 3600
    # record when the next run will fire so the UI countdown is accurate
    settings["next_run_ts"] = time.time() + interval_secs
    _save_auto_settings(settings)

    with _auto_lock:
        _auto_timer = threading.Timer(interval_secs, _auto_run, args=(query, config))
        _auto_timer.daemon = True
        _auto_timer.start()
    print(f"[AUTOMATION] Next run scheduled in {settings.get('interval_hours', 6)}h (starts after completion)")


def _auto_run(query, config):
    """execute one automated pipeline run, then schedule the next one
    only after this run is fully complete."""
    global _auto_timer
    with _auto_lock:
        _auto_timer = None  # timer has fired

    settings = _load_auto_settings()
    if not settings.get("enabled"):
        return

    print(f"[AUTOMATION] Starting automated run for: {query}")

    job_id = f"auto_{int(time.time())}_{os.getpid()}"

    with _job_lock:
        _jobs[job_id] = {
            "status": "queued",
            "query": query,
            "config": config,
            "created": time.time(),
            "automated": True,
        }

    try:
        _run_pipeline(job_id, query, config)
    except Exception as e:
        _add_alert("medium", "Automated run failed", str(e)[:300])

    # schedule the NEXT run only now that this one is done
    _schedule_next_run_after_complete(query, config)


def _check_abort(job_id: str) -> bool:
    """check if a job has been flagged for abort"""
    with _job_lock:
        return _jobs.get(job_id, {}).get("abort", False)


def _run_pipeline(job_id: str, query: str, config: dict):
    """run the main pipeline in a background thread."""
    import io
    import sys
    import builtins
    from contextlib import redirect_stdout

    with _job_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started"] = time.time()
        _jobs[job_id]["logs"] = []

    output_buffer = io.StringIO()

    # capture print() calls into the job's log buffer
    _original_print = builtins.print
    def _capturing_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        with _job_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.setdefault("logs", []).append(msg)
                # keep last 200 lines
                if len(job["logs"]) > 200:
                    job["logs"] = job["logs"][-200:]
        kwargs.setdefault("flush", True)
        _original_print(*args, **kwargs)

    builtins.print = _capturing_print

    # also patch module-level print in modules that shadow builtins.print
    # with functools.partial (so their logs appear in the dashboard)
    import scrape as _scrape_mod
    import search as _search_mod
    import forum_auth as _forum_mod
    _orig_scrape_print = _scrape_mod.print
    _orig_search_print = _search_mod.print
    _orig_forum_print = _forum_mod.print
    _scrape_mod.print = _capturing_print
    _search_mod.print = _capturing_print
    _forum_mod.print = _capturing_print

    try:
        from search import search_dark_web, save_results, get_urls_from_results
        from scrape import scrape_all, save_scraped_data
        from ioc_extractor import extract_iocs_from_scraped, extract_contacts_from_scraped, format_iocs_summary

        use_ai = config.get("use_ai", True)
        ai_provider = config.get("ai_provider", "gemini")
        num_engines = config.get("num_engines", MAX_ENGINES)
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
            _jobs[job_id].setdefault("stage_times", {})["searching"] = time.time()

        search_queries = [query]
        if use_ai:
            from ai_engine import refine_query
            keywords = refine_query(query)
            search_queries = [query] + keywords

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
            _jobs[job_id].setdefault("stage_times", {})["filtering"] = time.time()

        if use_ai and len(all_results) > scrape_limit:
            from ai_engine import filter_results
            all_results = filter_results(query, all_results, limit=scrape_limit)

        urls = [r["url"] if isinstance(r, dict) else r for r in all_results]
        urls_to_scrape = urls[:scrape_limit]

        if _check_abort(job_id): raise InterruptedError("Aborted")

        with _job_lock:
            _jobs[job_id]["progress"] = "scraping"
            _jobs[job_id].setdefault("stage_times", {})["scraping"] = time.time()

        scraped_data, html_cache = scrape_all(urls_to_scrape, max_workers=threads, depth=depth, max_pages=max_pages, check_abort=lambda: _check_abort(job_id), target_query=query)
        save_scraped_data(scraped_data)

        if _check_abort(job_id): raise InterruptedError("Aborted")

        all_iocs = extract_iocs_from_scraped(scraped_data)
        all_contacts = extract_contacts_from_scraped(scraped_data)

        summary = ""
        company_categories = {}
        if use_ai:
            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "categorizing"
                _jobs[job_id].setdefault("stage_times", {})["categorizing"] = time.time()

            from ai_engine import categorize_company_relevance, classify_threats, generate_summary
            company_categories = categorize_company_relevance(query, scraped_data)

            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "classifying"
                _jobs[job_id].setdefault("stage_times", {})["classifying"] = time.time()

            classifications = classify_threats(query, scraped_data, company_categories=company_categories)

            # generate alerts from company-specific classifications
            _generate_alerts_from_classifications(query, classifications, company_categories)

            if _check_abort(job_id): raise InterruptedError("Aborted")

            # file analysis + AI verification
            with _job_lock:
                _jobs[job_id]["progress"] = "analyzing_files"
                _jobs[job_id].setdefault("stage_times", {})["analyzing_files"] = time.time()

            try:
                from file_analyzer import analyze_threat_files, format_file_analysis
                file_analysis = analyze_threat_files(html_cache, classifications, max_workers=threads)

                file_verdicts = {}
                if file_analysis:
                    if _check_abort(job_id): raise InterruptedError("Aborted")
                    from ai_engine import verify_threat_files
                    file_verdicts = verify_threat_files(query, file_analysis)

                    # save file analysis report
                    report = format_file_analysis(file_analysis, file_verdicts)
                    os.makedirs("output", exist_ok=True)
                    with open("output/file_analysis.txt", "w", encoding="utf-8") as f:
                        f.write(report)
            except InterruptedError:
                raise
            except Exception as e:
                print(f"[!] File analysis failed: {str(e)[:100]}")

            if _check_abort(job_id): raise InterruptedError("Aborted")

            with _job_lock:
                _jobs[job_id]["progress"] = "summarizing"
                _jobs[job_id].setdefault("stage_times", {})["summarizing"] = time.time()

            summary = generate_summary(query, scraped_data, classifications, regex_iocs=all_iocs, actor_contacts=all_contacts, company_categories=company_categories)

            os.makedirs("output", exist_ok=True)
            with open("output/summary.txt", "w", encoding="utf-8") as f:
                f.write(summary)

        # save IOCs + contacts (after company categorization if AI enabled)
        if all_iocs or all_contacts:
            ioc_text = format_iocs_summary(all_iocs, all_contacts, company_categories=company_categories or None)
            os.makedirs("output", exist_ok=True)
            with open("output/iocs.txt", "w", encoding="utf-8") as f:
                f.write(ioc_text)

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

    finally:
        # restore original print for all patched modules
        import builtins as _bi
        _bi.print = _original_print
        _scrape_mod.print = _orig_scrape_print
        _search_mod.print = _orig_search_print
        _forum_mod.print = _orig_forum_print


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
  .container { max-width: 95vw; margin: 0 auto; padding: 28px 24px; }

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

  /* PIPELINE TIMER & ERROR COUNTER */
  .pipeline-stats-row {
    display: flex; gap: 14px; margin-bottom: 14px; flex-wrap: wrap;
  }
  .pipeline-stat-widget {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 20px; display: flex; align-items: center; gap: 14px;
    min-width: 200px; flex: 1;
  }
  .pipeline-stat-widget .stat-icon {
    width: 40px; height: 40px; border-radius: 10px; display: flex;
    align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;
  }
  .pipeline-stat-widget .stat-icon.timer-icon {
    background: rgba(34,211,238,0.12); color: var(--accent);
  }
  .pipeline-stat-widget .stat-icon.error-icon {
    background: rgba(239,68,68,0.12); color: var(--danger);
  }
  .pipeline-stat-widget .stat-label {
    color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 2px;
  }
  .pipeline-stat-widget .stat-value {
    color: var(--text); font-size: 22px; font-weight: 700;
    font-family: var(--mono); letter-spacing: -0.02em;
  }
  .pipeline-stat-widget .stat-value.timer-active {
    color: var(--accent);
  }
  .pipeline-stat-widget .stat-value.has-errors {
    color: var(--danger);
  }
  .error-breakdown {
    display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap;
  }
  .error-breakdown .err-tag {
    font-size: 10px; padding: 2px 7px; border-radius: 4px;
    background: rgba(239,68,68,0.08); color: #f87171;
    border: 1px solid rgba(239,68,68,0.15);
  }

  /* JOB STATUS */
  #job-status { display: none; }
  .job-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .job-stat { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 16px; }
  .job-stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .job-stat .value { color: var(--text); font-size: 18px; font-weight: 700; margin-top: 2px; }
  .progress-step { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; }
  .progress-step.active { color: var(--accent); }

  /* STAGE TIMELINE */
  .stage-timeline {
    display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px;
  }
  .stage-chip {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 14px; border-radius: 8px; font-size: 12px;
    background: var(--surface2); border: 1px solid var(--border);
    transition: all 0.3s ease; min-width: 130px;
  }
  .stage-chip.done {
    border-color: rgba(16,185,129,0.25);
  }
  .stage-chip.active {
    border-color: rgba(34,211,238,0.4);
    background: rgba(34,211,238,0.06);
    box-shadow: 0 0 12px rgba(34,211,238,0.08);
  }
  .stage-chip.pending {
    opacity: 0.4;
  }
  .stage-chip .stage-dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }
  .stage-chip.done .stage-dot { background: var(--success); }
  .stage-chip.active .stage-dot { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
  .stage-chip.pending .stage-dot { background: var(--muted); }
  .stage-chip .stage-name {
    font-weight: 500; color: var(--text); text-transform: capitalize;
  }
  .stage-chip.pending .stage-name { color: var(--muted); }
  .stage-chip .stage-time {
    margin-left: auto; font-family: var(--mono); font-size: 11px;
    color: var(--muted); min-width: 32px; text-align: right;
  }
  .stage-chip.active .stage-time { color: var(--accent); }
  .stage-chip.done .stage-time { color: var(--success); }
  .stage-chevron {
    color: var(--border); font-size: 12px; display: flex; align-items: center;
  }
  .summary-preview { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 16px; font-size: 13px; line-height: 1.7; color: #cbd5e1; white-space: normal; max-height: 350px; overflow-y: auto; overflow-x: auto; margin-top: 12px; }

  /* LIVE LOG PANEL */
  .log-panel {
    background: #080808; border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; margin-top: 14px; max-height: 260px; overflow-y: auto;
    font-family: var(--mono); font-size: 12px; line-height: 1.7;
    color: #6ee7b7; position: relative;
  }
  .log-panel::before {
    content: '● LIVE'; position: absolute; top: 10px; right: 14px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
    color: var(--success); animation: pulse 1.2s ease-in-out infinite;
  }
  .log-panel.done::before { content: 'COMPLETE'; color: var(--muted); animation: none; }
  .log-line { white-space: pre-wrap; word-break: break-all; }
  .log-line.error { color: #f87171; }
  .log-line.warn { color: #fbbf24; }
  .log-line.info { color: #6ee7b7; }
  .log-line.step { color: var(--accent); font-weight: 600; }

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
  .markdown-body table { width: 100%; border-collapse: collapse; margin-bottom: 16px; overflow-x: auto; table-layout: auto; }
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
  .ioc-scroll table { margin-bottom: 0; width: 100%; table-layout: auto; }
  .ioc-scroll thead th:not(:empty) ~ * { } /* keep non-empty headers */
  .ioc-scroll thead { visibility: collapse; }
  .ioc-scroll td { overflow: visible; word-break: break-all; }
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

  /* ── 3-COLUMN DASHBOARD GRID ── */
  .dashboard-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 24px;
  }
  .dashboard-grid > .card { display: flex; flex-direction: column; height: 100%; margin-bottom: 0; }

  /* ── TOGGLE SWITCH ── */
  .toggle-switch { position: relative; display: inline-block; width: 44px; height: 24px; }
  .toggle-switch input { opacity: 0; width: 0; height: 0; }
  .slider-toggle {
    position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
    background-color: var(--surface2); transition: .4s; border-radius: 24px;
    border: 1px solid var(--border);
  }
  .slider-toggle:before {
    position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px;
    background-color: var(--muted); transition: .4s; border-radius: 50%;
  }
  input:checked + .slider-toggle { background-color: var(--accent); border-color: var(--accent); }
  input:checked + .slider-toggle:before { transform: translateX(20px); background-color: #000; }

  /* ── ALERTS LIST ── */
  .alerts-list { display: flex; flex-direction: column; gap: 10px; overflow-y: auto; flex: 1; margin-top: 10px; max-height: 420px; }
  .alert-item { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .alert-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
  .alert-time { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
  .alert-title { font-size: 13px; font-weight: 600; color: var(--text); }
  .evidence-box {
    background: rgba(0,0,0,0.3); border-left: 2px solid var(--danger); padding: 8px 12px;
    border-radius: 4px; font-family: var(--mono); font-size: 11px; color: #f87171;
    margin-top: 8px; max-height: 80px; overflow-y: auto; white-space: pre-wrap; line-height: 1.5;
  }
  .evidence-box.warning { border-left-color: var(--warning); color: #fbbf24; }
  .cat-tag {
    display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px;
    font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin-right: 6px;
    background: rgba(34,211,238,0.12); color: var(--accent); border: 1px solid rgba(34,211,238,0.25);
  }
  .cat-tag.data_breach { background: rgba(239,68,68,0.12); color: #f87171; border-color: rgba(239,68,68,0.3); }
  .cat-tag.credentials { background: rgba(245,158,11,0.12); color: #fbbf24; border-color: rgba(245,158,11,0.3); }
  .cat-tag.malware { background: rgba(168,85,247,0.12); color: #c084fc; border-color: rgba(168,85,247,0.3); }
  .cat-tag.market_listing { background: rgba(16,185,129,0.12); color: #34d399; border-color: rgba(16,185,129,0.3); }
  .cat-tag.paste { background: rgba(100,116,139,0.15); color: #94a3b8; border-color: rgba(100,116,139,0.3); }
  .btn-secondary {
    background: var(--surface2); color: var(--text); border: 1px solid var(--border);
    width: 100%; margin-top: 10px;
  }
  .btn-secondary:hover { background: rgba(255,255,255,0.05); }

  /* ── AUTO STATUS PILL IN HEADER ── */
  .auto-status-pill {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 16px; border-radius: 20px; font-size: 12px; font-weight: 500;
  }
  .auto-status-pill.active { background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.3); color: var(--success); }
  .auto-status-pill.inactive { background: rgba(100,116,139,0.15); border: 1px solid var(--border); color: var(--muted); }
  .status-dot-sm { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
  .status-dot-sm.pulse { box-shadow: 0 0 6px currentColor; animation: pulse 1.2s ease-in-out infinite; }

  /* ── FORUM ACCOUNTS 2-COL LAYOUT ── */
  .forum-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  .forum-panel {
    min-width: 0; /* prevent overflow */
  }
  .forum-panel-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 14px;
  }
  .forum-panel-header .panel-dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }
  .forum-panel-header h3 {
    font-size: 12px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .login-wall-item {
    background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; margin-bottom: 8px;
    transition: border-color 0.2s;
  }
  .login-wall-item:hover { border-color: #3a3a3a; }
  .login-wall-url {
    font-family: var(--mono); font-size: 11px; color: var(--text);
    word-break: break-all; line-height: 1.5;
  }
  .login-wall-meta {
    display: flex; align-items: center; gap: 8px; margin-top: 6px;
    font-size: 10px; color: var(--muted);
  }
  .login-wall-badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .login-wall-badge.success {
    background: rgba(16,185,129,0.12); color: var(--success); border: 1px solid rgba(16,185,129,0.25);
  }
  .login-wall-badge.failed {
    background: rgba(239,68,68,0.12); color: var(--danger); border: 1px solid rgba(239,68,68,0.25);
  }
  .login-walls-scroll {
    max-height: 260px; overflow-y: auto;
  }
  .login-walls-scroll::-webkit-scrollbar { width: 5px; }
  .login-walls-scroll::-webkit-scrollbar-track { background: transparent; }
  .login-walls-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 5px; }
  .login-walls-scroll::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
  .wall-count-pill {
    margin-left: auto;
    padding: 2px 10px; border-radius: 10px; font-size: 10px; font-weight: 600;
    background: rgba(239,68,68,0.12); color: var(--danger); border: 1px solid rgba(239,68,68,0.2);
  }
</style>
</head>
<body>
<div class="header">
  <div class="header-logo"></div>
  <div>
    <h1>Dark Web Leak Monitor</h1>
    <p>Threat Intelligence Pipeline</p>
  </div>
  <div class="auto-status-pill inactive" id="auto-pill">
    <div class="status-dot-sm"></div>
    <span id="auto-pill-text">Automation Off</span>
  </div>
</div>
<div class="container">

  <!-- 3-COLUMN DASHBOARD GRID -->
  <div class="dashboard-grid">

  <!-- COLUMN 1: RUN QUERY -->
  <div class="card">
    <div class="card-header">
      <div class="h-bar"></div>
      <h2>Run Query</h2>
    </div>
    <form id="query-form" style="display:flex;flex-direction:column;flex:1">
      <label>Search Query</label>
      <input type="text" id="query" placeholder="e.g. company data breach, leaked credentials…" required>
      <div class="row">
        <div><label>Engines</label><input type="number" id="engines" value="__MAX_ENGINES__" min="1" max="__MAX_ENGINES__"></div>
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
            <option value="ollama" selected>Ollama (Local)</option>
            <option value="gemini">Gemini</option>
            <option value="anthropic">Anthropic</option>
            <option value="deepseek">DeepSeek</option>
            <option value="groq">Groq</option>
            <option value="mistral">Mistral</option>
          </select>
        </div>
        <div id="ollama-model-wrapper">
          <label>Ollama Model</label>
          <select id="ollama-model">
            <option value="">Loading models…</option>
          </select>
        </div>
      </div>
      <!-- AUTOMATION: inline repeat controls -->
      <div class="row" style="margin-top:8px;align-items:center">
        <div style="flex:0 0 auto;display:flex;align-items:center;gap:10px;padding-top:16px">
          <label class="toggle-switch" style="margin:0">
            <input type="checkbox" id="auto-enabled">
            <span class="slider-toggle"></span>
          </label>
          <span style="color:var(--accent);font-size:13px;font-weight:600;white-space:nowrap">Repeat</span>
        </div>
        <div><label>Interval (Hours)</label><input type="number" id="auto-interval" value="6" min="0.001" max="168" step="any" placeholder="e.g. 0.5, 1, 6, 24"></div>
        <div><label>Webhook URL</label><input type="text" id="auto-webhook" placeholder="https://discord/slack…"></div>
      </div>
      <div style="padding:8px 0;text-align:center;margin-top:6px">
        <span style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Next Automated Run: </span>
        <span style="font-weight:600;color:var(--accent);font-size:13px" id="auto-countdown">—</span>
      </div>
      <button type="submit" id="run-btn" class="btn btn-primary">Run Pipeline</button>
    </form>
  </div>

  <!-- COLUMN 3: RECENT ALERTS -->
  <div class="card">
    <div class="card-header" style="margin-bottom:8px">
      <div class="h-bar" style="background:var(--danger)"></div>
      <h2 style="display:flex;align-items:center;justify-content:space-between;width:100%">
        Recent Alerts
        <span class="badge badge-error" id="alert-count-badge" style="font-size:11px;padding:2px 8px;display:none">0 New</span>
      </h2>
    </div>
    <div class="alerts-list" id="alerts-list">
      <div class="empty-state">No alerts yet. Enable automation to start monitoring.</div>
    </div>
  </div>

  </div> <!-- END dashboard-grid -->

  <!-- FORUM ACCOUNTS + LOGIN WALLS (2-col) -->
  <div class="card">
    <div class="card-header">
      <div class="h-bar" style="background:var(--success)"></div>
      <h2>Forum Accounts & Login Walls</h2>
    </div>
    <div class="forum-grid">
      <!-- LEFT: Account Management -->
      <div class="forum-panel">
        <div class="forum-panel-header">
          <div class="panel-dot" style="background:var(--success)"></div>
          <h3>Stored Credentials</h3>
        </div>
        <div style="margin-bottom:14px">
          <div style="display:flex;gap:8px;align-items:flex-end">
            <div style="flex:1"><label>Domain (.onion)</label><input type="text" id="forum-domain" placeholder="abc123xyz.onion"></div>
            <div style="flex:1"><label>Username</label><input type="text" id="forum-user" placeholder="username"></div>
            <div style="flex:1"><label>Password</label><input type="text" id="forum-pass" placeholder="password"></div>
            <button class="btn btn-sm" style="height:40px;padding:0 18px;margin-bottom:1px" onclick="addForumAccount()">Add Account</button>
          </div>
        </div>
        <div id="forum-accounts-list"><div class="empty-state">No forum accounts stored.</div></div>
      </div>
      <!-- RIGHT: Detected Login Walls -->
      <div class="forum-panel">
        <div class="forum-panel-header">
          <div class="panel-dot" style="background:var(--danger)"></div>
          <h3>Detected Login Walls</h3>
          <span class="wall-count-pill" id="wall-count-pill" style="display:none">0</span>
        </div>
        <div class="login-walls-scroll" id="login-walls-list">
          <div class="empty-state">No login walls detected yet. Run a scan to discover them.</div>
        </div>
      </div>
    </div>
  </div>

  <!-- JOB STATUS -->
  <div class="card" id="job-status">
    <div class="card-header">
      <div class="h-bar"></div>
      <h2>Job Status</h2>
    </div>
    <div class="pipeline-stats-row" id="pipeline-stats-row" style="display:none">
      <div class="pipeline-stat-widget">
        <div class="stat-icon timer-icon">⏱</div>
        <div>
          <div class="stat-label">Pipeline Duration</div>
          <div class="stat-value" id="pipeline-timer">00:00</div>
        </div>
      </div>
      <div class="pipeline-stat-widget">
        <div class="stat-icon error-icon">⚠</div>
        <div>
          <div class="stat-label">Tor Connection Errors</div>
          <div class="stat-value" id="error-counter">0</div>
          <div class="error-breakdown" id="error-breakdown"></div>
        </div>
      </div>
    </div>
    <div id="job-info"></div>
    <div id="job-log-panel"></div>
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
let logPollInterval = null;
let currentJobId = null;
let logLineCount = 0;
let lastStageTimes = {};

// ── Pipeline Timer ──
let timerInterval = null;
let timerStartTime = null;

// ── Error Counter ──
let torErrors = { connection: 0, timeout: 0, dead_link: 0, http: 0, other: 0 };

function resetTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = null;
  timerStartTime = null;
  const el = document.getElementById('pipeline-timer');
  if (el) { el.textContent = '00:00'; el.classList.remove('timer-active'); }
}

function startTimer() {
  resetTimer();
  timerStartTime = Date.now();
  const el = document.getElementById('pipeline-timer');
  if (el) el.classList.add('timer-active');
  timerInterval = setInterval(updateTimerDisplay, 200);
  updateTimerDisplay();
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = null;
  const el = document.getElementById('pipeline-timer');
  if (el) el.classList.remove('timer-active');
  updateTimerDisplay();
}

function updateTimerDisplay() {
  if (!timerStartTime) return;
  const elapsed = Date.now() - timerStartTime;
  const mins = Math.floor(elapsed / 60000);
  const secs = Math.floor((elapsed % 60000) / 1000);
  const el = document.getElementById('pipeline-timer');
  if (el) el.textContent = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
}

function resetErrorCounter() {
  torErrors = { connection: 0, timeout: 0, dead_link: 0, http: 0, other: 0 };
  updateErrorDisplay();
}

function countErrorsInLine(line) {
  const lower = line.toLowerCase();
  // check timeout before connection since 'connection timeout' contains 'connection'
  if (lower.includes('[error: connection timeout]')) { torErrors.timeout++; updateErrorDisplay(); }
  else if (lower.includes('[error: connection')) { torErrors.connection++; updateErrorDisplay(); }
  else if (lower.includes('[error: dead link]')) { torErrors.dead_link++; updateErrorDisplay(); }
  else if (lower.includes('[error: http')) { torErrors.http++; updateErrorDisplay(); }
  else if (lower.includes('[error: request failed]')) { torErrors.other++; updateErrorDisplay(); }
}

function updateErrorDisplay() {
  const total = torErrors.connection + torErrors.timeout + torErrors.dead_link + torErrors.http + torErrors.other;
  const el = document.getElementById('error-counter');
  if (el) {
    el.textContent = total;
    el.className = 'stat-value' + (total > 0 ? ' has-errors' : '');
  }
  const bd = document.getElementById('error-breakdown');
  if (bd) {
    let tags = [];
    if (torErrors.connection) tags.push(`<span class="err-tag">Connect: ${torErrors.connection}</span>`);
    if (torErrors.timeout) tags.push(`<span class="err-tag">Timeout: ${torErrors.timeout}</span>`);
    if (torErrors.dead_link) tags.push(`<span class="err-tag">Dead: ${torErrors.dead_link}</span>`);
    if (torErrors.http) tags.push(`<span class="err-tag">HTTP: ${torErrors.http}</span>`);
    if (torErrors.other) tags.push(`<span class="err-tag">Other: ${torErrors.other}</span>`);
    bd.innerHTML = tags.join('');
  }
}

const STEPS = ['searching','filtering','scraping','authenticating','categorizing','classifying','analyzing_files','summarizing'];

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
    repeat:       document.getElementById('auto-enabled').checked,
    interval_hours: parseFloat(document.getElementById('auto-interval').value) || 6,
    webhook_url:  document.getElementById('auto-webhook').value,
  };
  const res  = await fetch('/run', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  const data = await res.json();
  currentJobId = data.job_id;
  statusDiv.style.display = 'block';
  logLineCount = 0;
  document.getElementById('job-log-panel').innerHTML = '<div class="log-panel" id="live-log"></div>';
  // Show stats row, start timer, reset error counter
  document.getElementById('pipeline-stats-row').style.display = '';
  resetErrorCounter();
  startTimer();
  lastStageTimes = {};
  renderJobRunning('queued', null, {});
  setButtonAbort();
  // update header automation pill
  updateAutoPill(body.repeat);
  pollInterval = setInterval(() => pollJob(data.job_id), 2000);
  logPollInterval = setInterval(() => pollLogs(data.job_id), 1500);
});

async function pollJob(jobId) {
  const s = await fetch('/status/' + jobId).then(r => r.json());
  if (s.status === 'running' || s.status === 'queued') {
    lastStageTimes = s.stage_times || {};
    renderJobRunning(s.status, s.progress, s.stage_times || {});
  } else if (s.status === 'done') {
    stopTimer();
    renderJobDone(s);
    clearInterval(pollInterval);
    clearInterval(logPollInterval);
    pollLogs(jobId, true);
    currentJobId = null;
    setButtonRun();
    loadFiles();
    loadAlerts();
    loadLoginWalls();
    // start automation countdown if repeat was enabled (timer started server-side after completion)
    refreshAutoCountdown();
  } else if (s.status === 'aborted') {
    stopTimer();
    renderJobAborted();
    clearInterval(pollInterval);
    clearInterval(logPollInterval);
    pollLogs(jobId, true);
    currentJobId = null;
    setButtonRun();
    loadFiles();
    loadAlerts();
    loadLoginWalls();
  } else if (s.status === 'error') {
    stopTimer();
    renderJobError(s.error);
    clearInterval(pollInterval);
    clearInterval(logPollInterval);
    pollLogs(jobId, true);
    currentJobId = null;
    setButtonRun();
  }
}

function renderJobRunning(status, progress, stageTimes) {
  const activeIdx = STEPS.indexOf(progress);
  const now = Date.now() / 1000; // current time in seconds (to compare with server timestamps)
  const chipHtml = STEPS.map((s, i) => {
    let cls = 'pending';
    let timeStr = '—';
    if (i < activeIdx) {
      cls = 'done';
      // duration = next stage start - this stage start
      const nextStage = STEPS[i + 1];
      const start = stageTimes[s];
      const end = stageTimes[nextStage];
      if (start && end) timeStr = formatStageTime(end - start);
    } else if (i === activeIdx) {
      cls = 'active';
      const start = stageTimes[s];
      if (start) timeStr = formatStageTime(now - start);
    }
    const displayName = s.replace(/_/g, ' ');
    return `<div class="stage-chip ${cls}">
      <div class="stage-dot"></div>
      <span class="stage-name">${displayName}</span>
      <span class="stage-time">${timeStr}</span>
    </div>`;
  }).join('<span class="stage-chevron">›</span>');

  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <span class="badge badge-running"><span class="dot pulse"></span>${status}</span>
    </div>
    <div class="stage-timeline">${chipHtml}</div>`;
}

function formatStageTime(secs) {
  if (!secs || secs < 0) return '—';
  secs = Math.floor(secs);
  if (secs < 60) return secs + 's';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m + 'm ' + s + 's';
}

function renderJobDone(s) {
  // compute final timer display
  const elapsed = timerStartTime ? Date.now() - timerStartTime : 0;
  const totalSecs = Math.floor(elapsed / 1000);
  const mins = Math.floor(totalSecs / 60);
  const secs = totalSecs % 60;
  const timerStr = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
  const errTotal = torErrors.connection + torErrors.timeout + torErrors.dead_link + torErrors.http + torErrors.other;

  // build final stage breakdown from stage_times
  const stageTimes = s.stage_times || lastStageTimes || {};
  const finishedAt = s.finished || (Date.now() / 1000);
  const stageBreakdown = STEPS.map((step, i) => {
    const start = stageTimes[step];
    if (!start) return null;
    const nextStage = STEPS[i + 1];
    const end = stageTimes[nextStage] || finishedAt;
    const dur = formatStageTime(end - start);
    const displayName = step.replace(/_/g, ' ');
    return `<div class="stage-chip done">
      <div class="stage-dot"></div>
      <span class="stage-name">${displayName}</span>
      <span class="stage-time">${dur}</span>
    </div>`;
  }).filter(Boolean).join('<span class="stage-chevron">›</span>');

  jobInfo.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <span class="badge badge-done"><span class="dot"></span>done</span>
      <span style="color:var(--muted);font-size:12px">Completed in ${timerStr}</span>
      ${errTotal > 0 ? `<span style="color:var(--danger);font-size:12px">· ${errTotal} Tor error${errTotal > 1 ? 's' : ''}</span>` : ''}
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px">
      <div class="job-stat"><div class="label">URLs Found</div><div class="value">${s.results_count || 0}</div></div>
      <div class="job-stat"><div class="label">Pages Scraped</div><div class="value">${s.scraped_count || 0}</div></div>
      <div class="job-stat"><div class="label">Duration</div><div class="value">${timerStr}</div></div>
      <div class="job-stat"><div class="label">Tor Errors</div><div class="value" style="${errTotal > 0 ? 'color:var(--danger)' : ''}">${errTotal}</div></div>
    </div>
    ${stageBreakdown ? `<div style="margin-bottom:14px"><div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--muted);margin-bottom:8px">Stage Breakdown</div><div class="stage-timeline">${stageBreakdown}</div></div>` : ''}
    ${s.summary_preview ? `<div class="summary-preview markdown-body">${typeof marked !== 'undefined' ? marked.parse(s.summary_preview) : escHtml(s.summary_preview)}</div>` : ''}
    <div id="file-analysis-section"></div>`;
  // load file analysis below summary
  loadFileAnalysis();
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
  if (name.includes('summary'))       return { displayName:'Summary',        cls:'summary',  label:'AI Summary'       };
  if (name.includes('file_analysis')) return { displayName:'File Analysis',   cls:'iocs',     label:'File Analysis'    };
  if (name.includes('ioc'))           return { displayName:'IOC Indicators',  cls:'iocs',     label:'IOC Indicators'   };
  if (name.includes('contact'))       return { displayName:'Actor Contacts',  cls:'contacts', label:'Actor Contacts'   };
  if (name.includes('scrape'))        return { displayName:'Scraped Data',    cls:'default',  label:'Scraped Data'     };
  if (name.includes('result'))        return { displayName:'Search Results',  cls:'results',  label:'Search Results'   };
  return                                     { displayName: name,             cls:'default',  label:'Report'           };
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

// ── Live log polling ─────────────────────────────────────
async function pollLogs(jobId, isFinal) {
  try {
    const res = await fetch('/logs/' + jobId + '?after=' + logLineCount);
    const data = await res.json();
    if (data.lines && data.lines.length) {
      const panel = document.getElementById('live-log');
      if (!panel) return;
      data.lines.forEach(line => {
        const div = document.createElement('div');
        div.className = 'log-line ' + classifyLogLine(line);
        div.textContent = line;
        panel.appendChild(div);
        // count Tor connection errors from log lines
        countErrorsInLine(line);
      });
      logLineCount = data.total;
      panel.scrollTop = panel.scrollHeight;
    }
    if (isFinal) {
      const panel = document.getElementById('live-log');
      if (panel) panel.classList.add('done');
    }
  } catch(e) {}
}

function classifyLogLine(line) {
  if (line.includes('[!]') || line.includes('ERROR') || line.includes('failed')) return 'error';
  if (line.includes('[*]') || line.includes('STEP')) return 'step';
  if (line.includes('[+]')) return 'info';
  if (line.includes('WARNING') || line.includes('[WARN]')) return 'warn';
  return '';
}

// ── File analysis loader ─────────────────────────────────
async function loadFileAnalysis() {
  try {
    const res = await fetch('/results/file_analysis.txt');
    if (!res.ok) return;
    const text = await res.text();
    if (!text.trim()) return;
    const section = document.getElementById('file-analysis-section');
    if (!section) return;
    section.innerHTML = `
      <div style="margin-top:16px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <div style="width:3px;height:18px;border-radius:2px;background:var(--danger);flex-shrink:0"></div>
          <h3 style="font-size:13px;font-weight:600;color:var(--text);text-transform:uppercase;letter-spacing:0.04em">File Analysis</h3>
        </div>
        <div class="summary-preview markdown-body">${typeof marked !== 'undefined' ? marked.parse(text) : '<pre>' + escHtml(text) + '</pre>'}</div>
      </div>`;
  } catch(e) {}
}

// ── Load persisted summary on page open ─────────────────
async function loadLastSummary() {
  try {
    const res = await fetch('/last-summary');
    if (!res.ok) return;
    const data = await res.json();
    if (data.summary) {
      statusDiv.style.display = 'block';
      renderJobDone({
        results_count: data.urls_found || 0,
        scraped_count: data.pages_scraped || 0,
        summary_preview: data.summary
      });
    }
  } catch(e) { /* no persisted summary */ }
}

// ── Automation settings ───────────────────────────────────
let autoCountdownInterval = null;
let autoNextRunTime = null;

async function loadAutoSettings() {
  try {
    const res = await fetch('/automation/settings');
    const data = await res.json();
    document.getElementById('auto-enabled').checked = data.enabled || false;
    document.getElementById('auto-interval').value = data.interval_hours || 6;
    document.getElementById('auto-webhook').value = data.webhook_url || '';
    updateAutoPill(data.enabled);
    if (data.enabled && data.next_run_ts) {
      autoNextRunTime = data.next_run_ts * 1000;
      startCountdown();
    }
  } catch(e) {}
}

// refresh the countdown from server (called after a run completes)
async function refreshAutoCountdown() {
  try {
    const res = await fetch('/automation/settings');
    const data = await res.json();
    updateAutoPill(data.enabled);
    if (data.enabled && data.next_run_ts) {
      autoNextRunTime = data.next_run_ts * 1000;
      startCountdown();
    } else {
      document.getElementById('auto-countdown').textContent = '—';
      if (autoCountdownInterval) clearInterval(autoCountdownInterval);
    }
  } catch(e) {}
}

function updateAutoPill(enabled) {
  const pill = document.getElementById('auto-pill');
  const text = document.getElementById('auto-pill-text');
  const dot = pill.querySelector('.status-dot-sm');
  if (enabled) {
    pill.className = 'auto-status-pill active';
    dot.classList.add('pulse');
    text.textContent = 'Automation Active';
  } else {
    pill.className = 'auto-status-pill inactive';
    dot.classList.remove('pulse');
    text.textContent = 'Automation Off';
  }
}

function startCountdown() {
  if (autoCountdownInterval) clearInterval(autoCountdownInterval);
  function tick() {
    const el = document.getElementById('auto-countdown');
    if (!autoNextRunTime) { el.textContent = '—'; return; }
    const diff = autoNextRunTime - Date.now();
    if (diff <= 0) { el.textContent = 'Running now…'; return; }
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    el.textContent = `In ${h}h ${m}m ${s}s`;
  }
  tick();
  autoCountdownInterval = setInterval(tick, 1000);
}

// ── Alerts ────────────────────────────────────────────────
async function loadAlerts() {
  try {
    const res = await fetch('/automation/alerts');
    const alerts = await res.json();
    const el = document.getElementById('alerts-list');
    const badge = document.getElementById('alert-count-badge');
    if (!alerts.length) {
      el.innerHTML = '<div class="empty-state">No alerts yet. Enable automation to start monitoring.</div>';
      badge.style.display = 'none';
      return;
    }
    badge.textContent = alerts.length + ' Total';
    badge.style.display = '';
    el.innerHTML = alerts.slice(0, 15).map(a => renderAlert(a)).join('');
  } catch(e) {}
}

function renderAlert(a) {
  const sevMap = {
    critical: { cls: 'badge-error', border: 'var(--danger)', label: 'Critical' },
    medium:   { cls: 'badge-running', border: 'var(--warning)', label: 'Medium' },
    clear:    { cls: 'badge-done', border: 'var(--success)', label: 'Clear' },
    info:     { cls: 'badge-queued', border: 'var(--muted)', label: 'Info' },
  };
  const sev = sevMap[a.severity] || sevMap.info;
  const catTag = a.category
    ? `<span class="cat-tag ${escHtml(a.category)}">${escHtml(a.category.replace(/_/g, ' '))}</span>`
    : '';
  const evidenceHtml = a.evidence
    ? `<div class="evidence-box${a.severity === 'medium' ? ' warning' : ''}">${escHtml(a.evidence)}</div>`
    : (a.severity === 'clear' ? `<div style="font-size:12px;color:var(--muted);margin-top:8px">${escHtml(a.title)}</div>` : '');
  return `
    <div class="alert-item" style="border-left:2px solid ${sev.border}">
      <div class="alert-time">${escHtml(a.timestamp)}</div>
      <div class="alert-header">
        <div class="alert-title">${catTag}${escHtml(a.title)}</div>
        <span class="badge ${sev.cls}"><span class="dot"></span>${sev.label}</span>
      </div>
      ${evidenceHtml}
    </div>`;
}

// ── Forum Accounts ────────────────────────────────────────
async function loadForumAccounts() {
  try {
    const res = await fetch('/forum/accounts');
    const accounts = await res.json();
    const el = document.getElementById('forum-accounts-list');
    if (!accounts.length) {
      el.innerHTML = '<div class="empty-state">No forum accounts stored. Add credentials above or let the scraper auto-register.</div>';
      return;
    }
    let rows = accounts.map(a => `
      <tr>
        <td style="font-family:var(--mono);font-size:12px">${escHtml(a.domain)}</td>
        <td>${escHtml(a.username)}</td>
        <td style="color:var(--muted);font-size:12px">${escHtml(a.created || '—')}</td>
        <td style="width:80px"><button class="btn btn-sm" style="color:var(--danger);border-color:rgba(239,68,68,0.3)" onclick="deleteForumAccount('${escHtml(a.domain)}')">Delete</button></td>
      </tr>`).join('');
    el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="border-bottom:1px solid var(--border);text-align:left">
        <th style="padding:8px 12px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.05em">Domain</th>
        <th style="padding:8px 12px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.05em">Username</th>
        <th style="padding:8px 12px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:0.05em">Created</th>
        <th></th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  } catch(e) {}
}

async function addForumAccount() {
  const domain = document.getElementById('forum-domain').value.trim();
  const username = document.getElementById('forum-user').value.trim();
  const password = document.getElementById('forum-pass').value.trim();
  if (!domain || !username || !password) return;
  await fetch('/forum/accounts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({domain, username, password})
  });
  document.getElementById('forum-domain').value = '';
  document.getElementById('forum-user').value = '';
  document.getElementById('forum-pass').value = '';
  loadForumAccounts();
}

async function deleteForumAccount(domain) {
  await fetch('/forum/accounts/' + encodeURIComponent(domain), {method: 'DELETE'});
  loadForumAccounts();
}

// ── Login Walls (right panel) ──────────────────────────────
async function loadLoginWalls() {
  try {
    const res = await fetch('/forum/login-walls');
    const walls = await res.json();
    const el = document.getElementById('login-walls-list');
    const pill = document.getElementById('wall-count-pill');
    if (!walls.length) {
      el.innerHTML = '<div class="empty-state">No login walls detected yet. Run a scan to discover them.</div>';
      pill.style.display = 'none';
      return;
    }
    pill.textContent = walls.length;
    pill.style.display = '';
    el.innerHTML = walls.map(w => {
      const isOk = w.status === 'auth_success';
      const badgeCls = isOk ? 'success' : 'failed';
      const badgeText = isOk ? '✓ Authenticated' : '✗ Auth Failed';
      return `
        <div class="login-wall-item">
          <div class="login-wall-url">${escHtml(w.url)}</div>
          <div class="login-wall-meta">
            <span class="login-wall-badge ${badgeCls}">${badgeText}</span>
            <span>${escHtml(w.domain || '')}</span>
            <span>·</span>
            <span>${escHtml(w.last_seen || w.first_seen || '')}</span>
          </div>
        </div>`;
    }).join('');
  } catch(e) {}
}

// Load files, last summary, automation settings, alerts, forum accounts, and login walls on page open
loadFiles();
loadLastSummary();
loadAutoSettings();
loadAlerts();
loadForumAccounts();
loadLoginWalls();
// ollama is default, load models on page load
loadOllamaModels();
</script>
</body>
</html>"""


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    return DASHBOARD_HTML.replace("__MAX_ENGINES__", str(MAX_ENGINES))


@app.route("/run", methods=["POST"])
def run_pipeline():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400

    job_id = f"job_{int(time.time())}_{os.getpid()}"
    config = {
        "use_ai":        data.get("use_ai", True),
        "ai_provider":   data.get("ai_provider", "ollama"),
        "ollama_model":  data.get("ollama_model", ""),
        "num_engines":   data.get("num_engines", MAX_ENGINES),
        "scrape_limit":  data.get("scrape_limit", 10),
        "threads":       data.get("threads", 3),
        "depth":         data.get("depth", 1),
        "max_pages":     data.get("max_pages", 1),
    }

    # handle repeat / automation params passed from the form
    repeat = data.get("repeat", False)
    interval_hours = float(data.get("interval_hours", 6))
    webhook_url = data.get("webhook_url", "")

    # persist automation settings so they survive refreshes
    auto_settings = {
        "enabled": repeat,
        "interval_hours": interval_hours,
        "webhook_url": webhook_url,
    }
    _save_auto_settings(auto_settings)

    # cancel any previously pending timer (new manual run overrides)
    _cancel_auto_timer()

    with _job_lock:
        _jobs[job_id] = {
            "status":  "queued",
            "query":   query,
            "config":  config,
            "created": time.time(),
        }

    def _run_and_maybe_repeat():
        _run_pipeline(job_id, query, config)
        # after completion, schedule next run if repeat is enabled
        if repeat:
            _schedule_next_run_after_complete(query, config)

    thread = threading.Thread(target=_run_and_maybe_repeat, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id):
    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    # exclude logs from status response (served via /logs endpoint)
    return jsonify({k: v for k, v in job.items() if k != "logs"})


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


@app.route("/logs/<job_id>")
def job_logs(job_id):
    """return log lines for a job, with pagination via ?after=N"""
    after = int(request.args.get("after", 0))
    with _job_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        logs = job.get("logs", [])
        total = len(logs)
        new_lines = logs[after:] if after < total else []
    return jsonify({"lines": new_lines, "total": total})



@app.route("/last-summary")
def last_summary():
    """return persisted summary + stats from output files if they exist"""
    summary_path = os.path.join("output", "summary.txt")
    if not os.path.isfile(summary_path):
        return jsonify({}), 204

    with open(summary_path, "r", encoding="utf-8") as f:
        summary_text = f.read()

    # try to count URLs from results.txt
    urls_found = 0
    results_path = os.path.join("output", "results.txt")
    if os.path.isfile(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("|") and not line.strip().startswith("| #") and not line.strip().startswith("|--"):
                    urls_found += 1

    # try to count scraped pages from scraped_data.txt
    pages_scraped = 0
    scraped_path = os.path.join("output", "scraped_data.txt")
    if os.path.isfile(scraped_path):
        with open(scraped_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("URL:"):
                    pages_scraped += 1

    return jsonify({
        "summary": summary_text,
        "urls_found": urls_found,
        "pages_scraped": pages_scraped
    })


@app.route("/ollama/models")
def ollama_models():
    """return available ollama models for the dropdown"""
    from ai_engine import list_ollama_models
    models = list_ollama_models()
    return jsonify({"models": models})


@app.route("/automation/settings", methods=["GET"])
def get_auto_settings():
    """return current automation settings + next_run_ts if stored"""
    settings = _load_auto_settings()
    # next_run_ts is persisted when the timer is scheduled
    return jsonify(settings)


@app.route("/automation/alerts")
def get_auto_alerts():
    """return alert history"""
    return jsonify(_load_alerts())


# ============================================================
# FORUM ACCOUNT ROUTES
# ============================================================

@app.route("/forum/accounts", methods=["GET"])
def list_forum_accounts():
    """list stored forum accounts (no passwords exposed)"""
    from forum_auth import get_account_manager
    mgr = get_account_manager()
    return jsonify(mgr.list_accounts())


@app.route("/forum/accounts", methods=["POST"])
def add_forum_account():
    """manually add a forum account"""
    from forum_auth import get_account_manager
    data = request.get_json()
    domain = data.get("domain", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not domain or not username or not password:
        return jsonify({"error": "domain, username, and password required"}), 400
    mgr = get_account_manager()
    mgr.save_account(domain, username, password)
    return jsonify({"status": "saved"})


@app.route("/forum/accounts/<path:domain>", methods=["DELETE"])
def delete_forum_account(domain):
    """remove a stored forum account"""
    from forum_auth import get_account_manager
    mgr = get_account_manager()
    if mgr.delete_account(domain):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "not found"}), 404


@app.route("/forum/login-walls")
def list_login_walls():
    """return all detected login-wall URLs with auth status"""
    from scrape import get_login_walls
    return jsonify(get_login_walls())


if __name__ == "__main__":
    # automation timer is started only when a pipeline run completes with repeat=on
    # (no automatic scheduling on startup — user must click Run Pipeline)
    app.run(host="0.0.0.0", port=5000, debug=True)
