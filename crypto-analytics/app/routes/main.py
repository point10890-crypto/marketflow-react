# app/routes/main.py
"""메인 페이지 라우트"""

from flask import Blueprint, render_template, redirect, url_for

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """메인 인덱스 페이지"""
    return render_template('index.html')


@main_bp.route('/app')
def dashboard():
    """대시보드 페이지"""
    return render_template('dashboard.html')


@main_bp.route('/dividend')
def dividend_page():
    """배당 옵티마이저 페이지"""
    return render_template('dividend.html')


# Legacy routes - redirect to main dashboard
@main_bp.route('/kr-overview')
def kr_overview():
    """Redirect to main dashboard"""
    return redirect(url_for('main.dashboard'))


@main_bp.route('/kr-vcp')
def kr_vcp():
    """Redirect to main dashboard"""
    return redirect(url_for('main.dashboard'))


# @main_bp.route('/closing-bet')
# def closing_bet():
#     """종가베팅 - standalone page (kept for direct access)"""
#     # return render_template('closing_bet.html')
#     pass
