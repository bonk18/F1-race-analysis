"""Tyre Degradation Dashboard Page."""

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel
from src.analytics.race_summary import RaceAnalyzer
import numpy as np

st.set_page_config(page_title="Tyre Degradation | F1 Analytics", page_icon="🛞", layout="wide")

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
def load_stint_data(session_key: int):
    engine = get_engine()
    analyzer = RaceAnalyzer(engine)
    raw_data = analyzer.get_session_data(session_key)
    clean_result = analyzer.clean_engine.classify(
        raw_data["laps"], raw_data["stints"], raw_data["pit_stops"], raw_data["race_control"]
    )
    
    stints = analyzer.analyze_stints(
        session_key, 
        clean_result.clean_laps, 
        raw_data["stints"], 
        raw_data["drivers"]
    )
    return stints, clean_result.clean_laps, raw_data["stints"]

st.title("🛞 Tyre Degradation Analysis")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.sidebar.selectbox("Select Session", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Loading stint data..."):
    stints, clean_laps, raw_stints = load_stint_data(session_key)

if not stints:
    st.error("No stint data available.")
    st.stop()

# Convert stints to DataFrame for easier visualization
stint_df = pd.DataFrame([s.__dict__ for s in stints])
stint_df = stint_df[stint_df["compound"].notna()]
stint_df = stint_df[stint_df["clean_lap_count"] >= 5] # Only meaningful stints

if stint_df.empty:
    st.warning("No significant stint data (>= 5 laps) available to analyze.")
    st.stop()

st.subheader("Compound Degradation Rates")
st.markdown("Distribution of tyre degradation rates (sec/lap) across all drivers, grouped by compound.")

# Color mapping for compounds
compound_colors = {
    "SOFT": "#ff1801",
    "MEDIUM": "#eadd13",
    "HARD": "#ffffff",
    "INTERMEDIATE": "#43b02a",
    "WET": "#0066cc",
    "UNKNOWN": "#808080"
}

fig_deg = px.box(
    stint_df,
    x="compound",
    y="degradation_rate",
    color="compound",
    color_discrete_map=compound_colors,
    points="all",
    hover_data=["driver_name", "stint_number", "clean_lap_count"],
    title="Degradation Rate by Compound (Lower is Better)"
)
fig_deg.update_layout(template="plotly_dark")
st.plotly_chart(fig_deg, use_container_width=True)

st.markdown("---")

st.subheader("Detailed Stint Analysis")

selected_compound = st.selectbox("Filter by Compound", options=["ALL"] + list(stint_df["compound"].unique()))

view_df = stint_df.copy()
if selected_compound != "ALL":
    view_df = view_df[view_df["compound"] == selected_compound]

# Show top 10 longest stints
st.markdown(f"**Top 10 Longest Stints ({selected_compound})**")
longest = view_df.sort_values("clean_lap_count", ascending=False).head(10)

display_df = longest[[
    "driver_name", "stint_number", "compound", "clean_lap_count", 
    "median_pace", "degradation_rate"
]].copy()

# Format columns
display_df["median_pace"] = display_df["median_pace"].round(3)
display_df["degradation_rate"] = display_df["degradation_rate"].round(4)

st.dataframe(display_df, use_container_width=True, hide_index=True)
