import os
import threading
import time
from queue import Empty, Queue

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app_helpers import (  # noqa: E402
    ProgressTracker, list_runs, load_run, missing_settings, role_model_table, size_label, stages_for,
)
from core.config import SIZE_PRESETS  # noqa: E402
from flows.research_flow import ResearchCancelled, ResearchFlow  # noqa: E402
from tools.worker_client import WorkerClient  # noqa: E402

STAGE_LABELS = {
    "route": "Planning the search",
    "research": "Researching",
    "analyse": "Analysing",
    "figures": "Building charts and diagrams",
    "write": "Writing the report",
    "render": "Rendering the PDF",
}

st.set_page_config(page_title="Multi-Agent Research Assistant", page_icon="🔎", layout="wide")
st.title("Multi-Agent Research Assistant")

worker_url = os.getenv("WORKER_URL", "http://localhost:8000")
with st.sidebar:
    st.header("Settings")
    pdf = st.checkbox("Professional PDF report", value=False, help="Adds tables, charts and diagrams. Needs the Docker worker.")
    size = st.selectbox("Report size", list(SIZE_PRESETS), index=1, format_func=size_label)
    depth = st.selectbox("Search depth", ["Auto", "0 - Quick", "1 - Standard", "2 - Technical", "3 - Deep"], index=0)
    st.subheader("Models")
    st.table([
        {"Role": r["label"], "Tier": r["tier"], "Model": r["model"], "Temp": r["temperature"]}
        for r in role_model_table(os.environ, pdf)
    ])
    st.subheader("Worker")
    health = WorkerClient(worker_url, timeout=3).health()
    if health.get("ok"):
        st.success("Docker worker is running")
    else:
        st.warning("Docker worker not reachable. Page reading and PDF output will be limited. Start it with `docker compose up -d`.")
    st.subheader("Past runs")
    past = list_runs("runs")
    if past:
        picked = st.selectbox("Open a finished report", [r["label"] for r in past], index=None,
                              placeholder=f"{len(past)} saved reports", label_visibility="collapsed")
        if st.button("Open report", disabled=picked is None or "job" in st.session_state):
            run_dir = next(r["dir"] for r in past if r["label"] == picked)
            st.session_state["result"] = load_run(run_dir)
            st.session_state.pop("notice", None)
            st.rerun()
    else:
        st.caption("Finished reports will appear here.")

problems = missing_settings(os.environ)
if problems:
    st.error("Missing settings in .env: " + ", ".join(problems))
    st.stop()

topic = st.text_input("Research topic", placeholder="e.g. Defect mechanisms in GaN power devices", disabled="job" in st.session_state)
job = st.session_state.get("job")

# Drawn in both states, disabled while a run is going. While running, the script re-runs every
# second and never finishes a pass, so a button drawn only when idle lingers on screen as a stale copy.
clicked = st.button("Run research", type="primary", disabled=job is not None or not topic.strip())
if job is None:
    if clicked:
        events: Queue = Queue()
        cancel = threading.Event()
        box: dict = {}
        forced = None if depth == "Auto" else int(depth[0])

        def work(topic=topic, pdf=pdf, size=size, forced=forced):
            try:
                flow = ResearchFlow(
                    topic, pdf=pdf, size=size, forced_tier=forced, cancel=cancel,
                    on_stage=lambda s, state: events.put((s, state)),
                    on_event=lambda record: events.put(record),
                )
                box["result"] = flow.run()
            except ResearchCancelled as exc:
                box["cancelled"] = exc
            except Exception as exc:  # shown in the UI
                box["error"] = exc
            events.put(None)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        st.session_state["job"] = {
            "events": events, "cancel": cancel, "box": box, "stages": stages_for(pdf),
            "done": 0, "current": "route", "stopping": False, "progress": ProgressTracker(),
            "started": time.monotonic(),
        }
        st.session_state.pop("result", None)
        st.session_state.pop("notice", None)
        st.rerun()
else:
    finished = False
    try:
        while True:
            item = job["events"].get_nowait()
            if item is None:
                finished = True
                break
            if isinstance(item, dict):  # a log record: update the detail line
                job["progress"].update(item)
                continue
            stage, state = item
            if state == "start":
                job["current"] = stage
            else:
                job["done"] += 1
    except Empty:
        pass
    if finished:
        box = job["box"]
        if "error" in box:
            st.session_state["notice"] = ("error", f"Run failed: {box['error']}")
        elif "cancelled" in box:
            folder = box["cancelled"].run_dir
            where = f" Partial work is in {folder}." if folder else ""
            st.session_state["notice"] = ("warning", "Run stopped." + where)
        else:
            st.session_state["result"] = box["result"]
        del st.session_state["job"]
        st.rerun()
    st.progress(min(job["done"] / len(job["stages"]), 1.0))
    if job["stopping"]:
        st.warning("Stopping... the current model call has to finish first, which can take a minute.")
    else:
        elapsed = int(time.monotonic() - job["started"])
        st.info(f"{STAGE_LABELS.get(job['current'], job['current'])}...  ({elapsed // 60}:{elapsed % 60:02d})")
        if job["progress"].line and job["current"] == "research":
            st.caption(job["progress"].line)
        if st.button("Stop", type="secondary"):
            job["cancel"].set()
            job["stopping"] = True
            st.rerun()
    time.sleep(1)
    st.rerun()

notice = st.session_state.get("notice")
if notice:
    getattr(st, notice[0])(notice[1])

result = st.session_state.get("result")
if result:
    with st.expander("Research plan", expanded=False):
        st.json(result.plan.model_dump())
    tab_names = ["Report"] + (["PDF"] if result.pdf_path else []) + ["Sources", "Coverage notes"]
    tabs = dict(zip(tab_names, st.tabs(tab_names)))
    report_tab, sources_tab, notes_tab = tabs["Report"], tabs["Sources"], tabs["Coverage notes"]
    md = result.markdown_path.read_text(encoding="utf-8")
    with report_tab:
        usage = (result.usage or {}).get("summary")
        st.caption(f"{result.words:,} words" + (f" · {usage}" if usage else "") + f" · run folder: {result.run_dir}")
        st.markdown(md)
        st.download_button("Download Markdown", md, file_name=result.markdown_path.name, mime="text/markdown")
        if result.pdf_path:
            st.download_button("Download PDF", result.pdf_path.read_bytes(), file_name=result.pdf_path.name, mime="application/pdf")
    if "PDF" in tabs:
        with tabs["PDF"]:
            try:
                st.pdf(result.pdf_path.read_bytes(), height=900)
            except Exception:  # the viewer needs streamlit[pdf]; the download button still works
                st.info("The inline viewer is unavailable here; use Download PDF on the Report tab.")
    with sources_tab:
        sources_file = result.run_dir / "sources.json"
        if sources_file.exists():
            import json

            from core.registry import _DEPTH_LABEL

            for s in json.loads(sources_file.read_text(encoding="utf-8")):
                depth = _DEPTH_LABEL.get(s.get("depth") or "")
                st.markdown(f"**[{s['id']}]** [{s['title']}]({s['url']}) — {s['kind']}" + (f", {depth}" if depth else ""))
    with notes_tab:
        if result.notes:
            for n in result.notes:
                st.markdown(f"- {n}")
        else:
            st.write("No coverage issues.")
