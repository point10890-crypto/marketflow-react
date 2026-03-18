# app/__init__.py
"""Flask 애플리케이션 팩토리"""

import os
from flask import Flask
from flask_cors import CORS
from app.models import db


def create_app(config=None):
    """Flask 앱 팩토리 함수"""
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    # 환경변수 로드
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("python-dotenv not installed")

    # 기본 설정
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'crypto-analytics-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.dirname(os.path.dirname(__file__))), 'data', 'users.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 설정 적용
    if config:
        app.config.update(config)

    # CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Database
    db.init_app(app)
    with app.app_context():
        from app.models.user import User  # noqa: F401
        db.create_all()

    # Blueprint 등록
    from app.routes import register_blueprints
    register_blueprints(app)

    return app
