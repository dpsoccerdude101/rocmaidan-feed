#!/usr/bin/env python3
"""Layout gate for index.html: fails if the mosaic is not geometrically clean.

Checks, in a real Chromium render:
  1. every tile is square (w == h)
  2. every 2x2 tile is exactly 2 tracks + 1 gutter wide
  3. no two tiles overlap
  4. the grid has no holes: tile area covers the grid box (minus gutters)
  5. images actually load (naturalWidth > 0), so a broken CDN or missing file fails loudly

Usage: python3 scripts/verify_layout.py [--width 1280] [--url ...]
Exit code 0 = clean, 1 = defect (printed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = """
() => {
  const g = document.querySelector('.rm-grid');
  const gr = g.getBoundingClientRect();
  const cs = getComputedStyle(g);
  const gap = parseFloat(cs.rowGap) || 0;
  const tracks = cs.gridTemplateColumns.split(' ').map(parseFloat);
  const tiles = [...document.querySelectorAll('.rm-tile')].map(t => {
    const r = t.getBoundingClientRect();
    const img = t.querySelector('img');
    return {
      w: Math.round(r.width), h: Math.round(r.height),
      x: Math.round(r.x - gr.x), y: Math.round(r.y - gr.y),
      big: t.classList.contains('rm-tile--big'),
      loaded: !!(img && img.complete && img.naturalWidth > 0),
      src: img ? img.getAttribute('src') : null
    };
  });
  return {gap, tracks, gridW: Math.round(gr.width), gridH: Math.round(gr.height), tiles,
          visible: tiles.filter(t => t.w > 0 && t.h > 0).length};
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--url", default=None)
    ap.add_argument("--json", default=None, help="write raw probe output here")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    url = args.url or "file://" + str((ROOT / "index.html").resolve())
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": args.width, "height": 1000})
        page.goto(url, wait_until="load")
        # scroll through so lazy images load, then return to the top
        page.evaluate("""async () => {
          const step = window.innerHeight;
          for (let y = 0; y < document.body.scrollHeight; y += step) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
          window.scrollTo(0, 0);
        }""")
        page.wait_for_timeout(1200)
        data = page.evaluate(PROBE)
        browser.close()

    if args.json:
        Path(args.json).write_text(json.dumps(data, indent=2))

    tiles = [t for t in data["tiles"] if t["w"] > 0]
    unit = min(t["w"] for t in tiles)
    gap = data["gap"]
    print(f"viewport {args.width}px | {len(tiles)} visible tiles | unit {unit}px | gutter {gap}px | grid {data['gridW']}x{data['gridH']}")

    for t in tiles:
        if abs(t["w"] - t["h"]) > 1:
            problems.append(f"tile not square: {t['w']}x{t['h']} at ({t['x']},{t['y']})")
        if t["big"] and abs(t["w"] - (2 * unit + gap)) > 2:
            problems.append(f"2x2 tile is {t['w']}px, expected {2 * unit + gap}px at ({t['x']},{t['y']})")
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                problems.append(f"tiles overlap at ({a['x']},{a['y']}) and ({b['x']},{b['y']})")

    area = sum(t["w"] * t["h"] for t in tiles)
    box = data["gridW"] * data["gridH"]
    coverage = area / box if box else 0
    print(f"coverage {coverage:.3f} (1.0 = no holes)")
    if coverage < 0.90:
        problems.append(f"grid has holes: tiles cover {coverage:.0%} of the grid box")

    unloaded = [t for t in tiles if not t["loaded"]]
    if unloaded:
        problems.append(f"{len(unloaded)} images failed to load, first: {unloaded[0]['src']}")

    if problems:
        print("\nDEFECTS:")
        for prob in dict.fromkeys(problems):
            print("  -", prob)
        return 1
    print("\nlayout clean: squares, no overlaps, no holes, all images loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())