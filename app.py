# app.py
# Streamlit app: Browse BPMN files in your GitHub repo (Folder -> BPMN),
# render with bpmn-js, and manage KPIs (CSV). Optional: use OpenAI to
# propose KPIs and download a ready CSV to commit back to the repo.

import io
import json
import time
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from xml.etree import ElementTree as ET

# ------------------ PAGE SETUP ------------------
st.set_page_config(page_title="BPMN + KPI Dashboard", page_icon="🧭", layout="wide")
st.markdown(
    """
<style>
/* tighten vertical gaps a bit */
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
section.main > div { margin-top: 0.5rem; margin-bottom: 0.5rem; }
/* tighten gap under the viewer */
#canvas { margin-bottom: 0.5rem !important; }
</style>
""",
    unsafe_allow_html=True,
)

# ------------------ CONFIG ------------------
# Set these to your repo
REPO_USER = "udexvinda"               # <-- change if needed
REPO_NAME = "process-flow-dashboard"  # <-- change if needed
BRANCH = "main"                       # "main" unless you use another branch

# Private repo? Set True and put GITHUB_TOKEN in Streamlit Secrets
USE_GITHUB_TOKEN = False

# Default list of folders to show if dynamic listing fails (optional)
DEFAULT_FOLDERS = ["hr", "finance", "claims"]

# Auto-refresh seconds (0 = off)
AUTO_REFRESH_SECONDS = st.sidebar.number_input(
    "Auto-refresh (seconds, 0=off)", min_value=0, max_value=600, value=0, step=5
)

# ------------------ GITHUB HELPERS ------------------
def _auth_headers_json():
    """Auth + JSON headers for GitHub API/raw calls."""
    h = {"Accept": "application/vnd.github+json"}
    if USE_GITHUB_TOKEN:
        tok = st.secrets.get("GITHUB_TOKEN")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
    return h

def gh_contents(path=""):
    """
    List files/folders in a path using GitHub Contents API.
    Returns list[dict] with keys: name, path, type ('file'|'dir'), download_url, etc.
    """
    api = f"https://api.github.com/repos/{REPO_USER}/{REPO_NAME}/contents/{path}?ref={quote(BRANCH)}"
    r = requests.get(api, headers=_auth_headers_json(), timeout=20)
    r.raise_for_status()
    return r.json()

def list_folders_at_root():
    """Return directory names at repo root (fallback to DEFAULT_FOLDERS on error)."""
    try:
        items = gh_contents("")  # root
        return [it["name"] for it in items if it.get("type") == "dir"]
    except Exception:
        return DEFAULT_FOLDERS

def raw_url(path):
    return f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}/{path}"

def head_exists(url):
    r = requests.head(url, headers=_auth_headers_json(), timeout=15)
    return r.status_code == 200

# ------------------ LOADERS (CACHED) ------------------
@st.cache_data(ttl=60)
def load_text(url: str) -> str:
    r = requests.get(url, headers=_auth_headers_json(), timeout=20)
    r.raise_for_status()
    return r.text

@st.cache_data(ttl=60)
def load_csv_safe(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=_auth_headers_json(), timeout=20)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))

# ------------------ BPMN PARSER ------------------
def parse_kpi_properties(bpmn_xml: str) -> pd.DataFrame:
    """
    Extract camunda:properties (kpi_key, kpi_target, owner) from BPMN elements.
    """
    ns = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        "camunda": "http://camunda.org/schema/1.0/bpmn",
    }
    root = ET.fromstring(bpmn_xml.encode("utf-8"))
    rows = []
    for el in root.findall(".//bpmn:process//*[@id]", ns):
        el_id = el.attrib.get("id", "")
        # name may be in default ns or explicitly prefixed; cover both
        el_name = el.attrib.get("name") or el.attrib.get(
            "{http://www.omg.org/spec/BPMN/20100524/MODEL}name", ""
        )
        props = {}
        for p in el.findall(".//camunda:property", ns):
            props[p.attrib.get("name", "")] = p.attrib.get("value", "")
        if props:
            rows.append(
                {
                    "element_id": el_id,
                    "element_name": el_name,
                    "kpi_key": props.get("kpi_key", ""),
                    "kpi_target": props.get("kpi_target", ""),
                    "owner": props.get("owner", ""),
                }
            )
    return pd.DataFrame(rows)

def extract_named_tasks(bpmn_xml: str) -> list:
    """Get all element names (tasks/events/gateways with a name), deduped."""
    ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
    root = ET.fromstring(bpmn_xml.encode("utf-8"))
    names = []
    for el in root.findall(".//bpmn:process//*[@id]", ns):
        nm = el.attrib.get("name") or el.attrib.get(
            "{http://www.omg.org/spec/BPMN/20100524/MODEL}name"
        )
        if nm:
            names.append(nm)
    # dedupe preserving order
    seen, out = set(), []
    for n in names:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out

# ------------------ SIDEBAR: SOURCE PICKER ------------------
st.sidebar.header("Diagram Source")

# Folder selector (dynamic from repo root)
folders = list_folders_at_root()
if not folders:
    st.sidebar.error("No folders found at repo root.")
    st.stop()

folder = st.sidebar.selectbox("Folder", folders, index=folders.index("hr") if "hr" in folders else 0)

# List .bpmn files in selected folder
bpmn_files = []
list_err = None
try:
    items = gh_contents(folder)
    bpmn_files = [it["name"] for it in items if it.get("type") == "file" and it["name"].lower().endswith(".bpmn")]
except Exception as e:
    list_err = str(e)

if list_err:
    st.sidebar.error(f"List error: {list_err}")
    st.stop()

if not bpmn_files:
    st.sidebar.warning("No .bpmn files found in this folder.")
    st.stop()

bpmn_name = st.sidebar.selectbox("BPMN file", bpmn_files, index=0)

# Compute paths and conventional KPI CSV name
BPMN_PATH = f"{folder}/{bpmn_name}"
base = bpmn_name.rsplit(".", 1)[0]
KPI_PATH = f"{folder}/{base}_kpis.csv"

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()

# ------------------ LOAD SELECTED FILES ------------------
try:
    bpmn_xml = load_text(raw_url(BPMN_PATH))
except Exception as e:
    st.error(f"Failed to load BPMN: {e}")
    st.stop()

csv_url = raw_url(KPI_PATH)
kpis_df = None
if head_exists(csv_url):
    try:
        kpis_df = load_csv_safe(csv_url)
    except Exception as e:
        st.warning(f"Found KPI CSV but could not load: {e}")

# ------------------ TITLE ------------------
st.title("HR Recruitment — BPMN + KPI Monitor")

# ------------------ RENDER DIAGRAM ------------------
st.subheader("Process Diagram")
bpmn_html = f"""
<div id="canvas" style="height:50vh;border:1px solid #ddd;border-radius:8px;"></div>
<script src="https://unpkg.com/bpmn-js@10.2.1/dist/bpmn-viewer.production.min.js"></script>
<script>
  const viewer = new BpmnJS({{ container: '#canvas' }});
  const xml = {json.dumps(bpmn_xml)};
  viewer.importXML(xml).then(() => {{
    const canvas = viewer.get('canvas');
    canvas.zoom('fit-viewport');
  }}).catch((err) => {{
    const pre = document.createElement('pre'); pre.textContent = (err && err.message) ? err.message : err;
    document.body.appendChild(pre);
  }});
</script>
"""
st.components.v1.html(bpmn_html, height=420, scrolling=True)

# ------------------ KPI TABLE ------------------
st.subheader("KPI Mapping")
map_df = parse_kpi_properties(bpmn_xml)

if kpis_df is not None:
    st.caption("Loaded from existing CSV in repo.")
    st.dataframe(kpis_df, use_container_width=True)
elif not map_df.empty:
    st.caption("No CSV found. Showing BPMN element → KPI tags (from camunda:properties).")
    st.dataframe(map_df, use_container_width=True)
else:
    st.info(
        "No KPI CSV and no KPI tags in BPMN. Use **Generate KPIs with AI** below, "
        "or add camunda:properties with kpi_key to tasks."
    )

# ------------------ AI KPI SUGGESTION ------------------
with st.expander("✨ Generate KPIs with AI", expanded=False):
    st.write(
        "Extracts task names from the BPMN and asks an LLM to propose KPIs. "
        "Download the CSV and commit it to the **same folder** in GitHub. "
        "On next load, the app will auto-detect and display it."
    )
    # API key input (fallback to secrets). We don't store the typed key.
    default_key = st.secrets.get("OPENAI_API_KEY", "")
    key_placeholder = "••••••" if default_key else ""
    api_key = st.text_input("OpenAI API Key", value=key_placeholder, type="password", help="Use Secrets in prod.")
    use_secret = (api_key == "••••••" and default_key)

    st.caption("CSV columns: kpi_key, current_value, target_value, last_updated (YYYY-MM-DD)")

    if st.button("Generate KPIs from BPMN"):
        try:
            tasks = extract_named_tasks(bpmn_xml)
            if not tasks:
                st.warning("No named tasks found in BPMN.")
            else:
                from openai import OpenAI
                client = OpenAI(api_key=(default_key if use_secret else (api_key if api_key and api_key != "••••••" else None)))

                prompt = f"""
You are a BPM KPI designer. Given this process's task names, propose 6-12 KPI rows as CSV with columns:
kpi_key (snake_case), current_value (guess if unknown), target_value (reasonable goal),
last_updated (YYYY-MM-DD). Only output CSV rows, no commentary.

Tasks:
{json.dumps(tasks, ensure_ascii=False)}
"""
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                csv_text = resp.choices[0].message.content.strip()

                # best-effort CSV parse
                gen_df = pd.read_csv(io.StringIO(csv_text))
                st.success("Proposed KPI table generated.")
                st.dataframe(gen_df, use_container_width=True)

                dl_name = f"{base}_kpis.csv"
                st.download_button(
                    "⬇️ Download KPIs CSV",
                    data=gen_df.to_csv(index=False).encode("utf-8"),
                    file_name=dl_name,
                    mime="text/csv",
                )

                st.info(
                    f"Upload `{dl_name}` to your repo at `{folder}/` (same folder as `{bpmn_name}`). "
                    "On the next load, the app will detect and display it automatically."
                )
        except Exception as e:
            st.error(f"AI generation failed: {e}")

# ------------------ EXPLAINER ------------------
with st.expander("How this works"):
    st.markdown(
        """
- **Source of truth**: App reads BPMN XML + KPI CSV from your GitHub repo (selected Folder → BPMN file).
- **KPI CSV name**: `<bpmn_file_name>_kpis.csv` in the **same folder** (e.g., `hr/hr_recruitment_kpis.csv`).
- **Binding rule**: If no CSV exists, tasks/events with `camunda:properties` containing `kpi_key` are shown.
- **Update flow**: Commit a new `.bpmn` or CSV → click **Refresh now** (or use auto-refresh).
- **Private repos**: Set `USE_GITHUB_TOKEN=True` and add **GITHUB_TOKEN** in *Secrets*.
- **AI**: If you add **OPENAI_API_KEY** in *Secrets*, you won't need to paste the key here.
"""
    )

# ------------------ AUTO-REFRESH ------------------
if AUTO_REFRESH_SECONDS:
    st.markdown(f"_Auto-refreshing every **{AUTO_REFRESH_SECONDS}s** (change in the sidebar to disable)._")
    # Sleep at the very end, then rerun
    time.sleep(AUTO_REFRESH_SECONDS)
    st.rerun()

