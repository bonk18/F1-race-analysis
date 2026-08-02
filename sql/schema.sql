-- F1 Strategy Analytics — Database Schema
-- Supports both SQLite and PostgreSQL

-- ============================================================
-- Core Tables
-- ============================================================

CREATE TABLE IF NOT EXISTS meetings (
    meeting_key         INTEGER PRIMARY KEY,
    meeting_name        TEXT NOT NULL,
    official_name       TEXT,
    location            TEXT,
    country_key         INTEGER,
    country_code        TEXT,
    country_name        TEXT,
    circuit_key         INTEGER,
    circuit_short_name  TEXT,
    circuit_type        TEXT,
    gmt_offset          TEXT,
    date_start          TIMESTAMP,
    date_end            TIMESTAMP,
    year                INTEGER NOT NULL,
    is_cancelled        BOOLEAN DEFAULT FALSE,
    ingested_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_meetings_year ON meetings(year);

CREATE TABLE IF NOT EXISTS sessions (
    session_key         INTEGER PRIMARY KEY,
    session_type        TEXT NOT NULL,
    session_name        TEXT,
    meeting_key         INTEGER NOT NULL REFERENCES meetings(meeting_key),
    circuit_key         INTEGER,
    circuit_short_name  TEXT,
    date_start          TIMESTAMP,
    date_end            TIMESTAMP,
    year                INTEGER,
    is_cancelled        BOOLEAN DEFAULT FALSE,
    ingested_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_meeting ON sessions(meeting_key);

CREATE TABLE IF NOT EXISTS drivers (
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    driver_number       INTEGER NOT NULL,
    broadcast_name      TEXT,
    full_name           TEXT NOT NULL,
    name_acronym        TEXT,
    team_name           TEXT,
    team_colour         TEXT,
    first_name          TEXT,
    last_name           TEXT,
    country_code        TEXT,
    headshot_url        TEXT,
    PRIMARY KEY (session_key, driver_number)
);

CREATE TABLE IF NOT EXISTS laps (
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    driver_number       INTEGER NOT NULL,
    lap_number          INTEGER NOT NULL,
    date_start          TIMESTAMP,
    lap_duration        REAL,
    duration_sector_1   REAL,
    duration_sector_2   REAL,
    duration_sector_3   REAL,
    i1_speed            INTEGER,
    i2_speed            INTEGER,
    st_speed            INTEGER,
    is_pit_out_lap      BOOLEAN,
    segments_sector_1   TEXT,
    segments_sector_2   TEXT,
    segments_sector_3   TEXT,
    PRIMARY KEY (session_key, driver_number, lap_number)
);

CREATE TABLE IF NOT EXISTS stints (
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    driver_number       INTEGER NOT NULL,
    stint_number        INTEGER NOT NULL,
    lap_start           INTEGER NOT NULL,
    lap_end             INTEGER NOT NULL,
    compound            TEXT,
    tyre_age_at_start   INTEGER DEFAULT 0,
    PRIMARY KEY (session_key, driver_number, stint_number)
);

CREATE TABLE IF NOT EXISTS pit_stops (
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    driver_number       INTEGER NOT NULL,
    lap_number          INTEGER NOT NULL,
    pit_duration        REAL,
    lane_duration       REAL,
    stop_duration       REAL,
    date                TIMESTAMP,
    PRIMARY KEY (session_key, driver_number, lap_number)
);

CREATE TABLE IF NOT EXISTS positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    driver_number       INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    date                TIMESTAMP NOT NULL,
    UNIQUE (session_key, driver_number, date)
);
CREATE INDEX IF NOT EXISTS idx_positions_session_driver ON positions(session_key, driver_number);

CREATE TABLE IF NOT EXISTS weather (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    air_temperature     REAL,
    track_temperature   REAL,
    humidity            REAL,
    rainfall            INTEGER,
    wind_speed          REAL,
    wind_direction      INTEGER,
    pressure            REAL,
    date                TIMESTAMP NOT NULL,
    UNIQUE (session_key, date)
);
CREATE INDEX IF NOT EXISTS idx_weather_session_date ON weather(session_key, date);

CREATE TABLE IF NOT EXISTS race_control (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key         INTEGER NOT NULL REFERENCES sessions(session_key),
    category            TEXT,
    flag                TEXT,
    scope               TEXT,
    sector              INTEGER,
    message             TEXT,
    driver_number       INTEGER,
    lap_number          INTEGER,
    date                TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rc_session_date ON race_control(session_key, date);

CREATE TABLE IF NOT EXISTS data_quality_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key         INTEGER NOT NULL,
    driver_number       INTEGER,
    lap_number          INTEGER,
    issue_type          TEXT NOT NULL,
    severity            TEXT NOT NULL,
    description         TEXT,
    rule_name           TEXT,
    action_taken        TEXT,
    affected_count      INTEGER DEFAULT 1,
    detected_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name          TEXT NOT NULL,
    model_version       TEXT,
    training_period     TEXT,
    evaluation_races    TEXT,
    feature_set         TEXT,
    hyperparameters     TEXT,
    metrics             TEXT,
    git_commit          TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS predictions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id        INTEGER REFERENCES model_runs(id),
    session_key         INTEGER NOT NULL,
    driver_number       INTEGER NOT NULL,
    lap_number          INTEGER NOT NULL,
    prediction_type     TEXT NOT NULL,
    predicted_value     REAL,
    actual_value        REAL,
    confidence_lower    REAL,
    confidence_upper    REAL,
    features_json       TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
