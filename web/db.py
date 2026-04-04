"""
web/db.py — SQLite job tracking for AutoVideo Dashboard
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "dashboard.db"


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                date                TEXT NOT NULL,
                triggered_by        TEXT DEFAULT 'manual',
                topic               TEXT,
                lang                TEXT DEFAULT 'zh-TW',
                platforms           TEXT DEFAULT 'youtube,instagram',
                status              TEXT DEFAULT 'queued',
                step_news           TEXT DEFAULT 'pending',
                step_screenshot     TEXT DEFAULT 'pending',
                step_audio          TEXT DEFAULT 'pending',
                step_video          TEXT DEFAULT 'pending',
                step_upload         TEXT DEFAULT 'pending',
                output_path         TEXT,
                log_path            TEXT,
                error               TEXT,
                tokens_used         INTEGER DEFAULT 0,
                selected_cache_ids  TEXT DEFAULT '',
                started_at          TEXT,
                finished_at         TEXT,
                created_at          TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS news_cache (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                topic               TEXT NOT NULL DEFAULT '',
                lang                TEXT NOT NULL DEFAULT 'zh-TW',
                fetch_date          TEXT NOT NULL,
                title               TEXT NOT NULL,
                summary             TEXT DEFAULT '',
                url                 TEXT NOT NULL,
                source              TEXT DEFAULT '',
                source_type         TEXT DEFAULT 'google',
                screenshot_blocked  INTEGER DEFAULT 0,
                created_at          TEXT NOT NULL
            );

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('schedule_hour',   '8'),
                ('schedule_minute', '0'),
                ('platforms',       'youtube,instagram'),
                ('skip_upload',     'false'),
                ('dry_run',         'false');
        """)
        # 遷移：為已存在的舊 DB 補欄位
        existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        new_cols = [
            ("step_screenshot",    "TEXT DEFAULT 'pending'"),
            ("tokens_used",        "INTEGER DEFAULT 0"),
            ("lang",               "TEXT DEFAULT 'zh-TW'"),
            ("selected_cache_ids", "TEXT DEFAULT ''"),
        ]
        for col, defn in new_cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {defn}")

        # news_cache 遷移
        nc_existing = {r[1] for r in conn.execute("PRAGMA table_info(news_cache)")}
        if "source_type" not in nc_existing:
            conn.execute("ALTER TABLE news_cache ADD COLUMN source_type TEXT DEFAULT 'google'")


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_job(date: str, triggered_by: str = "manual", topic: str = None,
               lang: str = "zh-TW", platforms: str = "youtube,instagram",
               selected_cache_ids: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO jobs (date, triggered_by, topic, lang, platforms, selected_cache_ids, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, triggered_by, topic, lang, platforms, selected_cache_ids, _now())
        )
        return cur.lastrowid


# ── News Cache ────────────────────────────────────────────────────────────────

def save_news_cache(topic: str, lang: str, items: list[dict]) -> list[int]:
    """將一批新聞存入快取，回傳各自的 id。item 可含 source_type 欄位"""
    today = datetime.now(timezone.utc).date().isoformat()
    now   = _now()
    ids   = []
    with get_conn() as conn:
        for item in items:
            src_type = item.get("source_type", "google")
            cur = conn.execute(
                """INSERT INTO news_cache (topic, lang, fetch_date, title, summary, url, source, source_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (topic or "", lang, today,
                 item.get("title", ""), item.get("summary", "")[:300],
                 item.get("url", ""), item.get("source", ""), src_type, now)
            )
            ids.append(cur.lastrowid)
    return ids


def get_cached_news(topic: str, lang: str, date: str) -> list[dict] | None:
    """今天同 topic+lang 有快取就回傳（非封鎖優先），否則 None"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM news_cache
               WHERE topic=? AND lang=? AND fetch_date=?
               ORDER BY screenshot_blocked ASC, id ASC""",
            (topic or "", lang, date)
        ).fetchall()
        return [dict(r) for r in rows] if rows else None


def get_cache_item(cache_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM news_cache WHERE id=?", (cache_id,)).fetchone()
        return dict(row) if row else None


def get_job_candidates(job_id: int) -> list[dict]:
    """回傳此 job 同日期未被選用的候選新聞（被封鎖的排在最後）

    注意：cache key 現在是 "keyword|source1|source2" 格式，
    無法用 job.topic 精確匹配，改用 lang + fetch_date 廣查，
    確保跨來源的候選新聞都能出現。
    """
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return []
        job = dict(job)
        selected = {
            int(x) for x in (job.get("selected_cache_ids") or "").split(",") if x.strip()
        }
        rows = conn.execute(
            """SELECT * FROM news_cache
               WHERE lang=? AND fetch_date=?
               ORDER BY screenshot_blocked ASC, id ASC""",
            (job.get("lang", "zh-TW"), job.get("date", ""))
        ).fetchall()
        return [dict(r) for r in rows if r["id"] not in selected]


def mark_news_blocked(cache_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE news_cache SET screenshot_blocked=1 WHERE id=?", (cache_id,))


def mark_news_blocked_by_url(url: str):
    with get_conn() as conn:
        conn.execute("UPDATE news_cache SET screenshot_blocked=1 WHERE url=?", (url,))


def update_job(job_id: int, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)


def get_job(job_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 30, status: str = None) -> list[dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    with get_conn() as conn:
        total  = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        done   = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0]
        last   = conn.execute("SELECT date FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "total": total, "done": done, "failed": failed,
            "running": conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0],
            "success_rate": round(done / total * 100, 1) if total else 0,
            "last_run_date": last[0] if last else None,
        }


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))


def get_all_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r[0]: r[1] for r in rows}
