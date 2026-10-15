#!/usr/bin/env python3
"""Pull RocMaidan's Facebook page posts and Instagram media into data/feed.json.

No third party widget, no view cap: this talks straight to the Graph API and
writes a static JSON file that build_site.py turns into HTML.

Usage:
    python3 scripts/fetch_feed.py            # live (needs a token)
    python3 scripts/fetch_feed.py --demo     # render from data/sample_feed.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
OUT = ROOT / "data" / "feed.json"
SAMPLE = ROOT / "data" / "sample_feed.json"
ENV_FILE = ROOT / ".env"

FB_FIELDS = (
    "id,message,created_time,permalink_url,full_picture,"
    "attachments{media_type,media,subattachments},"
    "likes.summary(true),comments.summary(true),shares"
)
IG_FIELDS = (
    "id,caption,media_type,media_url,thumbnail_url,permalink,"
    "timestamp,like_count,comments_count,children{media_url,thumbnail_url,media_type}"
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_token() -> str | None:
    """Token from the environment or the gitignored .env file. Never logged."""
    tok = os.environ.get("ROCMADAN_FB_TOKEN") or os.environ.get("ROCMAIDAN_FB_TOKEN")
    if tok:
        return tok.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("ROCMAIDAN_FB_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def graph(path: str, params: dict, token: str) -> dict:
    params = dict(params)
    params["access_token"] = token
    url = "https://graph.facebook.com/" + path.lstrip("/") + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "rocmaidan-feed/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def graph_error(exc: Exception) -> str:
    """Human readable error with the token scrubbed out of it."""
    msg = str(exc)
    if hasattr(exc, "read"):
        try:
            payload = json.loads(exc.read().decode("utf-8"))  # type: ignore[attr-defined]
            err = payload.get("error", {})
            msg = f"{err.get('code')}/{err.get('error_subcode')} {err.get('message')}"
            if err.get("error_user_msg"):
                msg += f": {err['error_user_msg']}"
        except Exception:
            pass
    msg = re.sub(r"access_token=[^&\s]+", "access_token=REDACTED", msg)
    return msg


def resolve_page(page_id: str, token: str, version: str) -> tuple[str, str | None, str | None, str | None]:
    """Return (page_id, page_name, page_token, ig_user_id)."""
    if page_id.isdigit():
        page = graph(f"{version}/{page_id}", {"fields": "id,name,access_token,instagram_business_account{id,username}"}, token)
    else:
        accounts = graph(f"{version}/me/accounts", {
            "fields": "id,name,username,access_token,instagram_business_account{id,username}",
            "limit": 200,
        }, token)
        rows = accounts.get("data", [])
        if not rows:
            raise RuntimeError("this token can see no Pages. Re-run the token step with pages_show_list and an admin account.")
        page = next(
            (p for p in rows if page_id.lower() in {str(p.get("id", "")).lower(), str(p.get("username", "")).lower(), str(p.get("name", "")).lower().replace(" ", "")}),
            None,
        )
        if page is None:
            names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in rows)
            raise RuntimeError(f"no Page matched '{page_id}'. Token can see: {names}")
    ig = page.get("instagram_business_account") or {}
    return str(page.get("id")), page.get("name"), page.get("access_token") or token, ig.get("id")


def fb_items(page_id: str, token: str, version: str, limit: int, expand_albums: bool) -> list[dict]:
    data = graph(f"{version}/{page_id}/posts", {"fields": FB_FIELDS, "limit": limit}, token)
    items: list[dict] = []
    for post in data.get("data", []):
        caption = (post.get("message") or "").strip()
        permalink = post.get("permalink_url") or f"https://www.facebook.com/{post.get('id')}"
        created = post.get("created_time")
        likes = ((post.get("likes") or {}).get("summary") or {}).get("total_count", 0)
        comments = ((post.get("comments") or {}).get("summary") or {}).get("total_count", 0)
        attachments = (post.get("attachments") or {}).get("data") or []
        media_type = (attachments[0].get("media_type") if attachments else "") or ""

        galleries: list[str] = []
        if expand_albums and attachments:
            subs = ((attachments[0].get("subattachments") or {}).get("data")) or []
            for sub in subs:
                img = ((sub.get("media") or {}).get("image") or {}).get("src")
                if img:
                    galleries.append(img)

        primary = post.get("full_picture") or (galleries[0] if galleries else None)
        if primary:
            items.append({
                "id": post.get("id"),
                "platform": "facebook",
                "type": "video" if media_type.startswith("video") else "image",
                "image": primary,
                "thumb": primary,
                "caption": caption,
                "permalink": permalink,
                "created_time": created,
                "likes": likes,
                "comments": comments,
            })
        if expand_albums:
            for img in galleries[1:6]:
                items.append({
                    "id": f"{post.get('id')}#{img[-24:]}",
                    "platform": "facebook",
                    "type": "image",
                    "image": img,
                    "thumb": img,
                    "caption": "",
                    "album_of": post.get("id"),
                    "permalink": permalink,
                    "created_time": created,
                    "likes": likes,
                    "comments": comments,
                })
    return items


def ig_items(ig_user_id: str, token: str, version: str, limit: int, expand_albums: bool) -> list[dict]:
    data = graph(f"{version}/{ig_user_id}/media", {"fields": IG_FIELDS, "limit": limit}, token)
    items: list[dict] = []
    for media in data.get("data", []):
        mtype = (media.get("media_type") or "").upper()
        caption = (media.get("caption") or "").strip()
        base = {
            "platform": "instagram",
            "caption": caption,
            "permalink": media.get("permalink"),
            "created_time": media.get("timestamp"),
            "likes": media.get("like_count") or 0,
            "comments": media.get("comments_count") or 0,
        }
        if mtype == "CAROUSEL_ALBUM" and expand_albums:
            children = (media.get("children") or {}).get("data") or []
            for idx, child in enumerate(children[:6]):
                img = child.get("media_url") or child.get("thumbnail_url")
                if not img:
                    continue
                items.append({
                    **base,
                    "id": f"{media.get('id')}#{idx}",
                    "type": "video" if (child.get("media_type") or "").upper() == "VIDEO" else "image",
                    "image": img,
                    "thumb": child.get("thumbnail_url") or img,
                    "caption": caption if idx == 0 else "",
                })
            continue
        img = media.get("thumbnail_url") if mtype == "VIDEO" else media.get("media_url")
        if not img:
            continue
        items.append({
            **base,
            "id": media.get("id"),
            "type": "video" if mtype == "VIDEO" else "image",
            "image": img,
            "thumb": media.get("thumbnail_url") or img,
        })
    return items


def sort_key(item: dict) -> str:
    return item.get("created_time") or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="write sample_feed.json to feed.json and stop")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)

    if args.demo:
        if not SAMPLE.exists():
            log(f"no sample data at {SAMPLE}")
            return 2
        OUT.write_text(SAMPLE.read_text())
        log(f"demo mode: copied {SAMPLE.name} -> {OUT.name}")
        return 0

    token = load_token()
    if not token:
        log("no token found. Run scripts/setup_token.py, then re-run this script.")
        return 2

    version = cfg.get("api_version", "v21.0")
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text())
        except Exception:
            previous = {}
    prev_items = previous.get("items", [])

    feed: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": {}, "items": []}
    items: list[dict] = []

    try:
        page_id, page_name, page_token, ig_user_id = resolve_page(str(cfg.get("page_id")), token, version)
        log(f"page: {page_name} ({page_id}) ig_business_account: {ig_user_id or 'none linked'}")
        try:
            fb = fb_items(page_id, page_token, version, int(cfg.get("posts_per_source", 30)), bool(cfg.get("expand_albums", True)))
            items += fb
            feed["sources"]["facebook"] = {"ok": True, "count": len(fb), "name": page_name, "id": page_id}
        except Exception as exc:  # keep whatever we can
            feed["sources"]["facebook"] = {"ok": False, "error": graph_error(exc)}
            log(f"facebook failed: {feed['sources']['facebook']['error']}")

        if ig_user_id:
            try:
                ig = ig_items(ig_user_id, page_token, version, int(cfg.get("posts_per_source", 30)), bool(cfg.get("expand_albums", True)))
                items += ig
                feed["sources"]["instagram"] = {"ok": True, "count": len(ig), "id": ig_user_id}
            except Exception as exc:
                feed["sources"]["instagram"] = {"ok": False, "error": graph_error(exc)}
                log(f"instagram failed: {feed['sources']['instagram']['error']}")
        else:
            feed["sources"]["instagram"] = {"ok": False, "error": "no Instagram business account linked to this Page"}
    except Exception as exc:
        log(f"page lookup failed: {graph_error(exc)}")
        feed["sources"]["facebook"] = {"ok": False, "error": graph_error(exc)}

    # If a single source failed, keep the last good items for it so the wall never goes
    # blank. If EVERY source failed that is not a hiccup, it is a broken token or config,
    # so fail loudly and let the caller alert.
    failed = {name for name, s in feed["sources"].items() if not s.get("ok")}
    ok_sources = {name for name, s in feed["sources"].items() if s.get("ok")}
    if failed and not ok_sources:
        errors = "; ".join(f"{n}: {feed['sources'][n].get('error')}" for n in sorted(failed))
        log(f"every source failed, refusing to publish stale data. {errors}")
        return 1
    if failed:
        kept = [i for i in prev_items if i.get("platform") in failed]
        if kept:
            log(f"keeping {len(kept)} previously cached items for: {', '.join(sorted(failed))}")
            items += kept

    seen: set[str] = set()
    unique = []
    for item in sorted(items, key=sort_key, reverse=True):
        key = item.get("id") or item.get("image")
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    feed["items"] = unique[: int(cfg.get("max_tiles", 28)) * 3]
    if not feed["items"]:
        log("no items fetched and no cache available. Leaving the previous feed.json in place.")
        return 1

    OUT.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
    log(f"wrote {OUT.relative_to(ROOT)} with {len(feed['items'])} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
