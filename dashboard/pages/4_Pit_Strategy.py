"""Pit Strategy Dashboard Page."""

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel
from src.analytics.undercut import PitStrategyAnalyzer
from src.analytics.race_summary import RaceAnalyzer

st.set_page_config(page_title="Pit Strategy | F1 Analytics", page_icon="🛑", layout="wide")

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
def analyze_pit_strategy(session_key: int):
    engine = get_engine()
    analyzer = RaceAnalyzer(engine)
    raw_data = analyzer.get_session_data(session_key)
    clean_result = analyzer.clean_engine.classify(
        raw_data["laps"], raw_data["stints"], raw_data["pit_stops"], raw_data["race_control"]
    )
    
    pit_analyzer = PitStrategyAnalyzer(engine)
    pit_impacts = pit_analyzer.analyze_pit_stops(session_key, clean_result.clean_laps)
    return pit_impacts, raw_data["drivers"]

st.title("🛑 Pit Strategy & Execution")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.sidebar.selectbox("Select Session", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Analyzing pit strategy..."):
    pit_impacts, drivers_df = analyze_pit_strategy(session_key)

if not pit_impacts:
    st.info("No pit stops found for this session.")
    st.stop()

# Build DataFrame
pit_df = pd.DataFrame([p.__dict__ for p in pit_impacts])

# Merge driver names
driver_map = dict(zip(drivers_df["driver_number"], drivers_df["full_name"]))
pit_df["Driver"] = pit_df["driver_number"].map(driver_map)

# 1. Pit Lane Time Loss
st.subheader("Pit Lane Time Loss")
st.markdown("Total time spent in the pit lane (lane duration + stop duration).")

fig_pit = px.box(
    pit_df,
    x="Driver",
    y="pit_duration",
    color="Driver",
    title="Pit Lane Time Distribution",
    labels={"pit_duration": "Time in Pit Lane (s)"}
)
fig_pit.update_layout(template="plotly_dark", showlegend=False)
st.plotly_chart(fig_pit, use_container_width=True)

st.markdown("---")

# 2. Post-Stop Pace Gain
st.subheader("Post-Stop Pace Improvement")
st.markdown("Compares the median pace 3 laps before the stop to 3 laps after.")

pace_df = pit_df.dropna(subset=["pace_gain"]).copy()
if not pace_df.empty:
    pace_df["Gain Category"] = pd.cut(
        pace_df["pace_gain"], 
        bins=[-float("inf"), -1.0, 0.0, 1.0, float("inf")],
        labels=["Large Loss", "Slight Loss", "Slight Gain", "Large Gain"]
    )
    
    fig_pace = px.histogram(
        pace_df,
        x="pace_gain",
        color="Gain Category",
        title="Distribution of Pace Gains After Pit Stop",
        labels={"pace_gain": "Pace Gain (s) [Positive = Faster]"},
        nbins=20
    )
    fig_pace.update_layout(template="plotly_dark")
    st.plotly_chart(fig_pace, use_container_width=True)
else:
    st.warning("Not enough clean laps before/after stops to compute pace gain.")

# 3. Pit Stops Table
st.subheader("All Pit Stops Log")
display_df = pit_df[[
    "lap_number", "Driver", "compound_before", "compound_after", 
    "tyre_age_before", "pit_duration", "pace_gain"
]].sort_values("lap_number")

display_df["pit_duration"] = display_df["pit_duration"].round(2)
display_df["pace_gain"] = display_df["pace_gain"].round(3)

st.dataframe(display_df, use_container_width=True, hide_index=True)
