import os
import threading
import time
from queue import Empty, Queue

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app_helpers import missing_settings, role_model_table, size_label, stages_for  # noqa: E402
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
    st.table([{"Role": r["label"], "Model": r["model"], "Temp": r["temperature"]} for r in role_model_table(os.environ, pdf)])
    st.subheader("Worker")
    health = WorkerClient(worker_url, timeout=3).health()
    if health.get("ok"):
        st.success("Docker worker is running")
    else:
        st.warning("Docker worker not reachable. Page reading and PDF output will be limited. Start it with `docker compose up -d`.")

problems = missing_settings(os.environ)
if problems:
    st.error("Missing settings in .env: " + ", ".join(problems))
    st.stop()

topic = st.text_input("Research topic", placeholder="e.g. Defect mechanisms in GaN power devices", disabled="job" in st.session_state)
job = st.session_state.get("job")

if job is None:
    if st.button("Run research", type="primary", disabled=not topic.strip()):
        events: Queue = Queue()
        cancel = threading.Event()
        box: dict = {}
        forced = None if depth == "Auto" else int(depth[0])

        def work(topic=topic, pdf=pdf, size=size, forced=forced):
            try:
                flow = ResearchFlow(
                    topic, pdf=pdf, size=size, forced_tier=forced, cancel=cancel,
                    on_stage=lambda s, state: events.put((s, state)),
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
            "done": 0, "current": "route", "stopping": False,
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
        st.info(STAGE_LABELS.get(job["current"], job["current"]) + "...")
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
    report_tab, sources_tab, notes_tab = st.tabs(["Report", "Sources", "Coverage notes"])
    md = result.markdown_path.read_text(encoding="utf-8")
    with report_tab:
        st.caption(f"{result.words:,} words · run folder: {result.run_dir}")
        st.markdown(md)
        st.download_button("Download Markdown", md, file_name=result.markdown_path.name, mime="text/markdown")
        if result.pdf_path:
            st.download_button("Download PDF", result.pdf_path.read_bytes(), file_name=result.pdf_path.name, mime="application/pdf")
    with sources_tab:
        sources_file = result.run_dir / "sources.json"
        if sources_file.exists():
            import json

            for s in json.loads(sources_file.read_text(encoding="utf-8")):
                st.markdown(f"**[{s['id']}]** [{s['title']}]({s['url']}) — {s['kind']}")
    with notes_tab:
        if result.notes:
            for n in result.notes:
                st.markdown(f"- {n}")
        else:
            st.write("No coverage issues.")
