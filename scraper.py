"""
Scraper module for Fanatec Stock Searcher.
Dual strategy: cloudscraper (lightweight) -> Playwright (full browser fallback).
"""

import re
import asyncio
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import (
    FANATEC_URL,
    FANATEC_BASE_URL,
    SCRAPER_TIMEOUT,
    USE_PLAYWRIGHT_ONLY,
    logger,
)
from database import Product


# ── HTML Parsing (shared by both strategies) ─────────────────────────

def _parse_products(html: str) -> list[Product]:
    """
    Parse product tiles from the Fanatec refurbished page HTML.
    Uses partial-match CSS selectors to survive Next.js class hash changes.
    Deduplicates by product URL.
    """
    soup = BeautifulSoup(html, "html.parser")
    raw_products: list[Product] = []

    # Find all product tile containers
    # The Fanatec site uses classes like "ProductTile_..." with dynamic hashes
    product_tiles = soup.find_all(
        lambda tag: tag.name in ("div", "article", "li")
        and tag.get("class")
        and any("ProductTile" in c or "product-tile" in c for c in tag.get("class", []))
    )

    # Fallback: if no tiles found with class matching, try broader search
    if not product_tiles:
        logger.warning("No ProductTile elements found. Trying broader selectors...")
        # Look for product links to certified-refurbished items
        product_links = soup.find_all("a", href=re.compile(r"/p/certified-refurbished/"))
        if product_links:
            # Go up to find the containing card for each link
            seen_containers = set()
            for link in product_links:
                container = link
                # Walk up to find a reasonable parent container
                for _ in range(5):
                    if container.parent:
                        container = container.parent
                        classes = " ".join(container.get("class", []))
                        if any(kw in classes.lower() for kw in ("tile", "card", "product", "item")):
                            break
                container_id = id(container)
                if container_id not in seen_containers:
                    seen_containers.add(container_id)
                    product_tiles.append(container)

    if not product_tiles:
        logger.warning("Could not find any product tiles on the page.")
        return []

    logger.info(f"Found {len(product_tiles)} raw product tile element(s) on page.")

    for tile in product_tiles:
        try:
            product = _extract_product_from_tile(tile)
            if product and product.product_url:
                raw_products.append(product)
        except Exception as e:
            logger.warning(f"Error parsing product tile: {e}")
            continue

    # ── Deduplicate by product URL ───────────────────────────────
    # The page may have nested elements that all match our selector,
    # producing duplicates. Keep the most complete version of each.
    seen_urls: dict[str, Product] = {}
    for p in raw_products:
        if p.product_url not in seen_urls:
            seen_urls[p.product_url] = p
        else:
            existing = seen_urls[p.product_url]
            # Prefer the version with more data (price, availability)
            if (p.price and not existing.price) or \
               (p.availability != "Unknown" and existing.availability == "Unknown"):
                seen_urls[p.product_url] = p

    products = list(seen_urls.values())
    if len(raw_products) != len(products):
        logger.info(
            f"Deduplicated {len(raw_products)} raw entries -> {len(products)} unique product(s)."
        )

    return products


def _clean_availability(raw_text: str) -> str:
    """
    Clean the raw availability text extracted from the tile.
    The tile text often contains concatenated price/status junk like:
      '€111.95EURCurrent price: €111.95€159.95Original price: €159.95Available'
    We want to extract just the status keyword.
    """
    text = raw_text.strip()

    # If it's already clean, return as-is
    clean_statuses = [
        "Available", "Currently Unavailable", "Sold Out",
        "Open for Backorder", "Out of Stock", "Unknown",
    ]
    for status in clean_statuses:
        if text == status:
            return status

    # Extract status from messy text
    lower = text.lower()
    if "currently unavailable" in lower:
        return "Currently Unavailable"
    elif "sold out" in lower:
        return "Sold Out"
    elif "out of stock" in lower:
        return "Out of Stock"
    elif "open for backorder" in lower:
        return "Open for Backorder"
    elif "available" in lower and "unavailable" not in lower:
        return "Available"

    return "Unknown"


def _extract_product_from_tile(tile) -> Optional[Product]:
    """Extract product data from a single tile element."""

    # ── Product Name ─────────────────────────────────────────────
    name = ""
    # Try: button or element with "product-name" in class
    name_el = tile.find(
        lambda t: t.get("class")
        and any("product-name" in c.lower() for c in t.get("class", []))
    )
    if name_el:
        name = name_el.get_text(strip=True)
    else:
        # Fallback: look for heading or strong tags
        for tag in ("h2", "h3", "h4", "strong", "b"):
            el = tile.find(tag)
            if el:
                name = el.get_text(strip=True)
                break
    if not name:
        # Last resort: first link text that looks like a product name
        link = tile.find("a")
        if link and link.get_text(strip=True):
            name = link.get_text(strip=True)

    if not name:
        return None

    # ── Product URL ──────────────────────────────────────────────
    product_url = ""
    link = tile.find("a", href=re.compile(r"/p/certified-refurbished/"))
    if not link:
        link = tile.find("a", href=re.compile(r"/p/"))
    if link:
        product_url = urljoin(FANATEC_BASE_URL, link["href"])
    else:
        # Any link in the tile
        link = tile.find("a", href=True)
        if link:
            product_url = urljoin(FANATEC_BASE_URL, link["href"])

    if not product_url:
        return None  # Can't track a product without a URL

    # ── Price ────────────────────────────────────────────────────
    price = ""
    original_price = ""

    # Strategy: look for specific current/original price elements
    # Fanatec uses classes like "ProductActionButton_current-price__..."
    current_price_el = tile.find(
        lambda t: t.get("class")
        and any(
            "current" in c.lower() and "price" in c.lower()
            for c in t.get("class", [])
        )
    )
    original_price_el = tile.find(
        lambda t: t.get("class")
        and any(
            ("original" in c.lower() or "old" in c.lower() or "regular" in c.lower())
            and "price" in c.lower()
            for c in t.get("class", [])
        )
    )

    if current_price_el:
        matches = re.findall(r"[€$£]\s?\d+[\.,]\d{2}", current_price_el.get_text(strip=True))
        if matches:
            price = matches[0].replace(" ", "")
    if original_price_el:
        matches = re.findall(r"[€$£]\s?\d+[\.,]\d{2}", original_price_el.get_text(strip=True))
        if matches:
            original_price = matches[0].replace(" ", "")

    # Fallback: search all price-classed elements
    if not price:
        price_els = tile.find_all(
            lambda t: t.get("class")
            and any("price" in c.lower() for c in t.get("class", []))
        )
        all_prices = []
        for price_el in price_els:
            matches = re.findall(r"[€$£]\s?\d+[\.,]\d{2}", price_el.get_text(strip=True))
            all_prices.extend(m.replace(" ", "") for m in matches)
        # Deduplicate while preserving order
        unique_prices = list(dict.fromkeys(all_prices))
        if unique_prices:
            price = unique_prices[0]
            if len(unique_prices) > 1:
                original_price = unique_prices[1]

    # Last fallback: search entire tile text
    if not price:
        tile_text = tile.get_text(" ", strip=True)
        price_matches = re.findall(r"[€$£]\s?\d+[\.,]\d{2}", tile_text)
        unique_prices = list(dict.fromkeys(m.replace(" ", "") for m in price_matches))
        if unique_prices:
            price = unique_prices[0]
            if len(unique_prices) > 1:
                original_price = unique_prices[1]

    # Ensure original_price != price (not useful to show the same value)
    if original_price == price:
        original_price = ""

    # ── Availability ─────────────────────────────────────────────
    availability = "Unknown"

    # Strategy 1: Look for elements with availability-related class names
    avail_el = tile.find(
        lambda t: t.get("class")
        and any(
            kw in c.lower()
            for c in t.get("class", [])
            for kw in ("avail", "stock", "status", "delivery")
        )
    )
    if avail_el:
        availability = _clean_availability(avail_el.get_text(strip=True))

    # Strategy 2: Check for Add to Cart button
    if availability == "Unknown":
        add_to_cart = tile.find(
            lambda t: t.name in ("button", "a")
            and t.get_text(strip=True).lower() in ("add to cart", "add to basket")
        )
        if add_to_cart:
            availability = "Available"

    # Strategy 3: Search tile text for status keywords
    if availability == "Unknown":
        tile_text = tile.get_text(" ", strip=True)
        availability = _clean_availability(tile_text)

    # ── Image URL ────────────────────────────────────────────────
    image_url = ""
    img = tile.find("img")
    if img:
        src = img.get("src") or img.get("data-src") or ""
        if src:
            image_url = urljoin(FANATEC_BASE_URL, src)

    return Product(
        name=name,
        price=price,
        original_price=original_price,
        availability=availability,
        product_url=product_url,
        image_url=image_url,
    )


# ── Strategy 1: cloudscraper ─────────────────────────────────────────

def _scrape_with_cloudscraper() -> Optional[str]:
    """
    Attempt to fetch the page using cloudscraper.
    Returns HTML string or None on failure.
    """
    try:
        import cloudscraper

        scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            },
            delay=5,
        )
        response = scraper.get(
            FANATEC_URL,
            timeout=SCRAPER_TIMEOUT,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        response.raise_for_status()

        if len(response.text) < 1000:
            logger.warning("cloudscraper response too short, likely blocked.")
            return None

        # Quick sanity check: does the HTML contain product-related content?
        if "refurbished" not in response.text.lower() and "product" not in response.text.lower():
            logger.warning("cloudscraper HTML doesn't look like a product page.")
            return None

        logger.info(
            f"cloudscraper fetched {len(response.text)} chars successfully."
        )
        return response.text

    except ImportError:
        logger.warning("cloudscraper not installed. Skipping.")
        return None
    except Exception as e:
        logger.warning(f"cloudscraper failed: {e}")
        return None


# ── Strategy 2: Playwright ───────────────────────────────────────────

async def _scrape_with_playwright() -> Optional[str]:
    """
    Fetch the page using a headless Chromium browser via Playwright.
    Uses playwright-stealth to avoid bot detection.
    Returns HTML string or None on failure.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    try:
        from playwright_stealth import stealth_async
    except ImportError:
        stealth_async = None
        logger.warning("playwright-stealth not installed. Proceeding without stealth.")

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # Apply stealth patches if available
            if stealth_async:
                await stealth_async(page)

            logger.info(f"Playwright navigating to {FANATEC_URL}")
            await page.goto(FANATEC_URL, wait_until="networkidle", timeout=SCRAPER_TIMEOUT * 1000)

            # Wait for product content to render
            try:
                await page.wait_for_selector(
                    '[class*="ProductTile"], [class*="product-tile"], a[href*="/p/certified-refurbished/"]',
                    timeout=15000,
                )
            except Exception:
                logger.warning("Timed out waiting for product tiles. Page may be empty or blocked.")

            # Small delay for any lazy-loaded content
            await asyncio.sleep(2)

            html = await page.content()
            logger.info(f"Playwright fetched {len(html)} chars successfully.")
            return html

    except Exception as e:
        logger.error(f"Playwright failed: {e}")
        return None
    finally:
        if browser:
            await browser.close()


# ── Public API ───────────────────────────────────────────────────────

async def scrape_products() -> list[Product]:
    """
    Scrape the Fanatec refurbished page and return a list of Product objects.
    Tries cloudscraper first, falls back to Playwright.
    """
    html: Optional[str] = None

    if not USE_PLAYWRIGHT_ONLY:
        # Strategy 1: cloudscraper (fast, lightweight)
        logger.info("Attempting scrape with cloudscraper...")
        html = _scrape_with_cloudscraper()

        if html:
            products = _parse_products(html)
            if products:
                logger.info(f"cloudscraper extracted {len(products)} product(s).")
                return products
            else:
                logger.warning(
                    "cloudscraper fetched HTML but no products parsed. "
                    "Page may be JS-rendered. Falling back to Playwright."
                )
                html = None

    # Strategy 2: Playwright (full browser)
    if html is None:
        logger.info("Attempting scrape with Playwright...")
        html = await _scrape_with_playwright()

        if html:
            products = _parse_products(html)
            if products:
                logger.info(f"Playwright extracted {len(products)} product(s).")
                return products
            else:
                logger.warning("Playwright fetched HTML but no products parsed.")

    logger.error("All scraping strategies failed.")
    return []
