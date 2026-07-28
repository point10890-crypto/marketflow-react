"""AI Brain endpoints for the separate Goodrich TradingOS service."""

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_or_aibain_required
from app.services.mirofish import goodrich_client


admin_mirofish_goodrich_bp = Blueprint('admin_mirofish_goodrich', __name__)


def _call(action):
    try:
        return jsonify(action())
    except goodrich_client.GoodrichServiceError as exc:
        return jsonify({
            'error': str(exc),
            'service': 'goodrich-tradingos',
            'upstream_available': False,
        }), exc.status_code


@admin_mirofish_goodrich_bp.route('/goodrich/fund-manager', methods=['GET'])
@admin_or_aibain_required
def get_fund_manager():
    return _call(goodrich_client.get_fund_manager)


@admin_mirofish_goodrich_bp.route('/goodrich/fund-manager/research', methods=['POST'])
@admin_or_aibain_required
def run_fund_manager_research():
    return _call(goodrich_client.run_research)


@admin_mirofish_goodrich_bp.route('/goodrich/fund-manager/history', methods=['GET'])
@admin_or_aibain_required
def get_fund_manager_history():
    return _call(lambda: goodrich_client.get_detection_history(
        limit=request.args.get('limit', default=20, type=int),
        offset=request.args.get('offset', default=0, type=int),
    ))


@admin_mirofish_goodrich_bp.route('/goodrich/fund-manager/performance', methods=['GET'])
@admin_or_aibain_required
def get_fund_manager_performance():
    return _call(lambda: goodrich_client.get_performance(
        window_days=request.args.get('window_days', default=30, type=int),
    ))
