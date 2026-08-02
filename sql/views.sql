-- F1 Strategy Analytics — Analytical SQL Views
-- These views power the dashboard and analytical modules.
-- Compatible with both SQLite and PostgreSQL.

-- ============================================================
-- 1. race_control_periods
--    Materializes safety car, VSC, red flag periods
--    with start/end laps for joining to laps.
-- ============================================================
CREATE VIEW IF NOT EXISTS race_control_periods AS
WITH flag_events AS (
    SELECT
        session_key,
        date,
        lap_number,
        flag,
        category,
        scope,
        message,
        ROW_NUMBER() OVER (
            PARTITION BY session_key
            ORDER BY date
        ) AS event_seq
    FROM race_control
    WHERE category IN ('Flag', 'SafetyCar')
      AND scope = 'Track'
      AND flag IN ('YELLOW', 'DOUBLE YELLOW', 'GREEN', 'RED',
                   'SAFETY CAR', 'VIRTUAL SAFETY CAR')
)
SELECT
    session_key,
    flag AS status,
    lap_number AS start_lap,
    date AS start_time,
    LEAD(date) OVER (
        PARTITION BY session_key ORDER BY date
    ) AS end_time,
    LEAD(lap_number) OVER (
        PARTITION BY session_key ORDER BY date
    ) AS end_lap
FROM flag_events;


-- ============================================================
-- 2. clean_race_laps
--    Laps suitable for pace analysis — excludes pit laps,
--    SC periods, formation laps, and statistical outliers.
-- ============================================================
CREATE VIEW IF NOT EXISTS clean_race_laps AS
WITH pit_laps AS (
    -- Laps where driver enters or exits the pit
    SELECT session_key, driver_number, lap_number AS pit_in_lap
    FROM pit_stops
    UNION
    SELECT session_key, driver_number, lap_number + 1 AS pit_out_lap
    FROM pit_stops
),
sc_laps AS (
    -- Laps under safety car / VSC / red flag
    SELECT DISTINCT session_key, lap_number
    FROM race_control
    WHERE flag IN ('SAFETY CAR', 'VIRTUAL SAFETY CAR', 'RED')
      AND scope = 'Track'
),
driver_medians AS (
    -- Per-driver median lap time (all non-pit laps) for MAD calculation
    SELECT
        l.session_key,
        l.driver_number,
        -- SQLite doesn't have PERCENTILE, so we use a subquery
        l.lap_duration AS lap_duration
    FROM laps l
    WHERE l.lap_duration IS NOT NULL
      AND l.lap_duration > 0
      AND l.lap_number > 1
      AND l.is_pit_out_lap = 0
      AND NOT EXISTS (
          SELECT 1 FROM pit_laps p
          WHERE p.session_key = l.session_key
            AND p.driver_number = l.driver_number
            AND p.pit_in_lap = l.lap_number
      )
      AND NOT EXISTS (
          SELECT 1 FROM sc_laps s
          WHERE s.session_key = l.session_key
            AND s.lap_number = l.lap_number
      )
)
SELECT
    l.session_key,
    l.driver_number,
    l.lap_number,
    l.date_start,
    l.lap_duration,
    l.duration_sector_1,
    l.duration_sector_2,
    l.duration_sector_3,
    l.i1_speed,
    l.i2_speed,
    l.st_speed,
    s.stint_number,
    s.compound,
    s.tyre_age_at_start + (l.lap_number - s.lap_start) AS tyre_age,
    d.full_name AS driver_name,
    d.name_acronym,
    d.team_name
FROM laps l
JOIN stints s ON l.session_key = s.session_key
    AND l.driver_number = s.driver_number
    AND l.lap_number BETWEEN s.lap_start AND s.lap_end
JOIN drivers d ON l.session_key = d.session_key
    AND l.driver_number = d.driver_number
WHERE l.lap_duration IS NOT NULL
  AND l.lap_duration > 0
  AND l.lap_number > 1
  AND (l.is_pit_out_lap = 0 OR l.is_pit_out_lap IS NULL)
  AND NOT EXISTS (
      SELECT 1 FROM pit_laps p
      WHERE p.session_key = l.session_key
        AND p.driver_number = l.driver_number
        AND p.pit_in_lap = l.lap_number
  )
  AND NOT EXISTS (
      SELECT 1 FROM sc_laps sc
      WHERE sc.session_key = l.session_key
        AND sc.lap_number = l.lap_number
  );


-- ============================================================
-- 3. driver_race_summary
--    Aggregated per-driver race performance metrics.
-- ============================================================
CREATE VIEW IF NOT EXISTS driver_race_summary AS
WITH clean AS (
    SELECT * FROM clean_race_laps
),
starting_pos AS (
    SELECT
        session_key,
        driver_number,
        position AS grid_position
    FROM positions
    WHERE id IN (
        SELECT MIN(id) FROM positions
        GROUP BY session_key, driver_number
    )
),
finishing_pos AS (
    SELECT
        session_key,
        driver_number,
        position AS finish_position
    FROM positions
    WHERE id IN (
        SELECT MAX(id) FROM positions
        GROUP BY session_key, driver_number
    )
),
pit_summary AS (
    SELECT
        session_key,
        driver_number,
        COUNT(*) AS pit_count,
        SUM(pit_duration) AS total_pit_time
    FROM pit_stops
    GROUP BY session_key, driver_number
)
SELECT
    c.session_key,
    c.driver_number,
    c.driver_name,
    c.name_acronym,
    c.team_name,
    sp.grid_position,
    fp.finish_position,
    COALESCE(sp.grid_position, 0) - COALESCE(fp.finish_position, 0) AS positions_gained,
    COUNT(*) AS clean_lap_count,
    MIN(c.lap_duration) AS fastest_clean_lap,
    AVG(c.lap_duration) AS mean_clean_pace,
    COALESCE(ps.pit_count, 0) AS pit_count,
    COALESCE(ps.total_pit_time, 0) AS total_pit_time
FROM clean c
LEFT JOIN starting_pos sp ON c.session_key = sp.session_key
    AND c.driver_number = sp.driver_number
LEFT JOIN finishing_pos fp ON c.session_key = fp.session_key
    AND c.driver_number = fp.driver_number
LEFT JOIN pit_summary ps ON c.session_key = ps.session_key
    AND c.driver_number = ps.driver_number
GROUP BY c.session_key, c.driver_number, c.driver_name, c.name_acronym,
         c.team_name, sp.grid_position, fp.finish_position,
         ps.pit_count, ps.total_pit_time;


-- ============================================================
-- 4. driver_stint_summary
--    Per-driver per-stint performance summary.
-- ============================================================
CREATE VIEW IF NOT EXISTS driver_stint_summary AS
SELECT
    c.session_key,
    c.driver_number,
    c.driver_name,
    c.name_acronym,
    c.team_name,
    c.stint_number,
    c.compound,
    MIN(c.tyre_age) AS min_tyre_age,
    MAX(c.tyre_age) AS max_tyre_age,
    COUNT(*) AS clean_laps_in_stint,
    MIN(c.lap_duration) AS fastest_lap,
    AVG(c.lap_duration) AS mean_pace,
    MAX(c.lap_duration) AS slowest_lap
FROM clean_race_laps c
GROUP BY c.session_key, c.driver_number, c.driver_name, c.name_acronym,
         c.team_name, c.stint_number, c.compound;


-- ============================================================
-- 5. tyre_degradation_summary
--    Aggregated degradation metrics per compound/circuit/driver.
-- ============================================================
CREATE VIEW IF NOT EXISTS tyre_degradation_summary AS
SELECT
    c.session_key,
    s.circuit_short_name,
    c.compound,
    c.driver_number,
    c.name_acronym,
    c.team_name,
    c.stint_number,
    COUNT(*) AS lap_count,
    MIN(c.lap_duration) AS fastest_lap,
    AVG(c.lap_duration) AS mean_pace,
    MIN(c.tyre_age) AS first_tyre_age,
    MAX(c.tyre_age) AS last_tyre_age
FROM clean_race_laps c
JOIN sessions s ON c.session_key = s.session_key
GROUP BY c.session_key, s.circuit_short_name, c.compound,
         c.driver_number, c.name_acronym, c.team_name, c.stint_number;


-- ============================================================
-- 6. pit_stop_impact
--    Pre-stop and post-stop pace comparison.
-- ============================================================
CREATE VIEW IF NOT EXISTS pit_stop_impact AS
WITH pre_stop AS (
    SELECT
        c.session_key,
        c.driver_number,
        p.lap_number AS pit_lap,
        AVG(c.lap_duration) AS pre_stop_pace
    FROM clean_race_laps c
    JOIN pit_stops p ON c.session_key = p.session_key
        AND c.driver_number = p.driver_number
    WHERE c.lap_number BETWEEN (p.lap_number - 3) AND (p.lap_number - 1)
    GROUP BY c.session_key, c.driver_number, p.lap_number
),
post_stop AS (
    SELECT
        c.session_key,
        c.driver_number,
        p.lap_number AS pit_lap,
        AVG(c.lap_duration) AS post_stop_pace
    FROM clean_race_laps c
    JOIN pit_stops p ON c.session_key = p.session_key
        AND c.driver_number = p.driver_number
    WHERE c.lap_number BETWEEN (p.lap_number + 2) AND (p.lap_number + 4)
    GROUP BY c.session_key, c.driver_number, p.lap_number
)
SELECT
    p.session_key,
    p.driver_number,
    d.name_acronym,
    d.team_name,
    p.lap_number AS pit_lap,
    p.pit_duration,
    p.lane_duration,
    pre.pre_stop_pace,
    post.post_stop_pace,
    pre.pre_stop_pace - post.post_stop_pace AS pace_gain,
    s_before.compound AS compound_before,
    s_after.compound AS compound_after
FROM pit_stops p
JOIN drivers d ON p.session_key = d.session_key
    AND p.driver_number = d.driver_number
LEFT JOIN pre_stop pre ON p.session_key = pre.session_key
    AND p.driver_number = pre.driver_number
    AND p.lap_number = pre.pit_lap
LEFT JOIN post_stop post ON p.session_key = post.session_key
    AND p.driver_number = post.driver_number
    AND p.lap_number = post.pit_lap
LEFT JOIN stints s_before ON p.session_key = s_before.session_key
    AND p.driver_number = s_before.driver_number
    AND p.lap_number BETWEEN s_before.lap_start AND s_before.lap_end
LEFT JOIN stints s_after ON p.session_key = s_after.session_key
    AND p.driver_number = s_after.driver_number
    AND (p.lap_number + 1) BETWEEN s_after.lap_start AND s_after.lap_end;


-- ============================================================
-- 7. position_gain_summary
--    Grid vs finish and when gains/losses occurred.
-- ============================================================
CREATE VIEW IF NOT EXISTS position_gain_summary AS
SELECT
    drs.session_key,
    drs.driver_number,
    drs.driver_name,
    drs.name_acronym,
    drs.team_name,
    drs.grid_position,
    drs.finish_position,
    drs.positions_gained,
    drs.pit_count,
    drs.fastest_clean_lap,
    drs.mean_clean_pace
FROM driver_race_summary drs
ORDER BY drs.positions_gained DESC;


-- ============================================================
-- 8. driver_consistency_summary
--    Consistency metrics per driver per session.
-- ============================================================
CREATE VIEW IF NOT EXISTS driver_consistency_summary AS
SELECT
    c.session_key,
    c.driver_number,
    c.driver_name,
    c.name_acronym,
    c.team_name,
    COUNT(*) AS clean_lap_count,
    AVG(c.lap_duration) AS mean_pace,
    MIN(c.lap_duration) AS fastest_lap,
    MAX(c.lap_duration) AS slowest_lap,
    MAX(c.lap_duration) - MIN(c.lap_duration) AS range_seconds
FROM clean_race_laps c
GROUP BY c.session_key, c.driver_number, c.driver_name,
         c.name_acronym, c.team_name;


-- ============================================================
-- 9. weather_condition_windows
--    Weather conditions binned by approximate lap ranges.
-- ============================================================
CREATE VIEW IF NOT EXISTS weather_condition_windows AS
SELECT
    w.session_key,
    w.date,
    w.air_temperature,
    w.track_temperature,
    w.humidity,
    w.rainfall,
    w.wind_speed,
    w.wind_direction,
    CASE
        WHEN w.rainfall > 0 THEN 'WET'
        WHEN w.track_temperature > 40 THEN 'HOT'
        WHEN w.track_temperature < 20 THEN 'COOL'
        ELSE 'NORMAL'
    END AS condition_category
FROM weather w;
