"""Local JSON bridge for the F1 dashboard. Run with python dashboard_api.py."""
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json
import math

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.analytics.race_summary import RaceAnalyzer
from src.analytics.undercut import PitStrategyAnalyzer
from src.database.models import Meeting, Session as RaceSession

DB = Path(__file__).resolve().parent / 'data' / 'f1_strategy.db'
engine = create_engine(f'sqlite:///{DB}')


def clean(value):
    if is_dataclass(value):
        return clean(asdict(value))
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def records(df):
    return clean(df.to_dict(orient='records'))


def sessions():
    with Session(engine) as db:
        rows = db.query(RaceSession, Meeting).join(Meeting).order_by(RaceSession.date_start.desc()).all()
        return [{'session_key': s.session_key, 'label': f'{m.meeting_name} · {s.session_name} · {s.year}', 'meeting_name': m.meeting_name, 'session_name': s.session_name, 'date': s.date_start} for s, m in rows]


def data(key, view):
    analyzer = RaceAnalyzer(engine)
    if view == 'overview':
        return clean(analyzer.analyze_race(key))
    raw = analyzer.get_session_data(key)
    result = analyzer.clean_engine.classify(raw['laps'], raw['stints'], raw['pit_stops'], raw['race_control'])
    if view == 'pace':
        overview = analyzer.analyze_race(key)
        return {'drivers': clean(overview.driver_kpis), 'laps': records(result.clean_laps)}
    if view == 'tyres':
        if raw['stints'].empty or raw['drivers'].empty or result.clean_laps.empty:
            return []
        teams = dict(zip(raw['drivers'].get('driver_number', []), raw['drivers'].get('team_name', [])))
        stints = analyzer.analyze_stints(key, result.clean_laps, raw['stints'], raw['drivers'])
        return [{**clean(stint), 'team_name': teams.get(stint.driver_number)} for stint in stints]
    if view == 'pit':
        if raw['stints'].empty or result.clean_laps.empty:
            return []
        names = dict(zip(raw['drivers'].get('driver_number', []), raw['drivers'].get('full_name', [])))
        teams = dict(zip(raw['drivers'].get('driver_number', []), raw['drivers'].get('team_name', [])))
        return [{**clean(p), 'driver_name': names.get(p.driver_number, str(p.driver_number)), 'team_name': teams.get(p.driver_number)} for p in PitStrategyAnalyzer(engine).analyze_pit_stops(key, result.clean_laps)]
    if view == 'quality':
        return {'summary': clean(result.summary), 'excluded': records(result.excluded_laps)}
    raise ValueError('Unknown view')


def cross_race():
    with engine.connect() as conn:
        rows = conn.execute(text('''SELECT s.session_key, m.meeting_name, s.session_name,
          (SELECT COUNT(*) FROM pit_stops p WHERE p.session_key=s.session_key) AS total_pit_stops,
          (SELECT AVG(p.pit_duration) FROM pit_stops p WHERE p.session_key=s.session_key) AS avg_pit_duration,
          (SELECT AVG(l.lap_duration) FROM laps l WHERE l.session_key=s.session_key AND l.lap_duration > 0) AS avg_lap_time,
          (SELECT COUNT(*) FROM laps l WHERE l.session_key=s.session_key AND l.lap_duration > 0) AS total_laps
          FROM sessions s JOIN meetings m ON s.meeting_key=m.meeting_key ORDER BY s.date_start DESC''')).mappings().all()
        return clean([dict(row) for row in rows])


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, obj):
        body = json.dumps(clean(obj), allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            parts = urlparse(self.path).path.strip('/').split('/')
            if len(parts) != 4 or parts[:2] != ['api', 'sessions'] or not parts[2].isdigit() or parts[3] != 'simulate':
                return self.send_json(404, {'error': 'Not found'})
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 4096:
                raise ValueError('Invalid request size')
            params = json.loads(self.rfile.read(length))
            current = int(params['current_lap'])
            target = int(params['target_lap'])
            laps = int(params['laps_to_simulate'])
            age = int(params['current_tyre_age'])
            baseline = float(params['baseline_pace'])
            temperature = float(params['track_temp'])
            compounds = {'SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'}
            if not (1 <= current <= 70 and 10 <= laps <= 50 and current < target < current + laps - 1 and 1 <= age <= 50 and 20 <= temperature <= 60 and 30 <= baseline <= 300 and params['current_compound'] in compounds and params['next_compound'] in compounds):
                raise ValueError('Invalid simulation inputs')
            from src.models.strategy_explorer import StrategyExplorer
            explorer = StrategyExplorer(engine)
            explorer.train_models(int(parts[2]))
            features = {'total_laps': 60, 'track_evolution_index': baseline - 1, 'track_temperature': temperature, 'air_temperature': temperature - 10, 'stint_baseline_pace': baseline, 'rolling_median_pace_3L': baseline + age * 0.05, 'recent_degradation_slope_5L': 0.05}
            result = explorer.compare_pit_windows(current, target, params['current_compound'], params['next_compound'], age, features, laps)
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(400, {'error': str(exc)})

    def do_GET(self):
        try:
            if not DB.is_file():
                raise FileNotFoundError('Database not found. Sync race data first.')
            parts = urlparse(self.path).path.strip('/').split('/')
            if parts == ['api', 'sessions']:
                value = sessions()
            elif parts == ['api', 'cross-race']:
                value = cross_race()
            elif len(parts) == 4 and parts[:2] == ['api', 'sessions'] and parts[2].isdigit():
                value = data(int(parts[2]), parts[3])
            else:
                return self.send_json(404, {'error': 'Not found'})
            self.send_json(200, value)
        except Exception as exc:
            self.send_json(500, {'error': str(exc)})


if __name__ == '__main__':
    print('Dashboard API listening on http://127.0.0.1:8000')
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
