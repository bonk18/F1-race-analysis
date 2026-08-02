"""Strategy Explorer Dashboard Page."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.database.models import Meeting, Session as SessionModel
from src.models.strategy_explorer import StrategyExplorer

st.set_page_config(page_title="Strategy Explorer | F1 Analytics", page_icon="🔮", layout="wide")

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

@st.cache_resource
def get_trained_explorer(session_key: int):
    engine = get_engine()
    explorer = StrategyExplorer(engine)
    explorer.train_models(session_key)
    return explorer

st.title("🔮 Counterfactual Strategy Explorer")
st.markdown("Use trained LightGBM models to predict race outcomes under different pit stop strategies.")

sessions = load_sessions()
if not sessions:
    st.warning("No sessions found in database. Please run the sync script.")
    st.stop()

session_options = {s["label"]: s["session_key"] for s in sessions}
selected_label = st.sidebar.selectbox("Select Session for Training", options=list(session_options.keys()))
session_key = session_options[selected_label]

with st.spinner("Training simulation models (LightGBM)..."):
    try:
        explorer = get_trained_explorer(session_key)
        st.sidebar.success("Models trained successfully!")
    except Exception as e:
        st.error(f"Failed to train models: {e}")
        st.stop()

st.markdown("---")
st.subheader("Simulate: Pit Now vs Pit Later")

col1, col2, col3, col4 = st.columns(4)

with col1:
    current_lap = st.number_input("Current Lap", min_value=1, max_value=70, value=20)
    target_lap = st.number_input("Pit Later Lap", min_value=current_lap+1, max_value=75, value=current_lap+5)

with col2:
    current_compound = st.selectbox("Current Compound", ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"], index=1)
    next_compound = st.selectbox("Next Compound", ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"], index=2)

with col3:
    current_tyre_age = st.number_input("Current Tyre Age (Laps)", min_value=1, max_value=50, value=15)
    laps_to_simulate = st.number_input("Laps to Simulate", min_value=10, max_value=50, value=15)

with col4:
    track_temp = st.slider("Track Temp (°C)", 20.0, 60.0, 35.0)
    baseline_pace = st.number_input("Baseline Pace (s)", value=95.0, step=0.1)

# Base features dictionary needed for the simulation
base_features = {
    "total_laps": 60,
    "track_evolution_index": baseline_pace - 1.0,  # Proxy
    "track_temperature": track_temp,
    "air_temperature": track_temp - 10.0,
    "stint_baseline_pace": baseline_pace,
    "rolling_median_pace_3L": baseline_pace + (current_tyre_age * 0.05),
    "recent_degradation_slope_5L": 0.05
}

if st.button("Run Simulation", type="primary"):
    with st.spinner("Simulating counterfactuals..."):
        try:
            results = explorer.compare_pit_windows(
                current_lap=current_lap,
                target_lap=target_lap,
                current_compound=current_compound,
                next_compound=next_compound,
                current_tyre_age=current_tyre_age,
                base_features=base_features,
                laps_to_simulate=laps_to_simulate
            )
            
            delta = results["delta_seconds"]
            st.markdown("### 🏆 Simulation Results")
            if delta > 0:
                st.success(f"**Pit Now** is faster by **{delta:.2f} seconds** over the next {laps_to_simulate} laps.")
            else:
                st.info(f"**Pit on Lap {target_lap}** is faster by **{abs(delta):.2f} seconds** over the next {laps_to_simulate} laps.")
                
            # Plot the cumulative times
            pit_now = results["pit_now"]
            pit_later = results["pit_later"]
            
            laps = list(range(current_lap, current_lap + laps_to_simulate))
            
            # Create a DataFrame for plotting lap times
            df_plot = pd.DataFrame({
                "Lap": laps,
                "Pit Now Pace": pit_now.lap_times,
                "Pit Later Pace": pit_later.lap_times
            })
            
            fig = px.line(
                df_plot, 
                x="Lap", 
                y=["Pit Now Pace", "Pit Later Pace"],
                title="Predicted Lap Times (Includes Pit Stop Loss)",
                labels={"value": "Lap Time (s)", "variable": "Strategy"}
            )
            fig.update_layout(template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            # Cumulative Race Time Delta
            cum_now = np.cumsum(pit_now.lap_times)
            cum_later = np.cumsum(pit_later.lap_times)
            delta_over_time = cum_later - cum_now # Positive means Pit Now is ahead
            
            fig2 = px.bar(
                x=laps, 
                y=delta_over_time,
                title="Cumulative Delta (Pit Now vs Pit Later) - Positive = Pit Now is Ahead",
                labels={"x": "Lap", "y": "Delta (Seconds)"}
            )
            fig2.update_layout(template="plotly_dark")
            fig2.add_hline(y=0, line_dash="dash", line_color="white")
            st.plotly_chart(fig2, use_container_width=True)
            
        except Exception as e:
            st.error(f"Simulation error: {e}")
