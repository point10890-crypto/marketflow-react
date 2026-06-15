"""aibain overview route registration + delegation."""
from flask import Flask
from app.routes.admin_mirofish import admin_mirofish_bp


def test_aibain_overview_route_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/admin/mirofish/aibain/overview' in rules


def test_aibain_overview_callable():
    import app.routes.admin_mirofish as route_mod
    assert callable(route_mod.aibain_overview)
