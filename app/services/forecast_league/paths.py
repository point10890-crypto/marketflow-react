"""예측 리그 저장 위치. 테스트와 호스트 이전은 env FORECAST_LEAGUE_DIR 로 덮어쓴다."""
from __future__ import annotations

import os

from app.utils.paths import DATA_DIR


def league_dir() -> str:
    return os.environ.get('FORECAST_LEAGUE_DIR') or os.path.join(DATA_DIR, 'forecast_league')


def db_path() -> str:
    return os.path.join(league_dir(), 'league.db')
