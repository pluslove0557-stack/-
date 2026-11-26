"""SQLite 저장소 - 설정, 소싱 후보, 내 판매이력. 1인용 로컬 DB(data/sourcing.db)."""

import json
import os
import sqlite3
import time

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT '후보',
  data TEXT NOT NULL,
  memo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS niches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT '검증중',
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""

STATUSES = ["후보", "선정", "등록완료", "보류", "제외"]


def db():
    if "db" not in g:
        path = current_app.config["DB_PATH"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.executescript(SCHEMA)
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# --- settings ---------------------------------------------------------------
def get_settings(defaults):
    rows = db().execute("SELECT key, value FROM settings").fetchall()
    saved = {r["key"]: json.loads(r["value"]) for r in rows}
    return {**defaults, **saved}


def save_settings(values):
    conn = db()
    for k, v in values.items():
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, json.dumps(v)))
    conn.commit()


# --- candidates -------------------------------------------------------------
def add_candidates(items):
    conn = db()
    now = time.time()
    existing = {
        json.loads(r["data"]).get("asin")
        for r in conn.execute("SELECT data FROM candidates").fetchall()
    }
    added, skipped = 0, 0
    for it in items:
        if it.get("asin") and it["asin"] in existing:
            skipped += 1
            continue
        conn.execute("INSERT INTO candidates(created_at, data) VALUES(?, ?)", (now, json.dumps(it, ensure_ascii=False)))
        if it.get("asin"):
            existing.add(it["asin"])
        added += 1
    conn.commit()
    return added, skipped


def list_candidates(status=None):
    q = "SELECT * FROM candidates"
    args = ()
    if status:
        q += " WHERE status = ?"
        args = (status,)
    rows = db().execute(q + " ORDER BY id DESC", args).fetchall()
    return [{"id": r["id"], "status": r["status"], "memo": r["memo"], **json.loads(r["data"])} for r in rows]


def get_candidate(cid):
    r = db().execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "status": r["status"], "memo": r["memo"], **json.loads(r["data"])}


def update_candidate(cid, data=None, status=None, memo=None):
    conn = db()
    if data is not None:
        clean = {k: v for k, v in data.items() if k not in ("id", "status", "memo")}
        conn.execute("UPDATE candidates SET data = ? WHERE id = ?", (json.dumps(clean, ensure_ascii=False), cid))
    if status is not None:
        conn.execute("UPDATE candidates SET status = ? WHERE id = ?", (status, cid))
    if memo is not None:
        conn.execute("UPDATE candidates SET memo = ? WHERE id = ?", (memo, cid))
    conn.commit()


def delete_candidate(cid):
    conn = db()
    conn.execute("DELETE FROM candidates WHERE id = ?", (cid,))
    conn.commit()


# --- sales history ----------------------------------------------------------
def add_sales(titles):
    conn = db()
    now = time.time()
    n = 0
    for t in titles:
        t = (t or "").strip()
        if t:
            conn.execute("INSERT INTO sales(title, created_at) VALUES(?, ?)", (t, now))
            n += 1
    conn.commit()
    return n


def sales_titles():
    return [r["title"] for r in db().execute("SELECT title FROM sales ORDER BY id DESC").fetchall()]


def clear_sales():
    conn = db()
    conn.execute("DELETE FROM sales")
    conn.commit()


# --- niches (수요 먼저 → 자체 브랜드) ----------------------------------------
NICHE_STATUSES = ["검증중", "유망", "샘플주문", "런칭", "보류"]


def add_niche(data):
    conn = db()
    cur = conn.execute("INSERT INTO niches(created_at, data) VALUES(?, ?)",
                       (time.time(), json.dumps(data, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def list_niches():
    rows = db().execute("SELECT * FROM niches ORDER BY id DESC").fetchall()
    return [{"id": r["id"], "status": r["status"], **json.loads(r["data"])} for r in rows]


def get_niche(nid):
    r = db().execute("SELECT * FROM niches WHERE id = ?", (nid,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "status": r["status"], **json.loads(r["data"])}


def update_niche(nid, data=None, status=None):
    conn = db()
    if data is not None:
        clean = {k: v for k, v in data.items() if k not in ("id", "status")}
        conn.execute("UPDATE niches SET data = ? WHERE id = ?", (json.dumps(clean, ensure_ascii=False), nid))
    if status is not None:
        conn.execute("UPDATE niches SET status = ? WHERE id = ?", (status, nid))
    conn.commit()


def delete_niche(nid):
    conn = db()
    conn.execute("DELETE FROM niches WHERE id = ?", (nid,))
    conn.commit()
