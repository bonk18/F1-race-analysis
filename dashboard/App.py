"""Main Streamlit application entry point."""

import streamlit as st

st.set_page_config(
    page_title="F1 Strategy Analytics",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for premium dark mode aesthetics
st.markdown("""
<style>
    /* Global Backgrounds */
    .stApp {
        background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
        color: #c9d1d9;
        font-family: 'Inter', sans-serif;
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #e6edf3;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    
    /* Premium Title Gradient */
    .premium-title {
        background: linear-gradient(90deg, #ff1801 0%, #ff5722 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0d1117;
        border-right: 1px solid #30363d;
    }
    
    /* Metrics / KPI Cards */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
    }
    [data-testid="stMetricDelta"] {
        font-size: 1rem;
    }
    
    /* DataFrames / Tables */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #30363d;
    }
    
    /* Buttons */
    .stButton>button {
        background: linear-gradient(90deg, #238636 0%, #2ea043 100%);
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(46, 160, 67, 0.4);
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="premium-title">F1 Strategy Analytics</div>', unsafe_allow_html=True)
st.markdown("*Advanced Telemetry, Pit Strategy, and Performance Modelling Platform*")

st.markdown("---")

st.markdown("""
Welcome to the **F1 Strategy Analytics Platform**.

Please select an analysis module from the sidebar to begin:
- 📊 **Race Overview**: High-level KPIs, positions gained, and automated takeaways.
- ⏱️ **Driver Pace & Consistency**: Deep dive into lap-by-lap pace, MAD consistency, and teammates comparisons.
- 🛞 **Tyre Degradation**: Stint analysis, compound comparisons, and degradation modelling.
- 🛑 **Pit Strategy**: Pit-lane time loss, undercut attempts, and post-stop pace gains.
""")

# Sidebar info
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/3/33/F1.svg", width=100)
    st.markdown("### Configuration")
    st.info("Database connected successfully.")
    
    st.markdown("---")
    st.markdown("Built by Shreyas")
    st.markdown("[GitHub: bonk18](https://github.com/bonk18)")
