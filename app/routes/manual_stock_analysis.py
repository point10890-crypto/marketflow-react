"""Manual stock-analysis service routes."""

from __future__ import annotations

from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from app.auth.decorators import pro_required
from app.services import manual_stock_analysis as service


manual_stock_analysis_bp = Blueprint("manual_stock_analysis", __name__)


@manual_stock_analysis_bp.route("/runs", methods=["GET"])
@pro_required
def list_manual_runs():
    return jsonify({
        "runs": service.list_runs(),
        "result_filters": service.RESULT_ORDER,
    })


@manual_stock_analysis_bp.route("/runs/source", methods=["POST"])
@pro_required
def create_pending_run():
    payload = request.get_json(silent=True) or {}
    try:
        max_rows = int(payload.get("max_rows") or 2500)
        run = service.create_pending_run_from_source(max_rows=max_rows)
        return jsonify({
            "run": {k: v for k, v in run.items() if k != "records"},
        })
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@manual_stock_analysis_bp.route("/runs/scrape", methods=["POST"])
@pro_required
def scrape_manual_run():
    payload = request.get_json(silent=True) or {}
    try:
        run = service.scrape_source_run(
            max_rows=int(payload.get("max_rows") or 20),
            xpath=(payload.get("xpath") or service.DEFAULT_INVESTING_XPATH),
            timeout_sec=int(payload.get("timeout_sec") or 10),
        )
        return jsonify({
            "run": {k: v for k, v in run.items() if k != "records"},
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@manual_stock_analysis_bp.route("/scraper-loop", methods=["GET"])
@pro_required
def get_scraper_loop():
    return jsonify(service.get_scraper_loop_status())


@manual_stock_analysis_bp.route("/scraper-loop/start", methods=["POST"])
@pro_required
def start_scraper_loop():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(service.start_scraper_loop(
            max_rows=int(payload.get("max_rows") or 20),
            interval_sec=int(payload.get("interval_sec") or 900),
            timeout_sec=int(payload.get("timeout_sec") or 10),
            xpath=(payload.get("xpath") or service.DEFAULT_INVESTING_XPATH),
        ))
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@manual_stock_analysis_bp.route("/scraper-loop/stop", methods=["POST"])
@pro_required
def stop_scraper_loop():
    return jsonify(service.stop_scraper_loop())


@manual_stock_analysis_bp.route("/runs/upload", methods=["POST"])
@pro_required
def upload_manual_result():
    file = request.files.get("file")
    if file is None:
        return jsonify({"error": "file 필드에 Excel 파일을 업로드해 주세요."}), 400
    try:
        run = service.save_uploaded_result(file)
        return jsonify({
            "run": {k: v for k, v in run.items() if k != "records"},
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@manual_stock_analysis_bp.route("/runs/<run_id>", methods=["GET"])
@pro_required
def get_manual_run(run_id: str):
    try:
        return jsonify(service.get_run(
            run_id,
            result=request.args.get("result", "all"),
            q=request.args.get("q", ""),
        ))
    except FileNotFoundError:
        return jsonify({"error": "manual run not found"}), 404


@manual_stock_analysis_bp.route("/runs/<run_id>/export", methods=["GET"])
@pro_required
def export_manual_run(run_id: str):
    try:
        payload, filename = service.run_to_excel_bytes(
            run_id,
            result=request.args.get("result", "all"),
            q=request.args.get("q", ""),
        )
    except FileNotFoundError:
        return jsonify({"error": "manual run not found"}), 404
    return send_file(
        BytesIO(payload),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )
