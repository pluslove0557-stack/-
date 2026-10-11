"""샤오홍슈(小红书)/도우인(抖音) 영상 링크 수집함.

정책상 안전한 범위만 구현합니다.
- 사용자가 앱에서 '공유하기'로 복사한 링크/공유문구를 붙여넣으면 URL을 추출하고,
  공개 페이지의 메타정보(제목/썸네일/설명)를 1건씩 가져와 보관합니다.
- 검색결과 대량 크롤링, 로그인 우회, 워터마크 제거 영상 다운로드는 하지 않습니다.
- 레시피 / 상품 분류는 키워드 기반 규칙이며 수동 수정이 가능합니다.
"""
import csv
import io
import re
import sqlite3
import urllib.request
from html import unescape
from urllib.parse import urlparse

PLATFORM_HOSTS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
}
PLATFORM_LABEL = {"douyin": "도우인", "xiaohongshu": "샤오홍슈", "other": "기타"}

CATEGORY_LABEL = {"recipe": "레시피", "product": "상품", "other": "미분류"}
CATEGORY_KEYWORDS = {
    "recipe": ["食谱", "做法", "菜谱", "教程", "烘焙", "家常菜", "早餐", "减脂餐", "食材",
               "레시피", "요리", "만들기", "recipe", "cook"],
    "product": ["好物", "测评", "开箱", "推荐", "种草", "同款", "购物", "链接", "价格",
                "상품", "후기", "리뷰", "추천", "unboxing", "review"],
}

URL_RE = re.compile(r"https?://[^\s<>\"'，。）)】]+")
USER_AGENT = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE NOT NULL,
  platform TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'other',
  title TEXT DEFAULT '',
  description TEXT DEFAULT '',
  thumbnail TEXT DEFAULT '',
  tags TEXT DEFAULT '',
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def detect_platform(url):
    host = (urlparse(url).hostname or "").lower()
    for name, hosts in PLATFORM_HOSTS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return "other"


def extract_urls(text):
    """공유 문구 속에서 지원 플랫폼 URL만 중복 없이 추출."""
    seen, out = set(), []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;")
        if u not in seen and detect_platform(u) != "other":
            seen.add(u)
            out.append(u)
    return out


def classify(*texts):
    blob = " ".join(t for t in texts if t).lower()
    scores = {c: sum(1 for k in kws if k.lower() in blob) for c, kws in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _meta(html, prop):
    for pat in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)',
                rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']'):
        m = re.search(pat, html, re.I)
        if m:
            return unescape(m.group(1)).strip()
    return ""


def fetch_metadata(url, timeout=8):
    """공개 페이지의 og 메타만 읽음. 실패해도 예외 대신 빈 값 반환."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            html = resp.read(400_000).decode("utf-8", "ignore")
    except Exception:
        return {"final_url": url, "title": "", "description": "", "thumbnail": "", "ok": False}
    title = _meta(html, "og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = unescape(m.group(1)).strip() if m else ""
    return {
        "final_url": final_url,
        "title": title,
        "description": _meta(html, "og:description") or _meta(html, "description"),
        "thumbnail": _meta(html, "og:image"),
        "ok": True,
    }


def _line_of(text, url):
    """URL이 들어 있는 줄만 반환 (여러 링크를 한꺼번에 붙여넣어도 분류가 섞이지 않게)."""
    for line in (text or "").splitlines():
        if url in line:
            return line
    return ""


def add_links(conn, text, category=None, fetch=True):
    """붙여넣은 텍스트의 링크를 저장. (추가된 수, 이미 있던 수, 메타 실패 수) 반환."""
    added = dup = failed = 0
    for url in extract_urls(text):
        if conn.execute("SELECT 1 FROM videos WHERE url=?", (url,)).fetchone():
            dup += 1
            continue
        meta = fetch_metadata(url) if fetch else {"title": "", "description": "", "thumbnail": "", "ok": True}
        if fetch and not meta["ok"]:
            failed += 1
        cat = category if category in CATEGORY_LABEL else classify(meta["title"], meta["description"], _line_of(text, url))
        conn.execute(
            "INSERT INTO videos(url, platform, category, title, description, thumbnail) VALUES(?,?,?,?,?,?)",
            (url, detect_platform(url), cat, meta["title"], meta["description"], meta["thumbnail"]),
        )
        added += 1
    conn.commit()
    return added, dup, failed


def list_videos(conn, platform="", category="", q=""):
    sql, args = "SELECT * FROM videos WHERE 1=1", []
    if platform:
        sql += " AND platform=?"; args.append(platform)
    if category:
        sql += " AND category=?"; args.append(category)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR tags LIKE ? OR note LIKE ?)"
        args += [f"%{q}%"] * 4
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]


def update_video(conn, vid, category=None, tags=None, note=None):
    if category in CATEGORY_LABEL:
        conn.execute("UPDATE videos SET category=? WHERE id=?", (category, vid))
    if tags is not None:
        conn.execute("UPDATE videos SET tags=? WHERE id=?", (tags.strip(), vid))
    if note is not None:
        conn.execute("UPDATE videos SET note=? WHERE id=?", (note.strip(), vid))
    conn.commit()


def delete_video(conn, vid):
    conn.execute("DELETE FROM videos WHERE id=?", (vid,))
    conn.commit()


def to_csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["플랫폼", "분류", "제목", "링크", "태그", "메모", "수집일"])
    for r in rows:
        w.writerow([PLATFORM_LABEL.get(r["platform"], r["platform"]),
                    CATEGORY_LABEL.get(r["category"], r["category"]),
                    r["title"], r["url"], r["tags"], r["note"], r["created_at"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")
