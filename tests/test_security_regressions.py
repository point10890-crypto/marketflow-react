from flask import Flask

from app.routes.common import common_bp
from app.routes.community import community_bp


def test_system_update_stream_requires_admin_auth():
    app = Flask(__name__)
    app.register_blueprint(common_bp, url_prefix="/api")

    response = app.test_client().get("/api/system/update-data-stream")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_formula_uploads_are_not_served_from_public_upload_route():
    app = Flask(__name__)
    app.register_blueprint(community_bp, url_prefix="/api/community")

    response = app.test_client().get("/api/community/uploads/leaked.zip")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Use the protected download endpoint"
