# Brand assets

Generated Knovaryn identity assets. **Do not edit files here by hand** —
every one is produced by `scripts/visuals/build_brand_assets.py` from a
single geometry source, and a drift check
(`... build_brand_assets.py --check`) fails if an output no longer matches
its source.

```bash
uv run --extra visuals python scripts/visuals/build_brand_assets.py          # build all
uv run --extra visuals python scripts/visuals/build_brand_assets.py --check  # verify
```

Read [brand-guidelines.md](brand-guidelines.md) for usage rules, clear
space, minimum sizes, variants, and misuse before placing any asset.

Raster derivatives (`.png`) are rendered with Playwright's Chromium at fixed
viewports; identical inputs produce identical bytes for a given browser
build.
