#!/usr/bin/env python3
"""
publish_to_site.py
Writes a Hugo markdown page for a product and rebuilds the site.
Called by the factory publisher after Whop/Payhip publish succeeds.

Usage:
    python publish_to_site.py --product-id 42
    python publish_to_site.py --all          # backfill all live products
    python publish_to_site.py --dry-run      # show what would be written
"""
import sys, json, argparse, subprocess, shutil
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

SITE_DIR   = Path(__file__).parent          # oddshop_site/
CONTENT_DIR = SITE_DIR / "content" / "tools"
STATIC_DIR  = SITE_DIR / "static" / "images" / "tools"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

try:
    from config import DB_PATH
    from db.schema import get_connection
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9-]", "", text.lower().replace(" ", "-"))


def product_to_markdown(product: dict, listings: list) -> str:
    """Generate Hugo front matter + body from a product dict + listings rows."""
    slug        = slugify(product["title"])
    price       = f"${product.get('price', 29):.0f}"
    date_str    = (product.get("live_at") or product.get("created_at") or
                   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]

    # Pull URLs from listings
    buy_url    = ""
    github_url = ""
    for l in listings:
        if l["platform"] in ("whop", "payhip", "kofi") and not buy_url:
            buy_url = l["listing_url"]
        if l["platform"] == "github" and not github_url:
            github_url = l["listing_url"]

    # Tags from category + title words
    title_words = [w.lower() for w in product["title"].split() if len(w) > 3]
    base_tags   = ["python", "automation", "tool"]
    if product.get("category"):
        base_tags.append(product["category"].lower())
    tags = list(dict.fromkeys(base_tags + title_words))[:8]
    tags_str = json.dumps(tags)

    features = product.get("features") or "[]"
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except Exception:
            features = []

    description = product.get("description") or f"Automate {product['title'].lower()} with this Python script."
    usage_ex    = product.get("usage_example") or ""

    # Cover image — copy to static if it exists
    cover_static = ""
    if product.get("cover_path") and Path(product["cover_path"]).exists():
        dest = STATIC_DIR / f"{slug}_cover.png"
        shutil.copy2(product["cover_path"], dest)
        cover_static = f"/images/tools/{slug}_cover.png"

    # GIF — copy to static if it exists
    gif_static = ""
    if product.get("gif_path") and Path(product["gif_path"]).exists():
        dest = STATIC_DIR / f"{slug}_demo.gif"
        shutil.copy2(product["gif_path"], dest)
        gif_static = f"/images/tools/{slug}_demo.gif"

    # Build feature bullet list
    features_md = ""
    if features:
        features_md = "\n## Features\n\n" + "\n".join(f"- {f}" for f in features) + "\n"

    usage_md = ""
    if usage_ex:
        usage_md = f"\n## Usage\n\n```bash\n{usage_ex}\n```\n"

    front_matter = f"""---
title: "{product['title']}"
date: {date_str}
draft: false
description: "{description.replace('"', "'")}"
tags: {tags_str}
categories: ["tools"]
price: "{price}"
buy_url: "{buy_url}"
github_url: "{github_url}"
cover: "{cover_static}"
demo_gif: "{gif_static}"
score: {int(product.get('confidence_score') or 0)}
---"""

    body = f"""
{description}
{features_md}{usage_md}
## Requirements

- Python 3.8+
- See README inside the ZIP for full dependency list

## Download

Buy once, download immediately. The ZIP includes the full script, README, and usage examples.
"""
    return front_matter + "\n" + body.strip()


def publish_product(product_id: int, dry_run: bool = False) -> bool:
    if not DB_AVAILABLE:
        print("ERROR: Cannot import config/db — run from factory root directory")
        return False

    conn = get_connection(DB_PATH)
    row = conn.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if not row:
        print(f"Product {product_id} not found")
        conn.close()
        return False

    product  = dict(row)
    listings = [dict(r) for r in conn.execute(
        "SELECT * FROM listings WHERE product_id = ? AND status = 'active'",
        (product_id,)
    ).fetchall()]
    conn.close()

    slug     = slugify(product["title"])
    md_path  = CONTENT_DIR / f"{slug}.md"
    content  = product_to_markdown(product, listings)

    if dry_run:
        print(f"[DRY RUN] Would write: {md_path}")
        print(content[:500] + "...")
        return True

    md_path.write_text(content, encoding="utf-8")
    print(f"  Written: {md_path.name}")

    # Rebuild site
    result = subprocess.run(["hugo"], cwd=SITE_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Hugo build failed:\n{result.stderr}")
        return False

    print(f"  Site rebuilt — {slug} is live")
    return True


def publish_all(dry_run: bool = False):
    if not DB_AVAILABLE:
        print("ERROR: Cannot import config/db")
        return

    conn = get_connection(DB_PATH)
    products = conn.execute(
        "SELECT id, title FROM products WHERE status = 'live'"
    ).fetchall()
    conn.close()

    print(f"Backfilling {len(products)} live products...")
    ok = 0
    for p in products:
        if publish_product(p["id"], dry_run=dry_run):
            ok += 1
    print(f"Done: {ok}/{len(products)} published to site")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--product-id", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all:
        publish_all(dry_run=args.dry_run)
    elif args.product_id:
        publish_product(args.product_id, dry_run=args.dry_run)
    else:
        ap.print_help()
