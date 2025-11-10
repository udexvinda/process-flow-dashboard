# BPMN + KPI Dashboard (bpmn.io → GitHub → Streamlit)


A minimal, working demo that stores BPMN diagrams in GitHub, renders them in a Streamlit app using **bpmn-js**, and links BPMN elements to KPIs.


## How it works
1. Model your process in the bpmn.io web modeler or Camunda Modeler.
2. Save/export the `.bpmn` XML and commit it to this repo under `hr/`.
3. Add/maintain KPIs in `hr/hr_kpis.csv`.
4. The Streamlit app fetches both files from GitHub and renders a live diagram + KPI table.


## Deploy (Streamlit Community Cloud)
1. Push this repo to GitHub.
2. In Streamlit Cloud, click **New app** → select repo and `app.py`.
3. If your repo is private:
- In `app.py`, set `USE_GITHUB_TOKEN=True`.
- Add `GITHUB_TOKEN` under **App → Settings → Secrets**.
4. Click **Deploy**.


## Editing KPIs & Diagram
- Update `hr/hr_kpis.csv` or `hr/hr_recruitment.bpmn` and commit.
- In the app, click **Refresh** (or enable auto-refresh in sidebar).


## Tagging BPMN tasks with KPI metadata
Use `camunda:properties` under `extensionElements` with at least `kpi_key`. Example:
```xml
<bpmn:task id="Task_ScreenCandidates" name="Screen Candidates">
<bpmn:extensionElements>
<camunda:properties>
<camunda:property name="kpi_key" value="time_to_screen"/>
<camunda:property name="kpi_target" value="48h"/>
<camunda:property name="owner" value="HR Recruiting"/>
</camunda:properties>
</bpmn:extensionElements>
</bpmn:task>