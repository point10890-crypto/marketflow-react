# app/routes/__init__.py
"""Blueprint 등록"""

from flask import Blueprint


def register_blueprints(app):
    """모든 Blueprint를 Flask 앱에 등록"""

    # Main routes (pages)
    from app.routes.main import main_bp
    app.register_blueprint(main_bp)

    # Common API routes
    from app.routes.common import common_bp
    app.register_blueprint(common_bp, url_prefix='/api')

    # Crypto routes
    from app.routes.crypto import crypto_bp
    app.register_blueprint(crypto_bp, url_prefix='/api/crypto')

    # Auth routes
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    # Stripe routes
    from app.routes.stripe_routes import stripe_bp
    app.register_blueprint(stripe_bp, url_prefix='/api/stripe')

    print("All Blueprints registered")
