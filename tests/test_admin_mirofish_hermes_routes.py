from __future__ import annotations

from flask import Flask

from app.routes.admin_mirofish_hermes import admin_mirofish_hermes_bp


def test_hermes_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_hermes_bp, url_prefix='/api/admin/mirofish')
    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/hermes/status' in rules
    assert '/api/admin/mirofish/hermes/manifest' in rules
    assert '/api/admin/mirofish/hermes/runbook' in rules
    assert '/api/admin/mirofish/hermes/prompt-pack' in rules
    assert '/api/admin/mirofish/hermes/preview' in rules
