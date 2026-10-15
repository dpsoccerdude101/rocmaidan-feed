#!/usr/bin/env python3
"""Turn data/feed.json into a static mosaic page (index.html).

Output is a single self contained page: inlined CSS, no JS libraries, no
third party widget, no view cap. Images are mirrored into assets/img/ so the
page never depends on Facebook or Instagram CDN URLs (those are signed and
expire).

Usage:
    python3 scripts/build_site.py                 # mirror images, build index.html
    python3 scripts/build_site.py --no-mirror     # keep remote CDN URLs (fast local preview)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
FEED = ROOT / "data" / "feed.json"
IMG_DIR = ROOT / "assets" / "img"
OUT = ROOT / "index.html"
SNIPPET = ROOT / "embed-snippet.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Mosaic rhythm: squares with a 2x2 feature block every 7 tiles. Only these two
# shapes are used because they tile a 4 column grid exactly with no holes and no
# drift: a 2x2 block is precisely 2 tracks + 1 gutter wide and tall.
PATTERN = ["big", "s", "s", "s", "s", "s", "s"]

FB_ICON = ('<svg viewBox="0 0 24 24" width="13" height="13" fill="#fff" aria-hidden="true">'
           '<path d="M22 12.06C22 6.5 17.52 2 12 2S2 6.5 2 12.06c0 5 3.66 9.15 8.44 9.94v-7.03H7.9v-2.9h2.54V9.85'
           'c0-2.51 1.49-3.9 3.77-3.9 1.09 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.78-1.63 1.57v1.88h2.78l-.44 2.9h-2.34'
           'V22c4.78-.79 8.44-4.93 8.44-9.94Z"/></svg>')
IG_ICON = ('<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="#fff" stroke-width="2.1" aria-hidden="true">'
           '<rect x="3" y="3" width="18" height="18" rx="5.2"/><circle cx="12" cy="12" r="4.1"/>'
           '<circle cx="17.3" cy="6.7" r="1.2" fill="#fff" stroke="none"/></svg>')
PLAY_ICON = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="#fff" aria-hidden="true">'
             '<path d="M8 5.5v13l11-6.5-11-6.5Z"/></svg>')


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def clean_caption(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"https?://\S+", "", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return text


def human_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.astimezone(timezone.utc).strftime("%b %-d, %Y")


def mirror(item: dict) -> str:
    """Download the image once, return a repo relative path."""
    src = item.get("image")
    if not src:
        return ""
    ext = ".jpg"
    m = re.search(r"\.(jpe?g|png|webp)(?:\?|$)", src, re.I)
    if m:
        ext = "." + m.group(1).lower().replace("jpeg", "jpg")
    digest = hashlib.sha1((item.get("id") or src).encode("utf-8")).hexdigest()[:16]
    dest = IMG_DIR / f"{digest}{ext}"
    if dest.exists() and dest.stat().st_size > 1024:
        return f"assets/img/{dest.name}"
    try:
        req = urllib.request.Request(src, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            blob = resp.read()
        if len(blob) < 1024:
            log(f"  tiny image, skipping: {src[:60]}")
            return src
        dest.write_bytes(blob)
        return f"assets/img/{dest.name}"
    except Exception as exc:
        log(f"  image mirror failed ({exc.__class__.__name__}), using remote URL")
        return src


def tile_html(item: dict, shape: str, image: str) -> str:
    platform = item.get("platform", "facebook")
    badge = IG_ICON if platform == "instagram" else FB_ICON
    label = "Instagram" if platform == "instagram" else "Facebook"
    caption = clean_caption(item.get("caption", ""))
    date = human_date(item.get("created_time"))
    video = item.get("type") == "video"
    meta_bits = [b for b in [date, f"{item.get('likes', 0)} likes" if item.get("likes") else ""] if b]
    overlay_caption = caption or (label + " post")
    shape_cls = "" if shape == "s" else f" rm-tile--{shape}"
    return f"""      <a class="rm-tile{shape_cls} rm-tile--{platform}" href="{esc(item.get('permalink', '#'))}" target="_blank" rel="noopener noreferrer" aria-label="{esc(label)} post{': ' + esc(overlay_caption[:80]) if caption else ''}">
        <img src="{esc(image)}" alt="{esc(overlay_caption[:140])}" loading="lazy" decoding="async" referrerpolicy="no-referrer">
        <span class="rm-badge" title="{esc(label)}">{badge}</span>
        {'<span class="rm-play">' + PLAY_ICON + '</span>' if video else ''}
        <span class="rm-overlay">
          <span class="rm-cap">{esc(overlay_caption)}</span>
          {'<span class="rm-meta">' + esc(" &middot; ".join(meta_bits)).replace("&amp;middot;", "&middot;") + '</span>' if meta_bits else ''}
        </span>
      </a>"""


CSS = """
:root{--rm-accent:#0057b7;--rm-accent2:#ffd700;--rm-gutter:8px;--rm-radius:10px}
.rm-feed{box-sizing:border-box;width:100%;margin:0 auto;padding:18px 16px 26px;background:transparent;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#14161c}
.rm-feed *,.rm-feed *::before,.rm-feed *::after{box-sizing:border-box}
.rm-head{display:flex;flex-wrap:wrap;gap:14px;align-items:center;justify-content:space-between;margin:0 0 14px}
.rm-head h2{margin:0;font-size:20px;line-height:1.2;letter-spacing:-.01em}
.rm-head p{margin:2px 0 0;font-size:13px;color:#5c6270}
.rm-follow{display:flex;gap:8px;flex-wrap:wrap}
.rm-follow a{display:inline-flex;align-items:center;gap:7px;padding:8px 14px;border-radius:6px;background:var(--rm-accent);
  color:#fff;font-size:13px;font-weight:600;text-decoration:none;border:1px solid var(--rm-accent)}
.rm-follow a.rm-ig{background:#c13584;border-color:#c13584}
.rm-follow a:hover{filter:brightness(1.08)}
.rm-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:auto;grid-auto-flow:dense;gap:var(--rm-gutter)}
.rm-tile{position:relative;display:block;overflow:hidden;border-radius:var(--rm-radius);background:#e8eaf0;aspect-ratio:1/1;
  text-decoration:none;outline-offset:2px}
.rm-tile img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .35s ease}
.rm-tile:hover img,.rm-tile:focus-visible img{transform:scale(1.045)}
.rm-tile--big{grid-column:span 2;grid-row:span 2}
.rm-badge{position:absolute;top:8px;right:8px;width:24px;height:24px;border-radius:50%;background:rgba(10,12,20,.55);
  display:flex;align-items:center;justify-content:center;backdrop-filter:blur(3px)}
.rm-play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:40px;height:40px;border-radius:50%;
  background:rgba(10,12,20,.5);display:flex;align-items:center;justify-content:center}
.rm-overlay{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:flex-end;gap:4px;padding:10px;
  background:linear-gradient(to top,rgba(8,10,20,.78),rgba(8,10,20,.35) 42%,rgba(8,10,20,0) 72%);
  opacity:0;transition:opacity .25s ease}
.rm-tile:hover .rm-overlay,.rm-tile:focus-visible .rm-overlay{opacity:1}
.rm-cap{color:#fff;font-size:13px;line-height:1.35;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.rm-meta{color:rgba(255,255,255,.78);font-size:11.5px}
.rm-foot{margin:16px 0 0;font-size:12.5px;color:#5c6270}
.rm-foot a{color:var(--rm-accent)}
body.rm-embed{margin:0;background:transparent}
body.rm-embed .rm-feed{padding:0}
body.rm-embed .rm-head,body.rm-embed .rm-foot{display:none}
@media (max-width:900px){.rm-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:620px){
  .rm-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}
  .rm-tile--big{grid-column:span 2;grid-row:span 1}
  .rm-feed{padding:12px 12px 18px}
  .rm-head h2{font-size:18px}
}
"""


def build(mirror_images: bool) -> int:
    cfg = json.loads(CONFIG.read_text())
    if not FEED.exists():
        log(f"missing {FEED}. run scripts/fetch_feed.py first.")
        return 2
    feed = json.loads(FEED.read_text())
    items = feed.get("items", [])
    if not items:
        log("feed.json has no items")
        return 2

    max_tiles = int(cfg.get("max_tiles", 28))
    items = items[:max_tiles]

    if mirror_images:
        IMG_DIR.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    tiles: list[str] = []
    for idx, item in enumerate(items):
        image = str(item.get("image") or "")
        if mirror_images:
            image = mirror(item)
        if image.startswith("assets/img/"):
            used.add(Path(image).name)
        shape = PATTERN[idx % len(PATTERN)]
        tiles.append(tile_html(item, shape, image))

    if mirror_images and IMG_DIR.exists():
        for old in IMG_DIR.iterdir():
            if old.is_file() and old.name not in used:
                old.unlink()

    sources = feed.get("sources", {})
    ig_ok = sources.get("instagram", {}).get("ok")
    fb_ok = sources.get("facebook", {}).get("ok")
    brand = cfg.get("brand", {})
    follow = cfg.get("follow_links", {})
    generated = feed.get("generated_at", "")
    footer = ('<p class="rm-foot">Also on '
              + (f'<a href="{esc(follow.get("facebook", "#"))}" target="_blank" rel="noopener">Facebook</a>' if follow.get("facebook") else "")
              + (' and ' if follow.get("facebook") and follow.get("instagram") else "")
              + (f'<a href="{esc(follow.get("instagram", "#"))}" target="_blank" rel="noopener">Instagram</a>' if follow.get("instagram") else "")
              + ('</p>'))

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg.get('site_title', 'Social feed'))}</title>
<meta name="robots" content="noindex">
<style>:root{{--rm-accent:{brand.get('accent', '#0057b7')};--rm-accent2:{brand.get('accent2', '#ffd700')};--rm-gutter:{brand.get('gutter', '8px')};--rm-radius:{brand.get('tile_radius', '10px')}}}
{CSS}</style>
</head>
<body class="rm-page">
  <div class="rm-feed">
    <div class="rm-head">
      <div>
        <h2>{esc(cfg.get('site_title', ''))}</h2>
        <p>{esc(cfg.get('site_subtitle', ''))}</p>
      </div>
      <div class="rm-follow">
        {f'<a href="{esc(follow.get("facebook"))}" target="_blank" rel="noopener">{FB_ICON}<span>Facebook</span></a>' if follow.get('facebook') else ''}
        {f'<a class="rm-ig" href="{esc(follow.get("instagram"))}" target="_blank" rel="noopener">{IG_ICON}<span>Instagram</span></a>' if follow.get('instagram') else ''}
      </div>
    </div>
    <div class="rm-grid">
{chr(10).join(tiles)}
    </div>
    {footer}
  </div>
  <script>
    (function () {{
      var p = new URLSearchParams(location.search);
      if (p.get('embed') === '1') document.body.classList.add('rm-embed');
      if (p.get('n')) {{
        var n = parseInt(p.get('n'), 10);
        var tiles = document.querySelectorAll('.rm-tile');
        for (var i = n; i < tiles.length; i++) tiles[i].style.display = 'none';
      }}
    }})();
  </script>
</body>
</html>
<!-- built {datetime.now(timezone.utc).isoformat(timespec='seconds')} | facebook ok={fb_ok} instagram ok={ig_ok} | source data {esc(generated)} -->
"""
    OUT.write_text(page)

    url = "https://dpsoccerdude101.github.io/rocmaidan-feed/"
    SNIPPET.write_text(f"""<!-- Paste into a Google Sites "Embed code" tile -->
<div style="position:relative;padding-top:100%;height:0;overflow:hidden">
  <iframe src="{url}?embed=1" title="RocMaidan Facebook and Instagram feed"
    style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
    loading="lazy" scrolling="no"></iframe>
</div>
""")

    size = sum(f.stat().st_size for f in IMG_DIR.iterdir() if f.is_file()) if IMG_DIR.exists() else 0
    log(f"built {OUT.relative_to(ROOT)}: {len(tiles)} tiles, mirror={'on' if mirror_images else 'off'}, "
        f"images on disk {size/1024/1024:.2f} MB")
    return 0


def write_placeholder() -> int:
    """Neutral page for the window between deploy and the first token backed build."""
    cfg = json.loads(CONFIG.read_text())
    OUT.write_text(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg.get('site_title', 'Social feed'))} feed</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#f6f7f9;color:#3a3f4b}}
div{{text-align:center;padding:32px;max-width:420px}}p{{font-size:14px;line-height:1.5}}</style></head>
<body><div><p>Social wall is not published yet. Run the token setup and the first build.</p></div></body></html>
""")
    log("wrote placeholder index.html")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mirror", action="store_true", help="keep remote CDN image URLs (local preview)")
    ap.add_argument("--placeholder", action="store_true", help="write a neutral page instead of the wall")
    args = ap.parse_args()
    if args.placeholder:
        return write_placeholder()
    return build(mirror_images=not args.no_mirror)


if __name__ == "__main__":
    raise SystemExit(main())