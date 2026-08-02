"""Data Quality Dashboard Page."""

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel
from src.analytics.race_summary import RaceAnalyzer
import plotly.express as px

st.set_page_config(page_title="Data Quality | F1 Analytics", page_icon="🧹", layout="wide")

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
def load_quality_data(session_key: int):
    engine = get_engine()
    analyzer = RaceAnalyzer(engine)
    raw_data = analyzer.get_session_data(session_key)
    
    clean_result = analyzer.clean_engine.classify(
        raw_data["laps"], raw_data["stints"], raw_data["pit_stops"], raw_data["race_control"]
    )
    return clean_result

st.title("🧹 Data Quality & Lap Cleaning Report")
st.markdown("Transparency into the MAD-based lap classification engine.")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.sidebar.selectbox("Select Session", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Analyzing data quality..."):
    clean_result = load_quality_data(session_key)

summary = clean_result.summary

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Raw Laps", summary["total"])
col2.metric("Clean Laps", summary["clean"])
col3.metric("Excluded Laps", summary["excluded"])
col4.metric("Clean Percentage", f"{summary['clean_pct']}%")

st.markdown("---")

st.subheader("Exclusion Breakdown")
breakdown = summary.get("exclusion_breakdown", {})
if breakdown:
    df_breakdown = pd.DataFrame(list(breakdown.items()), columns=["Reason", "Count"]).sort_values("Count", ascending=False)
    
    fig_pie = px.pie(
        df_breakdown, 
        names="Reason", 
        values="Count", 
        title="Why Laps Were Excluded",
        hole=0.4
    )
    fig_pie.update_layout(template="plotly_dark")
    st.plotly_chart(fig_pie, use_container_width=True)
else:
    st.info("No laps were excluded.")

st.markdown("---")

st.subheader("Excluded Laps Log")
st.markdown("Detailed view of all laps that did not meet the clean-lap criteria.")
if not clean_result.excluded_laps.empty:
    display_df = clean_result.excluded_laps[[
        "driver_number", "lap_number", "lap_duration", "exclusion_reasons"
    ]].copy()
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No excluded laps to display.")
