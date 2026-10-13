# Graveyard Keeper 2 Wiki — offline PWA

Offline copy of <https://graveyardkeeper2.fandom.com> as a static site and installable PWA,
with full-text search and a crafting cart that breaks builds down to raw materials.

**Live:** <https://naffiq.github.io/graveyard-keeper-2-wiki/>
· Sister project for the first game: [graveyard-keeper-wiki](https://github.com/naffiq/graveyard-keeper-wiki)

## Build

```sh
python3 scrape.py --content content   # → site/ (+ versioned snapshot in content/)
python3 -m http.server 8766 --directory site
```

No dependencies beyond the Python 3 standard library. The PWA (service worker, install,
offline download) needs http(s); opening `site/index.html` as a file works without it.

## Files

| file | what |
|---|---|
| `scrape.py` | fetches pages/wikitext/images via the MediaWiki API, writes `site/`; site constants at the top |
| `recipes.py` | parses recipe tables — GK2 "Material / Quantity" tables (plus the GK1 formats) |
| `search.js` | header search: titles + lazily loaded full-text index |
| `app.js` | cart storage, “Add to cart” buttons, service worker registration |
| `cart.js` | cart page: expands recipes to raw materials and ordered crafting steps |
| `sw.js` | service worker: app shell, cache-as-you-browse, full offline download |
| `style.css`, `icons/` | styling (light/dark, phone/tablet), app icons |

Both wikis are served from `naffiq.github.io`, so they share an origin: this one uses its own
cache (`gk2-wiki-*`) and cart storage key (`gk2-cart`) and never touches the other's.

## Automatic updates & versioning

`.github/workflows/update-wiki.yml` runs weekly, Mondays 04:00 UTC (and on demand from the Actions tab):

1. `python3 scrape.py --content content` — asks the wiki's `recentchanges` API what was edited
   since `content/state.json`, refetches only those pages (template edits re-render everything).
2. Commits `content/` — one `.wiki` file per page plus `recipes.json` — so `git log content/`
   is the wiki's history and `git diff` shows exactly what changed between snapshots.
3. Redeploys GitHub Pages (`gh-pages` branch) when the wiki changed; pushes that touch the
   site code (`*.py`, `*.js`, `*.css`, `icons/`) rebuild and redeploy immediately.

## License

Wiki text and images are from the [Graveyard Keeper 2 Fandom wiki](https://graveyardkeeper2.fandom.com)
under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/); each page links back to its
original. Logo/icon from the game's Steam page; game assets belong to Lazy Bear Games / tinyBuild.
This is an unofficial fan copy.
