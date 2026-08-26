# app/routes/__init__.py
"""Blueprint Registration"""


def register_blueprints(app):
    """Register all Blueprints"""

    # Common API routes
    from app.routes.common import common_bp
    app.register_blueprint(common_bp, url_prefix='/api')

    # KR Market routes
    from app.routes.kr_market import kr_bp
    app.register_blueprint(kr_bp, url_prefix='/api/kr')

    # US Market routes
    from app.routes.us_market import us_bp
    app.register_blueprint(us_bp, url_prefix='/api/us')

    # Crypto routes
    from app.routes.crypto import crypto_bp
    app.register_blueprint(crypto_bp, url_prefix='/api/crypto')

    # Economy routes
    from app.routes.econ import econ_bp
    app.register_blueprint(econ_bp, url_prefix='/api/econ')

    # Auth routes
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    # Admin routes
    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

    # Admin MiroFish routes
    from app.routes.admin_mirofish import admin_mirofish_bp
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    # AI Brain Goodrich TradingOS service boundary
    from app.routes.admin_mirofish_goodrich import admin_mirofish_goodrich_bp
    app.register_blueprint(admin_mirofish_goodrich_bp, url_prefix='/api/admin/mirofish')

    # Admin MiroFish K-Analyst analysis endpoints
    from app.routes.admin_mirofish_analysis import admin_mirofish_analysis_bp
    app.register_blueprint(admin_mirofish_analysis_bp, url_prefix='/api/admin/mirofish')

    # Admin MiroFish Hermes sidecar endpoints
    from app.routes.admin_mirofish_hermes import admin_mirofish_hermes_bp
    app.register_blueprint(admin_mirofish_hermes_bp, url_prefix='/api/admin/mirofish')

    # Admin MiroFish TradingAgents deep-verification endpoints
    from app.routes.admin_mirofish_tradingagents import admin_mirofish_tradingagents_bp
    app.register_blueprint(admin_mirofish_tradingagents_bp, url_prefix='/api/admin/mirofish')

    # Admin MiroFish GraphRAG analysis routes (Phase A: status)
    from app.routes.admin_mirofish_graphrag import admin_mirofish_graphrag_bp
    app.register_blueprint(admin_mirofish_graphrag_bp, url_prefix='/api/admin/mirofish/graphrag')

    # Admin MiroFish memory leak diagnostics (admin only, _debug prefix)
    from app.routes.admin_mirofish_debug import admin_mirofish_debug_bp
    app.register_blueprint(admin_mirofish_debug_bp, url_prefix='/api/admin/mirofish/_debug')

    # Stripe routes
    from app.routes.stripe_routes import stripe_bp
    app.register_blueprint(stripe_bp, url_prefix='/api/stripe')

    # Stock Analyzer routes (Investing.com ProPicks)
    from app.routes.stock_analyzer import stock_analyzer_bp
    app.register_blueprint(stock_analyzer_bp, url_prefix='/api/stock-analyzer')

    # Claw LIVE read-only overview (marketflow_claw) — 대시보드 폴링 전용
    from app.routes.kr_claw import kr_claw_bp
    app.register_blueprint(kr_claw_bp, url_prefix='/api/kr/claw')

    # Alpha Core paper ledger — authenticated GET-only projections
    from app.routes.kr_alpha_core import kr_alpha_core_bp
    app.register_blueprint(kr_alpha_core_bp, url_prefix='/api/kr/alpha-core')

    # Manual Stock Analysis routes (legacy Excel workflow as a service)
    from app.routes.manual_stock_analysis import manual_stock_analysis_bp
    app.register_blueprint(manual_stock_analysis_bp, url_prefix='/api/manual-stock-analysis')

    # Wave Pattern Detection routes
    from app.routes.wave import wave_bp
    app.register_blueprint(wave_bp, url_prefix='/api/wave')

    # AI Briefing routes (조간/마감 브리핑)
    from app.routes.briefing import briefing_bp
    app.register_blueprint(briefing_bp, url_prefix='/api/briefing')

    # Community routes
    from app.routes.community import community_bp
    app.register_blueprint(community_bp, url_prefix='/api/community')

    # Public community (read-only, no auth) — AdSense 심사용 공개 콘텐츠.
    # /api/public/ 프리픽스는 _GATED_PREFIXES 밖이어야 한다 (app/__init__.py).
    from app.routes.public_community import public_community_bp
    app.register_blueprint(public_community_bp, url_prefix='/api/public/community')

    print("[OK] Blueprints registered (KR + US + Crypto + Econ + Auth + Admin + MiroFish + Stripe + StockAnalyzer + ManualStockAnalysis + Wave + Briefing + Community)")
