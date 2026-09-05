"""SQLite 저장소 — 단일 파일, JSON 컬럼 기반.

스레드 안전(락) + WAL. 모든 모델은 `data` JSON 컬럼에 통째로 저장하고
검색용 컬럼만 별도 인덱스한다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from studio.models import (
    AffiliateLink,
    BlogPost,
    Campaign,
    EarningsEntry,
    Job,
    Product,
    VideoAsset,
    VideoScript,
)
from studio.utils import now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY, name TEXT, source TEXT, status TEXT,
    data TEXT NOT NULL, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, title TEXT, url TEXT UNIQUE, product_id TEXT,
    data TEXT NOT NULL, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS contents (
    id TEXT PRIMARY KEY, product_id TEXT, kind TEXT, title TEXT, seo_score INTEGER,
    data TEXT NOT NULL, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_contents_product ON contents(product_id, kind);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY, product_id TEXT, script_id TEXT, path TEXT,
    data TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, type TEXT, status TEXT, progress INTEGER,
    data TEXT NOT NULL, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS earnings (
    id TEXT PRIMARY KEY, date TEXT, product_id TEXT, content_id TEXT, channel TEXT,
    clicks INTEGER, orders INTEGER, revenue INTEGER, commission INTEGER,
    data TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY, product_id TEXT, network TEXT, url TEXT,
    data TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT);
"""


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


class Store:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.DatabaseError:
                    pass
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ helpers
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)).fetchall())

    # ------------------------------------------------------------ products
    def save_product(self, product: Product) -> Product:
        product.updated_at = now_iso()
        self._exec(
            "INSERT INTO products(id,name,source,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, source=excluded.source, status=excluded.status, "
            "data=excluded.data, updated_at=excluded.updated_at",
            (product.id, product.name, product.source, product.status, _dumps(product.to_dict()),
             product.created_at, product.updated_at),
        )
        return product

    def get_product(self, product_id: str) -> Product | None:
        rows = self._rows("SELECT data FROM products WHERE id=?", (product_id,))
        return Product.from_dict(_loads(rows[0]["data"])) if rows else None

    def find_product_by_url(self, url: str) -> Product | None:
        if not url:
            return None
        for row in self._rows("SELECT data FROM products"):
            d = _loads(row["data"])
            if url in (d.get("source_url"), d.get("product_url")):
                return Product.from_dict(d)
        return None

    def list_products(self, status: str | None = None, limit: int = 500) -> list[Product]:
        if status:
            rows = self._rows("SELECT data FROM products WHERE status=? ORDER BY updated_at DESC LIMIT ?", (status, limit))
        else:
            rows = self._rows("SELECT data FROM products ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [Product.from_dict(_loads(r["data"])) for r in rows]

    def delete_product(self, product_id: str) -> None:
        self._exec("DELETE FROM products WHERE id=?", (product_id,))
        self._exec("DELETE FROM contents WHERE product_id=?", (product_id,))
        self._exec("DELETE FROM videos WHERE product_id=?", (product_id,))
        self._exec("DELETE FROM links WHERE product_id=?", (product_id,))
        self._exec("UPDATE campaigns SET product_id='' WHERE product_id=?", (product_id,))

    # ------------------------------------------------------------ campaigns
    def save_campaigns(self, campaigns: Iterable[Campaign]) -> int:
        n = 0
        for c in campaigns:
            existing = self._rows("SELECT id, product_id FROM campaigns WHERE url=?", (c.url,)) if c.url else []
            if existing:
                c.id = existing[0]["id"]
                if not c.product_id:
                    c.product_id = existing[0]["product_id"] or ""
            self._exec(
                "INSERT INTO campaigns(id,title,url,product_id,data,fetched_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url, product_id=excluded.product_id, "
                "data=excluded.data, fetched_at=excluded.fetched_at",
                (c.id, c.title, c.url or None, c.product_id, _dumps(c.to_dict()), c.fetched_at),
            )
            n += 1
        return n

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        rows = self._rows("SELECT data FROM campaigns WHERE id=?", (campaign_id,))
        return Campaign.from_dict(_loads(rows[0]["data"])) if rows else None

    def list_campaigns(self, limit: int = 500) -> list[Campaign]:
        rows = self._rows("SELECT data FROM campaigns ORDER BY fetched_at DESC LIMIT ?", (limit,))
        return [Campaign.from_dict(_loads(r["data"])) for r in rows]

    def clear_campaigns(self) -> None:
        self._exec("DELETE FROM campaigns")

    # ------------------------------------------------------------ contents
    def save_content(self, content: BlogPost | VideoScript) -> BlogPost | VideoScript:
        content.updated_at = now_iso()
        score = getattr(content, "seo_score", 0) or 0
        self._exec(
            "INSERT INTO contents(id,product_id,kind,title,seo_score,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET product_id=excluded.product_id, kind=excluded.kind, title=excluded.title, "
            "seo_score=excluded.seo_score, data=excluded.data, updated_at=excluded.updated_at",
            (content.id, content.product_id, content.kind, content.title, int(score), _dumps(content.to_dict()),
             content.created_at, content.updated_at),
        )
        return content

    @staticmethod
    def _content_from_row(row: sqlite3.Row) -> BlogPost | VideoScript:
        d = _loads(row["data"])
        if d.get("kind") == "script":
            return VideoScript.from_dict(d)
        return BlogPost.from_dict(d)

    def get_content(self, content_id: str) -> BlogPost | VideoScript | None:
        rows = self._rows("SELECT data FROM contents WHERE id=?", (content_id,))
        return self._content_from_row(rows[0]) if rows else None

    def list_contents(self, product_id: str | None = None, kind: str | None = None, limit: int = 500) -> list[BlogPost | VideoScript]:
        sql = "SELECT data FROM contents WHERE 1=1"
        params: list[Any] = []
        if product_id:
            sql += " AND product_id=?"
            params.append(product_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [self._content_from_row(r) for r in self._rows(sql, params)]

    def latest_content(self, product_id: str, kind: str) -> BlogPost | VideoScript | None:
        items = self.list_contents(product_id=product_id, kind=kind, limit=1)
        return items[0] if items else None

    def delete_content(self, content_id: str) -> None:
        self._exec("DELETE FROM contents WHERE id=?", (content_id,))

    # ------------------------------------------------------------ videos
    def save_video(self, video: VideoAsset) -> VideoAsset:
        self._exec(
            "INSERT INTO videos(id,product_id,script_id,path,data,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET product_id=excluded.product_id, script_id=excluded.script_id, "
            "path=excluded.path, data=excluded.data",
            (video.id, video.product_id, video.script_id, video.path, _dumps(video.to_dict()), video.created_at),
        )
        return video

    def get_video(self, video_id: str) -> VideoAsset | None:
        rows = self._rows("SELECT data FROM videos WHERE id=?", (video_id,))
        return VideoAsset.from_dict(_loads(rows[0]["data"])) if rows else None

    def list_videos(self, product_id: str | None = None, limit: int = 500) -> list[VideoAsset]:
        if product_id:
            rows = self._rows("SELECT data FROM videos WHERE product_id=? ORDER BY created_at DESC LIMIT ?", (product_id, limit))
        else:
            rows = self._rows("SELECT data FROM videos ORDER BY created_at DESC LIMIT ?", (limit,))
        return [VideoAsset.from_dict(_loads(r["data"])) for r in rows]

    def delete_video(self, video_id: str) -> None:
        self._exec("DELETE FROM videos WHERE id=?", (video_id,))

    # ------------------------------------------------------------ jobs
    def save_job(self, job: Job) -> Job:
        job.updated_at = now_iso()
        self._exec(
            "INSERT INTO jobs(id,type,status,progress,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET type=excluded.type, status=excluded.status, progress=excluded.progress, "
            "data=excluded.data, updated_at=excluded.updated_at",
            (job.id, job.type, job.status, job.progress, _dumps(job.to_dict()), job.created_at, job.updated_at),
        )
        return job

    def get_job(self, job_id: str) -> Job | None:
        rows = self._rows("SELECT data FROM jobs WHERE id=?", (job_id,))
        return Job.from_dict(_loads(rows[0]["data"])) if rows else None

    def list_jobs(self, limit: int = 50, active_only: bool = False) -> list[Job]:
        if active_only:
            rows = self._rows("SELECT data FROM jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            rows = self._rows("SELECT data FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [Job.from_dict(_loads(r["data"])) for r in rows]

    def mark_stale_jobs_failed(self) -> int:
        """서버 재시작 시 남아있는 running/queued 작업 정리."""
        stale = self.list_jobs(limit=1000, active_only=True)
        for job in stale:
            job.status = "failed"
            job.error = job.error or "서버 재시작으로 중단됨"
            self.save_job(job)
        return len(stale)

    # ------------------------------------------------------------ earnings
    def add_earning(self, entry: EarningsEntry) -> EarningsEntry:
        self._exec(
            "INSERT INTO earnings(id,date,product_id,content_id,channel,clicks,orders,revenue,commission,data,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET date=excluded.date, product_id=excluded.product_id, "
            "content_id=excluded.content_id, channel=excluded.channel, clicks=excluded.clicks, orders=excluded.orders, "
            "revenue=excluded.revenue, commission=excluded.commission, data=excluded.data",
            (entry.id, entry.date, entry.product_id, entry.content_id, entry.channel, entry.clicks, entry.orders,
             entry.revenue, entry.commission, _dumps(entry.to_dict()), entry.created_at),
        )
        return entry

    def list_earnings(self, product_id: str | None = None, limit: int = 2000) -> list[EarningsEntry]:
        if product_id:
            rows = self._rows("SELECT data FROM earnings WHERE product_id=? ORDER BY date DESC, created_at DESC LIMIT ?", (product_id, limit))
        else:
            rows = self._rows("SELECT data FROM earnings ORDER BY date DESC, created_at DESC LIMIT ?", (limit,))
        return [EarningsEntry.from_dict(_loads(r["data"])) for r in rows]

    def delete_earning(self, entry_id: str) -> None:
        self._exec("DELETE FROM earnings WHERE id=?", (entry_id,))

    # ------------------------------------------------------------ links
    def add_link(self, link: AffiliateLink) -> AffiliateLink:
        self._exec(
            "INSERT INTO links(id,product_id,network,url,data,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET product_id=excluded.product_id, network=excluded.network, url=excluded.url, data=excluded.data",
            (link.id, link.product_id, link.network, link.url, _dumps(link.to_dict()), link.created_at),
        )
        return link

    def list_links(self, product_id: str | None = None) -> list[AffiliateLink]:
        if product_id:
            rows = self._rows("SELECT data FROM links WHERE product_id=? ORDER BY created_at DESC", (product_id,))
        else:
            rows = self._rows("SELECT data FROM links ORDER BY created_at DESC")
        return [AffiliateLink.from_dict(_loads(r["data"])) for r in rows]

    def delete_link(self, link_id: str) -> None:
        self._exec("DELETE FROM links WHERE id=?", (link_id,))

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self._rows("SELECT value FROM settings WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except ValueError:
            return rows[0]["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, _dumps(value)),
        )

    def all_settings(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for row in self._rows("SELECT key, value FROM settings"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                out[row["key"]] = row["value"]
        return out

    # ------------------------------------------------------------ stats
    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            rows = self._rows(sql)
            return int(rows[0][0]) if rows else 0

        return {
            "products": one("SELECT COUNT(*) FROM products"),
            "campaigns": one("SELECT COUNT(*) FROM campaigns"),
            "blogs": one("SELECT COUNT(*) FROM contents WHERE kind='blog'"),
            "scripts": one("SELECT COUNT(*) FROM contents WHERE kind='script'"),
            "videos": one("SELECT COUNT(*) FROM videos"),
            "earnings": one("SELECT COUNT(*) FROM earnings"),
            "active_jobs": one("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"),
        }
