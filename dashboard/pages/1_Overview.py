"""Race Overview Dashboard Page."""

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from src.analytics.race_summary import RaceAnalyzer
from src.database.models import Meeting, Session as SessionModel
from sqlalchemy.orm import Session

st.set_page_config(page_title="Overview | F1 Analytics", page_icon="📊", layout="wide")

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
def analyze_race(session_key: int):
    engine = get_engine()
    analyzer = RaceAnalyzer(engine)
    return analyzer.analyze_race(session_key)

st.title("📊 Race Overview")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.selectbox("Select Session", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Analyzing race data..."):
    overview = analyze_race(session_key)

if overview.total_laps == 0:
    st.error("No lap data available for this session.")
    st.stop()

# Key Metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Circuit", overview.circuit)
col2.metric("Total Laps", overview.total_laps)
col3.metric("Drivers", overview.driver_count)
if overview.weather_summary.get("available"):
    air_temps = overview.weather_summary.get("air_temp_range", [0, 0])
    col4.metric("Air Temp", f"{air_temps[0]} - {air_temps[1]} °C")
else:
    col4.metric("Weather", "N/A")

st.markdown("---")

# Takeaways
st.subheader("💡 Key Takeaways")
for t in overview.takeaways:
    st.markdown(f"- {t}")

st.markdown("---")

# Podium & Movers
col1, col2 = st.columns(2)

with col1:
    st.subheader("🏆 Podium")
    for p in overview.podium:
        st.markdown(f"**P{p['position']}**: {p['driver']} ({p['team']})")

with col2:
    st.subheader("📈 Biggest Movers")
    for m in overview.largest_gainers:
        st.markdown(f"**+{m['gained']}**: {m['driver']} ({m['team']})")

st.markdown("---")

# Detailed Driver KPIs Table
st.subheader("🏁 Driver KPIs")
kpi_data = []
for k in overview.driver_kpis:
    kpi_data.append({
        "Position": k.finish_position,
        "Driver": k.driver_name,
        "Team": k.team_name,
        "Started": k.grid_position,
        "Gained": k.positions_gained,
        "Median Pace": round(k.clean_median_pace, 3) if k.clean_median_pace else None,
        "Pace vs Teammate": round(k.pace_deficit_to_teammate, 3) if k.pace_deficit_to_teammate else None,
        "Consistency (MAD)": round(k.consistency_mad, 3) if k.consistency_mad else None,
        "Pits": k.pit_count,
    })

df = pd.DataFrame(kpi_data).sort_values("Position")
st.dataframe(df, use_container_width=True, hide_index=True)
