-- F1 Strategy Analytics — SQL Analysis Queries
-- Demonstrates joins, CTEs, window functions, rolling calculations,
-- ranking, aggregation, and anomaly detection.

-- ============================================================
-- Q1: Driver position change by lap (window function)
-- ============================================================
-- Shows each driver's position progression throughout the race.

WITH lap_positions AS (
    SELECT
        p.session_key,
        p.driver_number,
        d.name_acronym,
        d.team_name,
        l.lap_number,
        p.position,
        LAG(p.position) OVER (
            PARTITION BY p.session_key, p.driver_number
            ORDER BY l.lap_number
        ) AS prev_position,
        p.position - LAG(p.position) OVER (
            PARTITION BY p.session_key, p.driver_number
            ORDER BY l.lap_number
        ) AS position_change
    FROM laps l
    JOIN drivers d ON l.session_key = d.session_key
        AND l.driver_number = d.driver_number
    -- Join position at the start of each lap (closest timestamp)
    LEFT JOIN LATERAL (
        SELECT position
        FROM positions pos
        WHERE pos.session_key = l.session_key
          AND pos.driver_number = l.driver_number
          AND pos.date <= l.date_start
        ORDER BY pos.date DESC
        LIMIT 1
    ) p ON TRUE
)
SELECT * FROM lap_positions
WHERE position_change != 0
ORDER BY session_key, driver_number, lap_number;


-- ============================================================
-- Q2: Rolling 5-lap median pace per driver (rolling calculation)
-- ============================================================
-- Uses window frame to compute rolling average (median requires UDF).

SELECT
    session_key,
    driver_number,
    name_acronym,
    lap_number,
    lap_duration,
    AVG(lap_duration) OVER (
        PARTITION BY session_key, driver_number
        ORDER BY lap_number
        ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
    ) AS rolling_5lap_avg_pace,
    compound,
    tyre_age
FROM clean_race_laps
ORDER BY session_key, driver_number, lap_number;


-- ============================================================
-- Q3: Gap to teammate per lap (join + window)
-- ============================================================

WITH team_pairs AS (
    SELECT
        c.session_key,
        c.driver_number,
        c.name_acronym,
        c.team_name,
        c.lap_number,
        c.lap_duration,
        c.compound,
        c.tyre_age
    FROM clean_race_laps c
)
SELECT
    t1.session_key,
    t1.team_name,
    t1.name_acronym AS driver_1,
    t2.name_acronym AS driver_2,
    t1.lap_number,
    t1.lap_duration AS driver_1_time,
    t2.lap_duration AS driver_2_time,
    t1.lap_duration - t2.lap_duration AS gap_to_teammate,
    t1.compound AS driver_1_compound,
    t2.compound AS driver_2_compound
FROM team_pairs t1
JOIN team_pairs t2 ON t1.session_key = t2.session_key
    AND t1.team_name = t2.team_name
    AND t1.lap_number = t2.lap_number
    AND t1.driver_number < t2.driver_number
ORDER BY t1.session_key, t1.team_name, t1.lap_number;


-- ============================================================
-- Q4: Pace before and after pit stop (CTE + aggregation)
-- ============================================================

SELECT
    pi.session_key,
    pi.driver_number,
    pi.name_acronym,
    pi.pit_lap,
    pi.pit_duration,
    pi.compound_before,
    pi.compound_after,
    pi.pre_stop_pace,
    pi.post_stop_pace,
    pi.pace_gain,
    CASE
        WHEN pi.pace_gain > 0.5 THEN 'Significant improvement'
        WHEN pi.pace_gain > 0 THEN 'Marginal improvement'
        WHEN pi.pace_gain > -0.5 THEN 'Marginal worsening'
        ELSE 'Significant worsening'
    END AS stop_effectiveness
FROM pit_stop_impact pi
WHERE pi.pre_stop_pace IS NOT NULL
  AND pi.post_stop_pace IS NOT NULL
ORDER BY pi.pace_gain DESC;


-- ============================================================
-- Q5: Stint-level ranking by pace (ranking)
-- ============================================================

SELECT
    session_key,
    driver_number,
    name_acronym,
    team_name,
    stint_number,
    compound,
    clean_laps_in_stint,
    mean_pace,
    RANK() OVER (
        PARTITION BY session_key, compound
        ORDER BY mean_pace ASC
    ) AS compound_pace_rank,
    RANK() OVER (
        PARTITION BY session_key
        ORDER BY fastest_lap ASC
    ) AS overall_fastest_rank
FROM driver_stint_summary
ORDER BY session_key, mean_pace;


-- ============================================================
-- Q6: Compound-level degradation slope proxy (aggregation)
-- ============================================================
-- Simple degradation metric: (last lap time - first lap time) / stint length

SELECT
    session_key,
    compound,
    driver_number,
    name_acronym,
    stint_number,
    fastest_lap,
    mean_pace,
    slowest_lap - fastest_lap AS pace_range,
    CASE
        WHEN last_tyre_age - first_tyre_age > 0 THEN
            (slowest_lap - fastest_lap) * 1.0 / (last_tyre_age - first_tyre_age)
        ELSE NULL
    END AS approx_deg_per_lap
FROM tyre_degradation_summary
WHERE lap_count >= 5
ORDER BY approx_deg_per_lap DESC;


-- ============================================================
-- Q7: Anomaly check — laps with impossible durations
-- ============================================================

SELECT
    l.session_key,
    l.driver_number,
    d.name_acronym,
    l.lap_number,
    l.lap_duration,
    l.duration_sector_1,
    l.duration_sector_2,
    l.duration_sector_3,
    l.duration_sector_1 + l.duration_sector_2 + l.duration_sector_3 AS sector_sum,
    ABS(l.lap_duration - (l.duration_sector_1 + l.duration_sector_2 + l.duration_sector_3))
        AS discrepancy,
    CASE
        WHEN l.lap_duration IS NULL THEN 'MISSING_DURATION'
        WHEN l.lap_duration <= 0 THEN 'NEGATIVE_DURATION'
        WHEN l.lap_duration < 30 THEN 'IMPOSSIBLY_FAST'
        WHEN l.lap_duration > 300 THEN 'IMPOSSIBLY_SLOW'
        WHEN ABS(l.lap_duration - (COALESCE(l.duration_sector_1,0) +
             COALESCE(l.duration_sector_2,0) + COALESCE(l.duration_sector_3,0))) > 5
             THEN 'SECTOR_SUM_MISMATCH'
        ELSE 'OK'
    END AS anomaly_type
FROM laps l
JOIN drivers d ON l.session_key = d.session_key AND l.driver_number = d.driver_number
WHERE l.lap_duration IS NULL
   OR l.lap_duration <= 0
   OR l.lap_duration < 30
   OR l.lap_duration > 300
   OR ABS(l.lap_duration - (COALESCE(l.duration_sector_1,0) +
      COALESCE(l.duration_sector_2,0) + COALESCE(l.duration_sector_3,0))) > 5
ORDER BY l.session_key, l.driver_number, l.lap_number;


-- ============================================================
-- Q8: Drivers with most blue flags (traffic indicator)
-- ============================================================

SELECT
    rc.session_key,
    rc.driver_number,
    d.name_acronym,
    d.team_name,
    COUNT(*) AS blue_flag_count
FROM race_control rc
JOIN drivers d ON rc.session_key = d.session_key AND rc.driver_number = d.driver_number
WHERE rc.flag = 'BLUE'
GROUP BY rc.session_key, rc.driver_number, d.name_acronym, d.team_name
ORDER BY blue_flag_count DESC;


-- ============================================================
-- Q9: Weather changes during race (time-series)
-- ============================================================

SELECT
    session_key,
    date,
    air_temperature,
    track_temperature,
    humidity,
    rainfall,
    wind_speed,
    LAG(track_temperature) OVER (PARTITION BY session_key ORDER BY date)
        AS prev_track_temp,
    track_temperature - LAG(track_temperature) OVER (
        PARTITION BY session_key ORDER BY date
    ) AS track_temp_change,
    condition_category
FROM weather_condition_windows
ORDER BY session_key, date;
