"""
Wave Pattern Detection API — /api/wave/*
M&W 차트 패턴 인식 엔드포인트
"""
import os
import json
import logging
import time
from flask import Blueprint, request, jsonify

from engine.wave.data_adapter import load_ohlcv, ohlcv_to_chart_data
from engine.wave.zigzag import zigzag, extract_five_point_groups
from engine.wave.classifier import classify_pattern
from engine.wave.pattern_scorer import score_pattern
from engine.wave.models import WAVE_META, WaveDetectResult

logger = logging.getLogger(__name__)

wave_bp = Blueprint('wave', __name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WAVE_DIR = os.path.join(_BASE_DIR, 'data', 'wave')

# 스크리너 결과 캐시 (30초 TTL)
_screener_cache: dict = {}
_CACHE_TTL = 30


def _load_screener_json():
    """캐시된 스크리너 결과 로드."""
    now = time.time()
    if 'data' in _screener_cache and now - _screener_cache.get('ts', 0) < _CACHE_TTL:
        return _screener_cache['data']

    path = os.path.join(_WAVE_DIR, 'wave_screener_latest.json')
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _screener_cache['data'] = data
        _screener_cache['ts'] = now
        return data
    except Exception as e:
        logger.error(f"Failed to load screener: {e}")
        return None


@wave_bp.route('/screener/latest')
def screener_latest():
    """
    캐시된 최신 스크리너 결과.
    GET /api/wave/screener/latest?min_confidence=50&limit=50
    """
    data = _load_screener_json()
    if not data:
        return jsonify({
            'signals': [],
            'scan_count': 0,
            'signal_count': 0,
            'date': None,
            'message': 'No screener data available. Run wave scan first.',
        })

    min_conf = int(request.args.get('min_confidence', '0'))
    limit = int(request.args.get('limit', '100'))
    pattern_class = request.args.get('pattern_class', '').upper()  # W or M

    signals = data.get('signals', [])

    # 필터
    if min_conf > 0:
        signals = [s for s in signals if s['best_pattern']['confidence'] >= min_conf]
    if pattern_class in ('W', 'M'):
        signals = [s for s in signals if s['best_pattern']['pattern_class'] == pattern_class]

    signals = signals[:limit]

    return jsonify({
        'date': data.get('date'),
        'updated_at': data.get('updated_at'),
        'market': data.get('market'),
        'scan_count': data.get('scan_count', 0),
        'signal_count': len(signals),
        'total_signal_count': data.get('signal_count', 0),
        'processing_time_sec': data.get('processing_time_sec'),
        'signals': signals,
    })


@wave_bp.route('/detect/<ticker>')
def detect_patterns(ticker: str):
    """
    단일 종목 패턴 감지.
    GET /api/wave/detect/005930?market=KR&lookback=200
    """
    market = request.args.get('market', 'KR').upper()
    lookback = int(request.args.get('lookback', '200'))
    reversal_pct = request.args.get('reversal_pct', None)
    if reversal_pct is not None:
        reversal_pct = float(reversal_pct)

    # 1. 데이터 로드
    data = load_ohlcv(ticker, market=market, lookback=lookback)
    if data is None:
        return jsonify({'error': f'No data found for {ticker} ({market})', 'patterns': [], 'chart_data': []}), 200

    dates = data['dates']
    highs = data['highs']
    lows = data['lows']
    closes = data['closes']
    volumes = data['volumes']

    # 2. ZigZag 전환점 추출
    turning_points = zigzag(dates, highs, lows, closes, reversal_pct=reversal_pct)

    # 3. 5점 그룹 추출
    groups = extract_five_point_groups(turning_points)

    # 4. 각 그룹 분류 + 채점
    patterns = []
    for group in groups:
        pattern = classify_pattern(
            group, closes, volumes=volumes,
            current_price=float(closes[-1]),
        )
        pattern_score = score_pattern(pattern, closes, volumes=volumes)
        # 낮은 신뢰도 필터링 (30점 이상만)
        if pattern_score >= 30:
            pattern.confidence = pattern_score
            patterns.append(pattern)

    # 신뢰도 내림차순 정렬
    patterns.sort(key=lambda p: p.confidence, reverse=True)

    # 최근 패턴 우선 — 최대 10개
    patterns = patterns[:10]

    # 5. 차트 데이터 변환
    chart_data = ohlcv_to_chart_data(data)

    result = WaveDetectResult(
        ticker=ticker,
        market=market,
        patterns=patterns,
        chart_data=chart_data,
        turning_points=turning_points,
    )

    return jsonify(result.to_dict())


@wave_bp.route('/pattern-types')
def pattern_types():
    """32가지 패턴 타입 목록"""
    types = []
    for wave_type, meta in WAVE_META.items():
        types.append({
            'wave_type': wave_type if isinstance(wave_type, str) else wave_type.value,
            'label': meta['label'],
            'bias': meta['bias'],
            'reliability': meta['reliability'],
            'direction': 'bullish' if meta['bias'] > 0 else 'bearish',
        })
    return jsonify({'types': types, 'count': len(types)})


# ─── DB Endpoints: 시그널 히스토리 + 통계 ───

@wave_bp.route('/signals')
def signal_history():
    """
    시그널 히스토리 조회.
    GET /api/wave/signals?status=active&pattern_class=W&limit=50
    """
    from app.models.wave import WaveSignal

    status = request.args.get('status', '')
    pattern_class = request.args.get('pattern_class', '').upper()
    limit = int(request.args.get('limit', '100'))

    query = WaveSignal.query.order_by(WaveSignal.detected_at.desc())

    if status:
        query = query.filter_by(status=status)
    if pattern_class in ('W', 'M'):
        query = query.filter_by(pattern_class=pattern_class)

    signals = query.limit(limit).all()

    return jsonify({
        'count': len(signals),
        'signals': [s.to_dict() for s in signals],
    })


@wave_bp.route('/signals/<int:signal_id>/tracking')
def signal_tracking(signal_id: int):
    """시그널 일별 추적 데이터."""
    from app.models.wave import WaveSignal, WaveTracking

    sig = WaveSignal.query.get_or_404(signal_id)
    tracking = WaveTracking.query.filter_by(signal_id=signal_id)\
        .order_by(WaveTracking.date).all()

    return jsonify({
        'signal': sig.to_dict(),
        'tracking': [{
            'date': t.date,
            'close_price': t.close_price,
            'pnl_pct': t.pnl_pct,
            'days_since': t.days_since,
            'neckline_broken': t.neckline_broken,
        } for t in tracking],
    })


@wave_bp.route('/stats')
def pattern_stats():
    """패턴 타입별 누적 통계 (승률, 평균 수익)."""
    from app.models.wave import WavePatternStats

    stats = WavePatternStats.query.order_by(WavePatternStats.total_count.desc()).all()

    return jsonify({
        'count': len(stats),
        'stats': [s.to_dict() for s in stats],
    })


@wave_bp.route('/signals/save', methods=['POST'])
def save_signals():
    """스크리너 결과를 DB에 적재 (내부 호출용)."""
    from app.services.wave_tracker import save_screener_to_db

    data = _load_screener_json()
    if not data:
        return jsonify({'error': 'No screener data'}), 404

    saved = save_screener_to_db(data)
    return jsonify({'saved': saved, 'date': data.get('date')})


@wave_bp.route('/signals/track', methods=['POST'])
def track_signals():
    """활성 시그널 일별 추적 업데이트 (내부 호출용)."""
    from app.services.wave_tracker import update_active_signals, refresh_pattern_stats

    result = update_active_signals()
    refresh_pattern_stats()
    return jsonify(result)


@wave_bp.route('/dashboard')
def wave_dashboard():
    """Wave 대시보드 종합 데이터 (프론트엔드 메인)."""
    from app.models.wave import WaveSignal, WavePatternStats

    # 활성 시그널
    active = WaveSignal.query.filter_by(status='active')\
        .order_by(WaveSignal.confidence.desc()).limit(20).all()

    # 최근 청산 시그널
    closed = WaveSignal.query.filter(
        WaveSignal.status.in_(['hit_target', 'hit_stop', 'expired'])
    ).order_by(WaveSignal.closed_at.desc()).limit(20).all()

    # 통계
    stats = WavePatternStats.query.order_by(WavePatternStats.total_count.desc()).all()

    # 요약
    total = WaveSignal.query.count()
    wins = WaveSignal.query.filter_by(status='hit_target').count()
    losses = WaveSignal.query.filter_by(status='hit_stop').count()
    active_count = WaveSignal.query.filter_by(status='active').count()

    return jsonify({
        'summary': {
            'total_signals': total,
            'active': active_count,
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        },
        'active_signals': [s.to_dict() for s in active],
        'recent_closed': [s.to_dict() for s in closed],
        'pattern_stats': [s.to_dict() for s in stats],
    })
