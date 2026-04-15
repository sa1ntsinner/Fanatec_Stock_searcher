"""
Test script to verify the scraper works against the live Fanatec site.
Run: python test_scraper.py
"""

import asyncio
import sys
import os

# Ensure we can import from the project
sys.path.insert(0, os.path.dirname(__file__))

# Set minimal env vars so config doesn't complain
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_ADMIN_USER_ID", "0")

from scraper import scrape_products, _scrape_with_cloudscraper, _parse_products
from database import Database, Product
from config import logger


async def test_cloudscraper():
    """Test cloudscraper strategy only."""
    print("\n" + "=" * 60)
    print("  Testing cloudscraper strategy")
    print("=" * 60)

    html = _scrape_with_cloudscraper()
    if html:
        print(f"✅ Got {len(html)} chars of HTML")
        products = _parse_products(html)
        if products:
            print(f"✅ Parsed {len(products)} product(s):\n")
            for p in products:
                print(f"  📦 {p.name}")
                print(f"     💶 {p.price} (was {p.original_price})")
                print(f"     📊 {p.availability}")
                print(f"     🔗 {p.product_url}")
                print()
            return True
        else:
            print("⚠️  HTML fetched but no products parsed (likely JS-rendered)")
            return False
    else:
        print("❌ cloudscraper failed to fetch the page")
        return False


async def test_playwright():
    """Test Playwright strategy only."""
    print("\n" + "=" * 60)
    print("  Testing Playwright strategy")
    print("=" * 60)

    try:
        from scraper import _scrape_with_playwright
    except ImportError:
        print("❌ Playwright not installed")
        return False

    html = await _scrape_with_playwright()
    if html:
        print(f"✅ Got {len(html)} chars of HTML")
        products = _parse_products(html)
        if products:
            print(f"✅ Parsed {len(products)} product(s):\n")
            for p in products:
                print(f"  📦 {p.name}")
                print(f"     💶 {p.price} (was {p.original_price})")
                print(f"     📊 {p.availability}")
                print(f"     🔗 {p.product_url}")
                print()
            return True
        else:
            print("⚠️  HTML fetched but no products parsed")
            return False
    else:
        print("❌ Playwright failed")
        return False


async def test_full_pipeline():
    """Test the full scrape → compare → database pipeline."""
    print("\n" + "=" * 60)
    print("  Testing full pipeline (scrape → database)")
    print("=" * 60)

    products = await scrape_products()
    if not products:
        print("❌ No products scraped. Cannot test pipeline.")
        return False

    print(f"✅ Scraped {len(products)} product(s)")

    # Test database
    test_db = Database(db_path=":memory:")
    for product in products:
        action, old = test_db.upsert_product(product)
        print(f"  → {action}: {product.name}")

    # Test second insert (should be "unchanged")
    print("\n  Re-inserting same products (expect 'unchanged'):")
    for product in products:
        action, old = test_db.upsert_product(product)
        assert action == "unchanged", f"Expected 'unchanged' but got '{action}'"
        print(f"  → {action}: {product.name} ✅")

    # Test availability change detection
    if products:
        test_product = Product(
            name=products[0].name,
            price=products[0].price,
            original_price=products[0].original_price,
            availability="Currently Unavailable",  # Changed!
            product_url=products[0].product_url,
            image_url=products[0].image_url,
        )
        action, old = test_db.upsert_product(test_product)
        assert action == "updated", f"Expected 'updated' but got '{action}'"
        print(f"\n  → Availability change detected: {old.availability} → {test_product.availability} ✅")

    print("\n✅ Full pipeline test passed!")
    return True


async def main():
    print("🏎️  Fanatec Stock Searcher — Scraper Test")
    print("=" * 60)

    cs_ok = await test_cloudscraper()
    pw_ok = await test_playwright()
    pipe_ok = await test_full_pipeline()

    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    print(f"  cloudscraper : {'✅ PASS' if cs_ok else '⚠️  FAIL (will use Playwright fallback)'}")
    print(f"  Playwright   : {'✅ PASS' if pw_ok else '❌ FAIL'}")
    print(f"  Full pipeline: {'✅ PASS' if pipe_ok else '❌ FAIL'}")

    if not cs_ok and not pw_ok:
        print("\n❌ CRITICAL: Both scraping strategies failed!")
        print("   Check your internet connection and try again.")
        sys.exit(1)
    elif pipe_ok:
        print("\n🎉 All good! Your bot is ready to run.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
