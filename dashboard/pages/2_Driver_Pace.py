"""Driver Pace Dashboard Page."""

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel
from src.analytics.race_summary import RaceAnalyzer
import plotly.graph_objects as go

st.set_page_config(page_title="Driver Pace | F1 Analytics", page_icon="⏱️", layout="wide")

@st.cache_resource
def get_engine():
    return create_engine("sqlite:///data/f1_strategy.db")

@st.cache_data
def load_sessions():
    engine = get_engine()
    with Session(engine) as session:
        query = session.query(SessionModel, Meeting).join(
            Meeting, SessionModel.meeting_key == Meeting.meeting_key
        ).all()
        
        results = []
        for sess, meet in query:
            results.append({
                "session_key": sess.session_key,
                "label": f"{meet.meeting_name} - {sess.session_name}",
            })
        return results

@st.cache_data
def load_pace_data(session_key: int):
    engine = get_engine()
    analyzer = RaceAnalyzer(engine)
    overview = analyzer.analyze_race(session_key)
    raw_data = analyzer.get_session_data(session_key)
    clean_result = analyzer.clean_engine.classify(
        raw_data["laps"], raw_data["stints"], raw_data["pit_stops"], raw_data["race_control"]
    )
    return overview, clean_result.clean_laps

st.title("⏱️ Driver Pace & Consistency")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.sidebar.selectbox("Select Session", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Loading pace data..."):
    overview, clean_laps = load_pace_data(session_key)

if clean_laps.empty:
    st.error("No clean lap data available for this session.")
    st.stop()

# Get list of drivers
driver_kpis = {k.driver_name: k for k in overview.driver_kpis}
driver_options = sorted(list(driver_kpis.keys()))

st.sidebar.markdown("---")
selected_drivers = st.sidebar.multiselect(
    "Compare Drivers",
    options=driver_options,
    default=driver_options[:3] if len(driver_options) >= 3 else driver_options
)

if not selected_drivers:
    st.warning("Please select at least one driver.")
    st.stop()

# Filter clean laps for selected drivers
selected_laps = clean_laps[clean_laps["driver_number"].isin([driver_kpis[d].driver_number for d in selected_drivers])]
# Map driver numbers to names for plotting
num_to_name = {k.driver_number: name for name, k in driver_kpis.items()}
selected_laps = selected_laps.copy()
selected_laps["Driver"] = selected_laps["driver_number"].map(num_to_name)

# 1. Pace Boxplot
st.subheader("Lap Time Distribution (Clean Laps)")
fig_box = px.box(
    selected_laps, 
    x="Driver", 
    y="lap_duration", 
    color="Driver",
    title="Pace and Consistency Distribution",
    labels={"lap_duration": "Lap Time (s)"}
)
fig_box.update_layout(template="plotly_dark", showlegend=False)
st.plotly_chart(fig_box, use_container_width=True)

# 2. Lap Time over Race
st.subheader("Pace Evolution")
fig_line = px.scatter(
    selected_laps,
    x="lap_number",
    y="lap_duration",
    color="Driver",
    trendline="lowess",
    trendline_options=dict(frac=0.3),
    title="Lap Times over the Race (Trend)",
    labels={"lap_duration": "Lap Time (s)", "lap_number": "Lap"}
)
fig_line.update_layout(template="plotly_dark")
st.plotly_chart(fig_line, use_container_width=True)

# 3. Consistency Metrics Table
st.subheader("Consistency KPIs")
consistency_data = []
for driver in selected_drivers:
    k = driver_kpis[driver]
    consistency_data.append({
        "Driver": driver,
        "Median Pace": round(k.clean_median_pace, 3) if k.clean_median_pace else None,
        "Std Dev (σ)": round(k.consistency_std, 3) if k.consistency_std else None,
        "IQR": round(k.consistency_iqr, 3) if k.consistency_iqr else None,
        "MAD": round(k.consistency_mad, 3) if k.consistency_mad else None,
        "Within 0.5% Threshold": f"{round(k.pct_within_half_pct, 1)}%" if k.pct_within_half_pct else None,
        "Clean Laps": k.clean_lap_count
    })

df_cons = pd.DataFrame(consistency_data)
st.dataframe(df_cons, use_container_width=True, hide_index=True)
