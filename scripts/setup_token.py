#!/usr/bin/env python3
"""One time helper: turn a short lived Meta token into a permanent Page token.

You need: a Meta app (developers.facebook.com/apps), its App ID and App Secret,
and a short lived User token from the Graph API Explorer with these permissions:

    pages_show_list, pages_read_engagement, instagram_basic, business_management

Then:

    python3 scripts/setup_token.py --app-id 1234567890 "PASTE_SHORT_LIVED_TOKEN"

It exchanges the token for a long lived User token, pulls the Page token (this
one does not expire) and the linked Instagram business account id, then writes
them to .env, which is gitignored. The token is never printed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CONFIG = ROOT / "config.json"
PERMS = "pages_show_list,pages_read_engagement,instagram_basic,business_management"


def call(path: str, params: dict) -> dict:
    url = "https://graph.facebook.com/" + path.lstrip("/") + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "rocmaidan-feed/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--app-secret", help="or put META_APP_SECRET in .env / pass it when prompted")
    ap.add_argument("token", help="short lived user token from the Graph API Explorer")
    args = ap.parse_args()

    secret = args.app_secret
    if not secret and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("META_APP_SECRET="):
                secret = line.split("=", 1)[1].strip().strip("'\"")
    if not secret:
        secret = input("App Secret: ").strip()
    if not secret:
        fail("no App Secret given")

    print("exchanging for a long lived user token...")
    try:
        ex = call("/oauth/access_token", {
            "grant_type": "fb_exchange_token",
            "client_id": args.app_id,
            "client_secret": secret,
            "fb_exchange_token": args.token,
        })
    except Exception as exc:
        fail(f"token exchange failed: {exc}")
    long_token = ex.get("access_token")
    if not long_token:
        fail(f"no access_token in response: {json.dumps(ex)[:300]}")
    hours = ex.get("expires_in", 0) / 3600
    print(f"got a long lived user token (expires in ~{hours:.0f}h if set)")

    try:
        accounts = call("/me/accounts", {
            "fields": "id,name,username,access_token,instagram_business_account{id,username}",
            "limit": 200,
            "access_token": long_token,
        })
    except Exception as exc:
        fail(f"could not list Pages with this token: {exc}\n"
             f"make sure the token has: {PERMS} and that your account is an admin of the Page.")

    rows = accounts.get("data", [])
    if not rows:
        fail(f"this token can see no Pages. Needed permissions: {PERMS}")

    wanted = json.loads(CONFIG.read_text()).get("page_id", "").lower()
    page = None
    for row in rows:
        if wanted in {str(row.get("id", "")).lower(), str(row.get("username", "")).lower(), str(row.get("name", "")).lower().replace(" ", "")}:
            page = row
            break
    if page is None:
        print("no Page matched config.json page_id, here is what the token can see:")
        for i, row in enumerate(rows):
            ig = (row.get("instagram_business_account") or {}).get("username")
            print(f"  [{i}] {row.get('name')} | id={row.get('id')} | username={row.get('username')} | ig={ig or 'none'}")
        choice = input("number to use, or blank to abort: ").strip()
        if not choice:
            fail("aborted")
        page = rows[int(choice)]

    page_token = page.get("access_token")
    if not page_token:
        fail("this token returned no Page access token. Recreate it with pages_show_list included.")
    ig = page.get("instagram_business_account") or {}

    lines = [l for l in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [])
             if not re.match(r"^(ROCMADAN_FB_TOKEN|ROCMAIDAN_FB_TOKEN|ROCMAIDAN_PAGE_ID|ROCMAIDAN_IG_ID|META_APP_ID|META_APP_SECRET)=", l)]
    lines += [
        f"META_APP_ID={args.app_id}",
        f"META_APP_SECRET={secret}",
        f"ROCMAIDAN_PAGE_ID={page.get('id')}",
        f"ROCMAIDAN_IG_ID={ig.get('id', '')}",
        f"ROCMAIDAN_FB_TOKEN={page_token}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    ENV_FILE.chmod(0o600)

    print(f"\nwrote {ENV_FILE.name} (chmod 600, gitignored)")
    print(f"  page      : {page.get('name')} ({page.get('id')})")
    print(f"  page token: {len(page_token)} chars, does not expire on its own")
    print(f"  instagram : {ig.get('username') or 'NONE LINKED'} ({ig.get('id') or '-'})")
    if not ig.get("id"):
        print("\nnote: no Instagram business account is linked to this Page.")
        print("Link it in the Instagram app: Settings, Account type and tools, or from the Page settings.")
        print("Instagram must be a Business or Creator account (personal accounts cannot be read via the API).")
    print("\nnext: python3 scripts/fetch_feed.py && python3 scripts/build_site.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())