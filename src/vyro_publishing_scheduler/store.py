from __future__ import annotations

import math
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, content_id TEXT NOT NULL,
 video_url TEXT NOT NULL, caption TEXT NOT NULL, scheduled_at TEXT NOT NULL,
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
 lease_until TEXT, last_error TEXT, instagram_media_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 approved INTEGER NOT NULL DEFAULT 0, approved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, scheduled_at);
CREATE TABLE IF NOT EXISTS post_metrics (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id), captured_at TEXT NOT NULL,
 local_hour INTEGER NOT NULL, views REAL NOT NULL DEFAULT 0, reach REAL NOT NULL DEFAULT 0,
 shares REAL NOT NULL DEFAULT 0, saves REAL NOT NULL DEFAULT 0, comments REAL NOT NULL DEFAULT 0,
 profile_visits REAL NOT NULL DEFAULT 0, follows REAL NOT NULL DEFAULT 0, inquiries REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_metrics_hour ON post_metrics(local_hour);
"""


class QueueStore:
    def __init__(self, db_path: str | Path = "vyro_scheduler.sqlite3", timezone_name: str = "Asia/Jakarta"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tz = ZoneInfo(timezone_name)
        self.init()

    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def init(self):
        with self.connect() as con:
            con.executescript(SCHEMA)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)").fetchall()}
            if "approved" not in columns:
                con.execute("ALTER TABLE jobs ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
            if "approved_at" not in columns:
                con.execute("ALTER TABLE jobs ADD COLUMN approved_at TEXT")
            # Legacy scheduled jobs are held until an operator explicitly approves them.
            con.execute("UPDATE jobs SET status='PENDING_APPROVAL' WHERE status='SCHEDULED' AND approved=0")

    @staticmethod
    def _validate_url(video_url: str) -> None:
        parsed = urlsplit(video_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("video_url must be a public HTTPS URL without credentials or fragment")
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".localhost", ".internal")):
            raise ValueError("Internal media hosts are not allowed")

    def add_job(self, content_id, video_url, caption, scheduled_at, idempotency_key, max_attempts=3):
        self._validate_url(video_url)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}", str(content_id)) or ".." in content_id:
            raise ValueError("content_id format is invalid")
        if not idempotency_key or len(idempotency_key) > 160:
            raise ValueError("idempotency_key must contain 1-160 characters")
        if not isinstance(caption, str) or len(caption) > 2200:
            raise ValueError("caption must be a string of at most 2200 characters")
        if not 1 <= int(max_attempts) <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        dt = datetime.fromisoformat(scheduled_at)
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("scheduled_at must include a UTC offset")
        scheduled_utc = dt.astimezone(timezone.utc).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        job_id = str(uuid.uuid4())
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                expected = (content_id, video_url, caption, scheduled_utc)
                actual = (existing["content_id"], existing["video_url"], existing["caption"], existing["scheduled_at"])
                if actual != expected:
                    con.rollback()
                    raise ValueError("idempotency_key already exists with a different payload")
                con.commit()
                return existing["id"]
            con.execute(
                """INSERT INTO jobs(id,idempotency_key,content_id,video_url,caption,scheduled_at,status,max_attempts,created_at,updated_at,approved)
                VALUES(?,?,?,?,?,?,?,?,?,?,0)""",
                (job_id, idempotency_key, content_id, video_url, caption, scheduled_utc,
                 "PENDING_APPROVAL", max_attempts, now, now),
            )
            con.commit()
        return job_id

    def approve(self, job_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE jobs SET approved=1,approved_at=?,status='SCHEDULED',updated_at=? WHERE id=? AND status='PENDING_APPROVAL'",
                (now, now, job_id),
            )
            if cur.rowcount != 1:
                raise ValueError("Job tidak ditemukan atau bukan dalam status PENDING_APPROVAL")

    def revoke_approval(self, job_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE jobs SET approved=0,approved_at=NULL,status='PENDING_APPROVAL',updated_at=? WHERE id=? AND status IN ('SCHEDULED','PENDING_APPROVAL')",
                (now, job_id),
            )
            if cur.rowcount != 1:
                raise ValueError("Approval tidak dapat dicabut pada status job ini")

    def claim_due(self, limit=5, lease_seconds=300):
        limit = max(1, min(int(limit), 50))
        lease_seconds = max(30, min(int(lease_seconds), 3600))
        now = datetime.now(timezone.utc)
        now_s = now.isoformat()
        lease = (now + timedelta(seconds=lease_seconds)).isoformat()
        claimed = []
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                """UPDATE jobs SET status=CASE WHEN attempts>=max_attempts THEN 'FAILED' ELSE 'SCHEDULED' END,
                lease_until=NULL,updated_at=? WHERE status='PROCESSING' AND lease_until<? AND approved=1""",
                (now_s, now_s),
            )
            rows = con.execute(
                "SELECT id FROM jobs WHERE status='SCHEDULED' AND approved=1 AND scheduled_at<=? ORDER BY scheduled_at LIMIT ?",
                (now_s, limit),
            ).fetchall()
            for row in rows:
                cur = con.execute(
                    "UPDATE jobs SET status='PROCESSING',attempts=attempts+1,lease_until=?,updated_at=? WHERE id=? AND status='SCHEDULED' AND approved=1",
                    (lease, now_s, row["id"]),
                )
                if cur.rowcount:
                    claimed.append(dict(con.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()))
            con.commit()
        return claimed

    def complete(self, job_id, media_id):
        if not media_id or len(media_id) > 160:
            raise ValueError("media_id must contain 1-160 characters")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE jobs SET status='PUBLISHED',instagram_media_id=?,lease_until=NULL,last_error=NULL,updated_at=? WHERE id=? AND status='PROCESSING' AND approved=1",
                (media_id, now, job_id),
            )
            if cur.rowcount != 1:
                raise ValueError("Job is not in PROCESSING state, is not approved, or was not found")

    def fail(self, job_id, reason, retry_in=300):
        now = datetime.now(timezone.utc)
        now_s = now.isoformat()
        with self.connect() as con:
            row = con.execute("SELECT attempts,max_attempts,approved FROM jobs WHERE id=? AND status='PROCESSING'", (job_id,)).fetchone()
            if not row:
                raise ValueError("Job is not in PROCESSING state or was not found")
            if row["attempts"] >= row["max_attempts"]:
                con.execute("UPDATE jobs SET status='FAILED',last_error=?,lease_until=NULL,updated_at=? WHERE id=?", (str(reason)[:1500], now_s, job_id))
            else:
                retry_at = (now + timedelta(seconds=max(30, min(int(retry_in), 86400)))).isoformat()
                con.execute("UPDATE jobs SET status='SCHEDULED',scheduled_at=?,last_error=?,lease_until=NULL,updated_at=? WHERE id=? AND approved=1", (retry_at, str(reason)[:1500], now_s, job_id))

    def list_due(self, limit=25):
        with self.connect() as con:
            rows = con.execute("SELECT * FROM jobs ORDER BY scheduled_at LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
            return [dict(row) for row in rows]

    def add_metrics(self, job_id, scheduled_at, **metrics):
        dt = datetime.fromisoformat(scheduled_at)
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("scheduled_at must include a UTC offset")
        dt = dt.astimezone(self.tz)
        names = ("views", "reach", "shares", "saves", "comments", "profile_visits", "follows", "inquiries")
        allowed = {key: float(metrics.get(key, 0)) for key in names}
        if any(not math.isfinite(value) or value < 0 for value in allowed.values()):
            raise ValueError("Metrics must be finite and non-negative")
        with self.connect() as con:
            exists = con.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not exists:
                raise ValueError("Unknown job_id")
            con.execute(
                """INSERT INTO post_metrics(job_id,captured_at,local_hour,views,reach,shares,saves,comments,profile_visits,follows,inquiries)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, datetime.now(timezone.utc).isoformat(), dt.hour, *[allowed[name] for name in names]),
            )

    def recommend_slots(self, min_samples=5, prior_strength=5):
        with self.connect() as con:
            rows = con.execute(
                """SELECT local_hour,COUNT(*) n,SUM(views) views,SUM(reach) reach,SUM(shares) shares,
                SUM(saves) saves,SUM(comments) comments,SUM(profile_visits) profile_visits,
                SUM(follows) follows,SUM(inquiries) inquiries FROM post_metrics GROUP BY local_hour"""
            ).fetchall()
        if not rows:
            return {"status": "insufficient_data", "recommendations": [], "message": "Belum ada metrik konten."}

        def score(row):
            denominator = max(float(row["reach"] or 0), float(row["views"] or 0), 1.0)
            weighted = (4 * float(row["shares"] or 0) + 3 * float(row["saves"] or 0)
                        + 1.5 * float(row["comments"] or 0) + 2 * float(row["profile_visits"] or 0)
                        + 3 * float(row["follows"] or 0) + 6 * float(row["inquiries"] or 0))
            return weighted / denominator

        total_n = sum(int(row["n"]) for row in rows)
        global_rate = sum(score(row) * int(row["n"]) for row in rows) / max(total_n, 1)
        output = []
        for row in rows:
            n = int(row["n"])
            raw = score(row)
            adjusted = (n * raw + prior_strength * global_rate) / (n + prior_strength)
            output.append({
                "hour_wib": int(row["local_hour"]), "samples": n,
                "raw_score": round(raw, 6), "adjusted_score": round(adjusted, 6),
                "confidence": "moderate" if n >= min_samples else "low",
                "denominator": "max(reach, views, 1)",
            })
        output.sort(key=lambda item: item["adjusted_score"], reverse=True)
        enough = any(item["samples"] >= min_samples for item in output)
        return {
            "status": "ok" if enough else "insufficient_samples",
            "interpretation": "Eksplorasi performa akun sendiri; bukan sinyal ranking Instagram dan bukan jaminan viral.",
            "global_baseline": round(global_rate, 6), "recommendations": output,
        }

    def summary(self):
        with self.connect() as con:
            rows = con.execute("SELECT status,COUNT(*) n FROM jobs GROUP BY status").fetchall()
            total = con.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
        return {"total": total, "by_status": {row["status"]: row["n"] for row in rows}}
