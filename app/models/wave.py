"""Wave pattern signal tracking models.

Tables:
- wave_signals: 감지된 패턴 시그널 (매일 스크리너에서 자동 적재)
- wave_tracking: 시그널 발생 후 일별 가격 추적 (수익률 트래킹)
- wave_pattern_stats: 패턴 타입별 누적 통계 (승률, 평균 수익)
"""

from datetime import datetime, timezone
from app.models import db


class WaveSignal(db.Model):
    """감지된 Wave 패턴 시그널."""
    __tablename__ = 'wave_signals'

    id = db.Column(db.Integer, primary_key=True)

    # 종목 정보
    ticker = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    market = db.Column(db.String(10), default='KR')

    # 패턴 정보
    pattern_class = db.Column(db.String(5), nullable=False)       # 'W' or 'M'
    wave_type = db.Column(db.String(50), nullable=False, index=True)  # e.g. 'HEAD_SHOULDERS'
    wave_label = db.Column(db.String(50), nullable=False)          # Korean label
    confidence = db.Column(db.Integer, nullable=False)              # 0-100
    completion_pct = db.Column(db.Float, default=0)
    bullish_bias = db.Column(db.Float, default=0)                  # -1.0 ~ 1.0
    volume_confirmed = db.Column(db.Boolean, default=False)

    # 가격 정보 (시그널 발생 시점)
    signal_price = db.Column(db.Float, nullable=False)             # 감지 당시 가격
    neckline_price = db.Column(db.Float, nullable=False)
    neckline_distance_pct = db.Column(db.Float, default=0)         # 넥라인까지 거리 %
    entry_price = db.Column(db.Float, nullable=True)               # 진입가 (넥라인 돌파)
    stop_price = db.Column(db.Float, nullable=True)                # 손절가
    target_price = db.Column(db.Float, nullable=True)              # 목표가 (측정 이동)

    # 결과 추적
    status = db.Column(db.String(20), default='active', index=True)
    # active: 모니터링 중
    # hit_target: 목표가 도달 (승)
    # hit_stop: 손절가 도달 (패)
    # neckline_break: 넥라인 돌파 (확인형 진입)
    # expired: 30일 경과 미돌파
    # invalidated: 패턴 무효화

    exit_price = db.Column(db.Float, nullable=True)                # 최종 청산 가격
    return_pct = db.Column(db.Float, nullable=True)                # 최종 수익률
    holding_days = db.Column(db.Integer, nullable=True)            # 보유 기간
    max_gain_pct = db.Column(db.Float, nullable=True)              # 보유 중 최대 이익
    max_loss_pct = db.Column(db.Float, nullable=True)              # 보유 중 최대 손실

    # 타임스탬프
    detected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    signal_date = db.Column(db.String(10), nullable=False, index=True)  # 'YYYY-MM-DD'
    closed_at = db.Column(db.DateTime, nullable=True)

    # P1-P5 포인트 (JSON 문자열)
    points_json = db.Column(db.Text, nullable=True)

    # 관계
    tracking = db.relationship('WaveTracking', backref='signal', lazy='dynamic',
                               cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'ticker': self.ticker,
            'name': self.name,
            'market': self.market,
            'pattern_class': self.pattern_class,
            'wave_type': self.wave_type,
            'wave_label': self.wave_label,
            'confidence': self.confidence,
            'completion_pct': self.completion_pct,
            'bullish_bias': self.bullish_bias,
            'volume_confirmed': self.volume_confirmed,
            'signal_price': self.signal_price,
            'neckline_price': self.neckline_price,
            'neckline_distance_pct': self.neckline_distance_pct,
            'entry_price': self.entry_price,
            'stop_price': self.stop_price,
            'target_price': self.target_price,
            'status': self.status,
            'exit_price': self.exit_price,
            'return_pct': self.return_pct,
            'holding_days': self.holding_days,
            'max_gain_pct': self.max_gain_pct,
            'max_loss_pct': self.max_loss_pct,
            'signal_date': self.signal_date,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
        }


class WaveTracking(db.Model):
    """시그널 발생 후 일별 가격 추적."""
    __tablename__ = 'wave_tracking'

    id = db.Column(db.Integer, primary_key=True)
    signal_id = db.Column(db.Integer, db.ForeignKey('wave_signals.id'), nullable=False, index=True)
    date = db.Column(db.String(10), nullable=False)        # 'YYYY-MM-DD'
    close_price = db.Column(db.Float, nullable=False)
    pnl_pct = db.Column(db.Float, default=0)               # 시그널 가격 대비 수익률
    days_since = db.Column(db.Integer, default=0)           # 감지 이후 경과 일수
    neckline_broken = db.Column(db.Boolean, default=False)  # 넥라인 돌파 여부


class WavePatternStats(db.Model):
    """패턴 타입별 누적 통계 (집계 테이블)."""
    __tablename__ = 'wave_pattern_stats'

    id = db.Column(db.Integer, primary_key=True)
    wave_type = db.Column(db.String(50), unique=True, nullable=False, index=True)
    wave_label = db.Column(db.String(50), nullable=False)
    pattern_class = db.Column(db.String(5), nullable=False)

    # 집계
    total_count = db.Column(db.Integer, default=0)          # 총 감지 횟수
    win_count = db.Column(db.Integer, default=0)            # 목표가 도달 횟수
    loss_count = db.Column(db.Integer, default=0)           # 손절 횟수
    active_count = db.Column(db.Integer, default=0)         # 활성 시그널

    # 수익률
    avg_return_pct = db.Column(db.Float, default=0)         # 평균 수익률
    best_return_pct = db.Column(db.Float, default=0)        # 최고 수익률
    worst_return_pct = db.Column(db.Float, default=0)       # 최저 수익률
    avg_holding_days = db.Column(db.Float, default=0)       # 평균 보유 기간

    # 신뢰도
    win_rate = db.Column(db.Float, default=0)               # 승률 (0-100)
    avg_confidence = db.Column(db.Float, default=0)         # 평균 AI 신뢰도

    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'wave_type': self.wave_type,
            'wave_label': self.wave_label,
            'pattern_class': self.pattern_class,
            'total_count': self.total_count,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'active_count': self.active_count,
            'win_rate': self.win_rate,
            'avg_return_pct': self.avg_return_pct,
            'best_return_pct': self.best_return_pct,
            'worst_return_pct': self.worst_return_pct,
            'avg_holding_days': self.avg_holding_days,
            'avg_confidence': self.avg_confidence,
        }
