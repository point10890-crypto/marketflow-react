import time
from pathlib import Path

import pytest
from conftest import fixture_uri, requires_browser, requires_ffmpeg

from studio.db import Store
from studio.jobs import JobRunner
from studio.pipeline import Pipeline
from studio.web.app import create_app


@pytest.fixture
def app_ctx(settings):
    store = Store(settings.db_path)
    runner = JobRunner(store)
    pipeline = Pipeline(settings, store)
    app = create_app(settings, store, runner, pipeline)
    app.testing = True
    yield app.test_client(), store, runner, pipeline
    store.close()


def _wait(runner, job_id, timeout=180):
    job = runner.wait(job_id, timeout=timeout)
    assert job is not None and job.status == "done", (job.status, job.error, job.message)
    return job


def test_doctor_and_manual_flow(app_ctx, sample_image):
    client, store, runner, pipeline = app_ctx
    report = pipeline.doctor()
    assert report["llm_mode"] == "template" and "counts" in report
    r = client.get("/api/status")
    assert r.status_code == 200 and r.json["version"]
    assert client.get("/").status_code == 200
    r = client.post("/api/products/manual", json={"name": "수동 상품", "brand": "브랜드", "price": "19,900", "features": "특징1\n특징2", "commission_rate": 8})
    assert r.status_code == 201
    pid = r.json["product"]["id"]
    p = store.get_product(pid)
    p.screenshots = [sample_image]
    store.save_product(p)
    job = _wait(runner, client.post(f"/api/products/{pid}/blog", json={}).json["job"]["id"], timeout=60)
    assert job.result["content"]["seo_score"] >= 70
    cid = job.result["content"]["id"]
    r = client.put(f"/api/contents/{cid}", json={"title": "짧은제목", "hashtags": "#a #b"})
    assert r.json["content"]["hashtags"] == ["#a", "#b"] and r.json["content"]["seo_score"] < job.result["content"]["seo_score"]
    job = _wait(runner, client.post(f"/api/products/{pid}/script", json={"format": "review"}).json["job"]["id"], timeout=60)
    sid = job.result["content"]["id"]
    scenes = job.result["content"]["scenes"]
    scenes[0]["narration"] = "수정된 훅"
    r = client.put(f"/api/contents/{sid}", json={"scenes": scenes, "title": "새 제목"})
    assert r.json["content"]["scenes"][0]["narration"] == "수정된 훅" and r.json["content"]["title"] == "새 제목"
    job = _wait(runner, client.post(f"/api/products/{pid}/package", json={}).json["job"]["id"], timeout=60)
    assert "CHECKLIST.md" in job.result["files"] and client.get("/api/packages").json["packages"]
    assert client.get("/api/products/does-not-exist").status_code == 404
    assert client.post("/api/products/import", json={"url": "ftp://x"}).status_code == 400
    assert client.get("/files/../../etc/passwd").status_code == 404
    assert client.get("/api/nothing").status_code == 404
    r = client.post("/api/earnings", json={"date": "2026-09-01", "product_id": pid, "channel": "naver_blog", "clicks": 10, "orders": 1, "revenue": "19,900", "commission": "1,592"})
    assert r.status_code == 201
    assert client.post("/api/earnings/import", json={"csv": "날짜,채널,클릭,수수료\n2026-09-02,클립,3,100\n"}).json["imported"] == 1
    summary = client.get("/api/earnings/summary").json
    assert summary["totals"]["commission"] == 1692 and summary["counts"]["products"] == 1
    assert client.put("/api/settings", json={"blog_tone": "전문적인"}).json["runtime"]["blog_tone"] == "전문적인"
    assert pipeline.settings.blog_tone == "전문적인"
    assert client.put("/api/settings/selectors", json={"override": "{bad"}).status_code == 400
    assert client.put("/api/settings/selectors", json={"override": '{"list": {"item": ["li.x"]}}'}).json["effective"]["list"]["item"] == ["li.x"]
    assert client.post("/api/calculator", json={"price": 10000, "commission_rate": 10, "visits": 1000}).json["expected_commission"] == 1500
    assert client.post("/api/keywords/research", json={"query": "무선 청소기"}).json["keywords"]["primary"] == "무선 청소기"
    assert client.delete(f"/api/products/{pid}").status_code == 200
    assert client.get("/api/products").json["products"] == []


def test_job_runner_failure_and_cancel(store):
    runner = JobRunner(store)

    def boom(job, progress):
        progress("작업 중", 10)
        raise ValueError("의도된 실패")

    job = runner.wait(runner.submit("blog", {}, boom).id, timeout=20)
    assert job.status == "failed" and "의도된 실패" in job.error

    def slow(job, progress):
        for _ in range(50):
            progress("느린 작업")
            time.sleep(0.05)
        return {"ok": True}

    j = runner.submit("video", {}, slow)
    time.sleep(0.3)
    assert runner.cancel(j.id)
    assert runner.wait(j.id, timeout=20).status == "cancelled"


@requires_browser
def test_import_url_and_screenshots(app_ctx):
    client, store, runner, pipeline = app_ctx
    job = _wait(runner, client.post("/api/products/import", json={"url": fixture_uri("smartstore_product.html")}).json["job"]["id"])
    product = job.result["product"]
    assert product["name"] == "클린테크 무선 청소기 X1" and product["price"] == 299000
    assert len(product["media_urls"]) >= 3
    hero = client.get(product["media_urls"][0])
    assert hero.status_code == 200 and hero.content_type == "image/png"
    stored = store.get_product(product["id"])
    assert (Path(stored.screenshots[0]).parent / "page.html").exists()
    # 같은 URL 재수집 → 동일 ID 유지
    again = pipeline.import_url(fixture_uri("smartstore_product.html"), capture=False)
    assert again.id == stored.id
    # 브랜드커넥트 상세 픽스처 → 캠페인 파서 경로
    camp = pipeline.import_url("https://brandconnect.naver.com/creator/campaign/10001".replace("https://brandconnect.naver.com/creator/campaign/10001", fixture_uri("brandconnect_detail.html")), capture=False)
    assert camp.name and camp.source in ("url", "brandconnect")


@requires_browser
@requires_ffmpeg
def test_full_pipeline_offline(settings, store):
    pipeline = Pipeline(settings, store)
    result = pipeline.run_full(url=fixture_uri("generic_product.html"), fmt="shorts")
    assert result["seo_score"] >= 70 and Path(result["video_path"]).stat().st_size > 10000
    video = store.get_video(result["video_id"])
    assert video.duration > 20 and Path(video.srt).exists() and Path(video.thumbnail).exists()
    pkg = Path(result["package_dir"])
    assert (pkg / "CHECKLIST.md").exists() and any(pkg.glob("video/*.mp4"))
    assert store.get_product(result["product_id"]).status == "packaged"
