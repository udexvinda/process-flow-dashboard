import io
import html
import requests
import pandas as pd
import streamlit as st
from xml.etree import ElementTree as ET

st.set_page_config(
    page_title="HR BPMN + KPI Dashboard",
    page_icon="🧭",
    layout="wide",
)

# ------------------ CONFIG ------------------
# Public raw URLs (easy path). If your repo is private, set USE_GITHUB_TOKEN=True and put a token in st.secrets.
REPO_USER = "udexvinda"
REPO_NAME = "process-flow-dashboard"  # e.g., hr-bpmn-kpi-demo
BRANCH = "main"
BPMN_PATH = "hr/hr_recruitment.bpmn"
KPI_PATH = "hr/hr_kpis.csv"

USE_GITHUB_TOKEN = False  # set True if your repo is private
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_USER}/{REPO_NAME}/{BRANCH}"
GITHUB_RAW_BPMN = f"{RAW_BASE}/{BPMN_PATH}"
GITHUB_RAW_KPIS = f"{RAW_BASE}/{KPI_PATH}"

REQUEST_TIMEOUT = 20
AUTO_REFRESH_SECONDS = st.sidebar.number_input(
    "Auto-refresh (seconds, 0=off)", min_value=0, max_value=600, value=0, step=5
)

# ------------------ HELPERS ------------------

def _auth_headers():
    if USE_GITHUB_TOKEN:
        token = st.secrets.get("GITHUB_TOKEN", None)
        if not token:
            st.warning("Private repo selected but no GITHUB_TOKEN in secrets.")
        return {"Authorization": f"token {token}"} if token else None
    return None

@st.cache_data(ttl=60)
def load_text(url: str):
    r = requests.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text

@st.cache_data(ttl=60)
def load_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def parse_kpi_properties(bpmn_xml: str) -> pd.DataFrame:
    ns = {
        'bpmn': "http://www.omg.org/spec/BPMN/20100524/MODEL",
        'bpmndi': "http://www.omg.org/spec/BPMN/20100524/DI",
        'dc': "http://www.omg.org/spec/DD/20100524/DC",
        'di': "http://www.omg.org/spec/DD/20100524/DI",
        'camunda': "http://camunda.org/schema/1.0/bpmn"
    }
    root = ET.fromstring(bpmn_xml.encode('utf-8'))
    rows = []
    for el in root.findall(".//bpmn:process//*[@id]", ns):
        el_id = el.attrib.get("id", "")
        # name may be in default ns or explicitly prefixed; cover both
        el_name = el.attrib.get("name") or el.attrib.get("{http://www.omg.org/spec/BPMN/20100524/MODEL}name", "")
        props = {}
        for p in el.findall(".//camunda:property", ns):
            props[p.attrib.get("name", "")] = p.attrib.get("value", "")
        if props:
            rows.append({
                "element_id": el_id,
                "element_name": el_name,
                "kpi_key": props.get("kpi_key", ""),
                "kpi_target": props.get("kpi_target", ""),
                "owner": props.get("owner", ""),
            })
    return pd.DataFrame(rows)

# ------------------ UI ------------------
st.title("HR Recruitment — BPMN + KPI Monitor")
with st.sidebar:
    st.header("Diagram Source")
    st.write("**Repo:** ", f"{REPO_USER}/{REPO_NAME}@{BRANCH}")
    st.write("**BPMN:** ", BPMN_PATH)
    st.write("**KPIs:** ", KPI_PATH)
    refresh = st.button("🔄 Refresh now")

if AUTO_REFRESH_SECONDS:
    st.experimental_set_query_params(_=pd.Timestamp.utcnow().value)  # avoid caching by URL
    st.autorefresh = st.empty()
    st.autorefresh.write(
        f"Auto-refreshing every {AUTO_REFRESH_SECONDS}s (change in the sidebar to disable)."
    )
    st.experimental_rerun  # hint for Streamlit Cloud

if refresh:
    st.cache_data.clear()

# ------------------ LOAD DATA ------------------
try:
    bpmn_xml = load_text(GITHUB_RAW_BPMN)
    kpis_df = load_csv(GITHUB_RAW_KPIS)
    map_df = parse_kpi_properties(bpmn_xml)
except Exception as e:
    st.error(f"Load error: {e}")
    st.stop()

# ------------------ RENDER DIAGRAM ------------------
st.subheader("Process Diagram")

bpmn_html = f"""
<div id=\"canvas\" style=\"height:65vh;border:1px solid #ddd;border-radius:8px;\"></div>
<script src=\"https://unpkg.com/bpmn-js@10.2.1/dist/bpmn-viewer.production.min.js\"></script>
<script>
  const viewer = new BpmnJS({{ container: '#canvas' }});
  const xml = `{html.escape(bpmn_xml)}`;
  viewer.importXML(xml).then(() => {{
    const canvas = viewer.get('canvas');
    canvas.zoom('fit-viewport');
  }}).catch((err) => {{
    const pre = document.createElement('pre'); pre.textContent = err?.message || err;
    document.body.appendChild(pre);
  }});
</script>
"""

st.components.v1.html(bpmn_html, height=520, scrolling=True)

# ------------------ KPI TABLE ------------------
st.subheader("KPI Mapping")
if map_df.empty:
    st.info("No KPI tags found in the BPMN. Add camunda:properties to tasks/events to link KPIs.")
else:
    # Merge on kpi_key if present; handle missing column gracefully
    if 'kpi_key' in kpis_df.columns:
        merged = map_df.merge(kpis_df, how="left", on="kpi_key")
    else:
        merged = map_df.copy()
    st.dataframe(merged, use_container_width=True)

# ------------------ HINTS ------------------
with st.expander("How this works"):
    st.markdown(
        """
        - **Source of truth**: This app reads the BPMN XML and KPI CSV from your GitHub repo.
        - **Binding rule**: Tasks/events that include `camunda:properties` with a `kpi_key` are shown in the table.
        - **Update flow**: Commit a new `.bpmn` or `hr_kpis.csv` → click **Refresh** → dashboard updates.
        - **Private repos**: Set `USE_GITHUB_TOKEN=True` and add `GITHUB_TOKEN` in **secrets**.
        """
    )
