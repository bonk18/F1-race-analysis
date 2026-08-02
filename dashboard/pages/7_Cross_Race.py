"""Cross-Race Analytics Dashboard Page."""

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel

st.set_page_config(page_title="Cross-Race Analytics | F1 Analytics", page_icon="🌍", layout="wide")

@st.cache_resource
def get_engine():
    return create_engine("sqlite:///data/f1_strategy.db")

@st.cache_data
def load_all_sessions():
    engine = get_engine()
    with Session(engine) as session:
        query = session.query(SessionModel, Meeting).join(
            Meeting, SessionModel.meeting_key == Meeting.meeting_key
        ).all()
        
        results = []
        for sess, meet in query:
            results.append({
                "session_key": sess.session_key,
                "meeting_name": meet.meeting_name,
                "session_name": sess.session_name,
                "date": sess.date_start,
                "circuit_key": meet.circuit_key
            })
        return pd.DataFrame(results)

@st.cache_data
def get_cross_race_metrics():
    """Load high-level metrics for all synced races from DB."""
    engine = get_engine()
    # Simple query to get average pit stop time per session
    query = """
    SELECT 
        s.session_key,
        m.meeting_name,
        COUNT(p.lap_number) as total_pit_stops,
        AVG(p.pit_duration) as avg_pit_duration
    FROM sessions s
    JOIN meetings m ON s.meeting_key = m.meeting_key
    LEFT JOIN pit_stops p ON s.session_key = p.session_key
    GROUP BY s.session_key, m.meeting_name
    """
    df_pits = pd.read_sql(query, engine)
    
    # Simple query for average pace
    pace_query = """
    SELECT 
        s.session_key,
        AVG(l.lap_duration) as avg_lap_time,
        COUNT(l.lap_number) as total_laps
    FROM sessions s
    LEFT JOIN laps l ON s.session_key = l.session_key
    WHERE l.lap_duration IS NOT NULL AND l.lap_duration > 0
    GROUP BY s.session_key
    """
    df_pace = pd.read_sql(pace_query, engine)
    
    df = pd.merge(df_pits, df_pace, on="session_key")
    return df

st.title("🌍 Cross-Race Analytics")
st.markdown("Compare high-level metrics across the entire 2024 season.")

sessions_df = load_all_sessions()
if sessions_df.empty:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

st.subheader("Synced Sessions Overview")
st.dataframe(sessions_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("Season Trends")

with st.spinner("Aggregating cross-race metrics..."):
    metrics_df = get_cross_race_metrics()
    
if metrics_df.empty:
    st.info("Insufficient data for cross-race analysis.")
    st.stop()
    
col1, col2 = st.columns(2)

with col1:
    fig_pits = px.bar(
        metrics_df, 
        x="meeting_name", 
        y="avg_pit_duration",
        title="Average Pit Lane Duration by Circuit",
        labels={"meeting_name": "Circuit", "avg_pit_duration": "Avg Pit Duration (s)"},
        color="total_pit_stops",
        color_continuous_scale="Viridis"
    )
    fig_pits.update_layout(template="plotly_dark")
    st.plotly_chart(fig_pits, use_container_width=True)
    
with col2:
    # Remove obvious outliers for pace (e.g., extremely long tracks)
    metrics_df = metrics_df[metrics_df["avg_lap_time"] < 150]
    fig_pace = px.scatter(
        metrics_df,
        x="meeting_name",
        y="avg_lap_time",
        size="total_laps",
        title="Average Lap Time by Circuit",
        labels={"meeting_name": "Circuit", "avg_lap_time": "Avg Lap Time (s)"},
        color="meeting_name"
    )
    fig_pace.update_layout(template="plotly_dark", showlegend=False)
    st.plotly_chart(fig_pace, use_container_width=True)

st.markdown("---")
st.info("To populate this page with more races, run `python -m src.ingestion.sync --year 2024 --session-type Race` to sync the full season.")
