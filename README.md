# RocMaidan social wall (self hosted)

A static mosaic wall of RocMaidan's Facebook page posts and Instagram media, built
straight from Meta's Graph API. It replaces the Elfsight Social Feed widget.

Why: Elfsight bills per widget load. Their own docs say a view counts every time the
page with the widget loads, so crawlers, link previews and your own editing sessions
burn the monthly quota. This wall is plain HTML served from GitHub Pages, so there is
no view cap, no per load billing, and no third party iframe on the page.

```
scripts/setup_token.py    one time: short lived token -> permanent Page token (writes .env)
scripts/fetch_feed.py     Graph API -> data/feed.json (keeps last good cache if a source fails)
scripts/build_site.py     data/feed.json -> index.html (mirrors images locally)
scripts/verify_layout.py  layout gate: squares, no overlaps, no holes, images load
scripts/publish.sh        fetch + build + commit + push
```

## Setup (one time, about 5 minutes)

1. Create a Meta app at https://developers.facebook.com/apps (type: Business).
2. Open the Graph API Explorer, select your app, and add these permissions:
   `pages_show_list`, `pages_read_engagement`, `instagram_basic`, `business_management`.
3. Generate a **User** token, then run:

```
python3 scripts/setup_token.py --app-id YOUR_APP_ID "PASTE_THE_SHORT_LIVED_TOKEN"
```

That exchanges the token for a long lived one, pulls the Page token (which does not
expire on its own) plus the linked Instagram business account id, and writes them to
`.env` (gitignored, chmod 600). The token is never printed.

4. Build it:

```
python3 scripts/fetch_feed.py && python3 scripts/build_site.py && python3 scripts/publish.sh
```

## Instagram requirements

- The Instagram account must be **Business or Creator**. Personal accounts cannot be
  read through the API at all, the old Basic Display API was shut down on 4 December 2024.
- It must be **linked to the Facebook Page** in Meta Business Suite. If
  `setup_token.py` prints "NONE LINKED", link it first, then re-run.

## Google Sites embed

RocMaidan's site is Google Sites, so the wall goes in an "Embed code" tile. Delete the
old Elfsight tile and paste `embed-snippet.html`:

```html
<div style="position:relative;padding-top:100%;height:0;overflow:hidden">
  <iframe src="https://dpsoccerdude101.github.io/rocmaidan-feed/?embed=1"
    title="RocMaidan Facebook and Instagram feed"
    style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
    loading="lazy" scrolling="no"></iframe>
</div>
```

`?embed=1` hides the header and footer. `?n=12` limits the number of tiles.

Height note: `padding-top:100%` makes the tile as tall as it is wide. The wall is square
based, so that ratio stays honest at every breakpoint. If you want it taller, use
`padding-top:130%` and set `max_tiles` higher.

## Refresh

`scripts/publish.sh` is what keeps it current. Run it on a schedule (cron, every 6 hours
is plenty for a page that posts a few times a week). Facebook and Instagram image URLs on
their CDNs are signed and expire, which is why `build_site.py` mirrors every image into
`assets/img/` and prunes the ones no longer used. A stale build does not break, but a very
old build can end up with expired source URLs if you turn mirroring off.

## Config

`config.json`:

| key | meaning |
|---|---|
| `page_id` | Facebook Page id or vanity name (`rocmaidan`) |
| `ig_username` | for reference only, the IG id comes from the Page link |
| `posts_per_source` | how many posts to pull per platform |
| `max_tiles` | how many tiles render (28 keeps the page around 2 to 4 MB) |
| `expand_albums` | split multi photo posts and carousels into separate tiles |
| `show_header` | header with title and follow buttons |
| `brand` | accent colours, gutter, tile radius |

The mosaic rhythm lives in `PATTERN` in `scripts/build_site.py`: `"big"` is a 2x2 block,
`"s"` is a square. Only those two shapes are used because they tile a 4 column grid
exactly, with no holes and no drift.

## Verify before shipping a change

```
python3 scripts/verify_layout.py --width 1280
python3 scripts/verify_layout.py --width 390
```

It renders the page in Chromium and fails if any tile is not square, if tiles overlap,
if the grid has holes, or if an image fails to load.

## Gotchas

- Keep the repo **public** if you want free GitHub Pages. It contains only already public
  posts and images. `.env` is gitignored, never commit it.
- If the Page or Instagram token stops working, re-run `setup_token.py`. Changing the
  Facebook account password invalidates the long lived token.
- The page is served with `noindex` so it never competes with rocmaidan.org in search.