"""
Database module for Fanatec Stock Searcher.
Uses SQLite for lightweight state management of product data.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict

from config import DB_PATH, logger


@dataclass
class Product:
    """Represents a single Fanatec refurbished product."""
    name: str
    price: str
    original_price: str
    availability: str
    product_url: str
    image_url: str
    first_seen: str = ""
    last_seen: str = ""

    def is_available(self) -> bool:
        """Check if the product is currently purchasable."""
        avail_lower = self.availability.lower()
        return "available" in avail_lower and "unavailable" not in avail_lower

    def to_dict(self) -> dict:
        return asdict(self)


class Database:
    """SQLite database wrapper for product state management."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Use a persistent connection so :memory: databases work across calls
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the persistent connection (reconnect if closed)."""
        try:
            self._conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        """Create the products table if it doesn't exist."""
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    product_url   TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    price         TEXT NOT NULL,
                    original_price TEXT DEFAULT '',
                    availability  TEXT NOT NULL,
                    image_url     TEXT DEFAULT '',
                    first_seen    TEXT NOT NULL,
                    last_seen     TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrape_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    product_count INTEGER DEFAULT 0,
                    error_msg   TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword     TEXT NOT NULL UNIQUE,
                    added_at    TEXT NOT NULL
                )
            """)
            conn.commit()
            logger.info(f"Database initialised at {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Database init failed: {e}")
            raise

    # ── Product CRUD ─────────────────────────────────────────────────

    def get_product(self, product_url: str) -> Optional[Product]:
        """Get a product by its URL."""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM products WHERE product_url = ?",
                (product_url,),
            ).fetchone()
            if row:
                return Product(**dict(row))
            return None
        except sqlite3.Error as e:
            logger.error(f"Error fetching product: {e}")
            return None

    def get_all_products(self) -> list[Product]:
        """Get all tracked products."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM products ORDER BY name"
            ).fetchall()
            return [Product(**dict(row)) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error fetching all products: {e}")
            return []

    def upsert_product(self, product: Product) -> tuple[str, Optional[Product]]:
        """
        Insert or update a product. Returns a tuple of:
          - action: "new", "updated", or "unchanged"
          - old_product: the previous state if updated, else None
        """
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_product(product.product_url)

        try:
            conn = self._get_conn()
            if existing is None:
                # New product
                product.first_seen = now
                product.last_seen = now
                conn.execute(
                    """INSERT INTO products
                       (product_url, name, price, original_price,
                        availability, image_url, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        product.product_url, product.name, product.price,
                        product.original_price, product.availability,
                        product.image_url, product.first_seen, product.last_seen,
                    ),
                )
                conn.commit()
                logger.info(f"New product stored: {product.name}")
                return ("new", None)
            else:
                # Existing product — update
                conn.execute(
                    """UPDATE products SET
                       name = ?, price = ?, original_price = ?,
                       availability = ?, image_url = ?, last_seen = ?
                       WHERE product_url = ?""",
                    (
                        product.name, product.price, product.original_price,
                        product.availability, product.image_url, now,
                        product.product_url,
                    ),
                )
                conn.commit()

                # Detect meaningful changes
                if existing.availability != product.availability:
                    logger.info(
                        f"Availability changed for {product.name}: "
                        f"{existing.availability} -> {product.availability}"
                    )
                    return ("updated", existing)
                elif existing.price != product.price:
                    logger.info(
                        f"Price changed for {product.name}: "
                        f"{existing.price} -> {product.price}"
                    )
                    return ("updated", existing)
                return ("unchanged", existing)

        except sqlite3.Error as e:
            logger.error(f"Error upserting product {product.name}: {e}")
            return ("unchanged", existing)

    def get_disappeared_products(self, current_urls: set[str]) -> list[Product]:
        """
        Find products in DB that are NOT in the current scrape results.
        These may have been removed from the page.
        """
        all_products = self.get_all_products()
        return [p for p in all_products if p.product_url not in current_urls]

    def remove_product(self, product_url: str) -> None:
        """Remove a product from the database."""
        try:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM products WHERE product_url = ?",
                (product_url,),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error removing product: {e}")

    # ── Scrape logging ───────────────────────────────────────────────

    def log_scrape(self, status: str, product_count: int = 0, error_msg: str = "") -> None:
        """Log a scrape attempt for diagnostics."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO scrape_log (timestamp, status, product_count, error_msg)
                   VALUES (?, ?, ?, ?)""",
                (now, status, product_count, error_msg),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error logging scrape: {e}")

    def get_last_scrape(self) -> Optional[dict]:
        """Get the most recent scrape log entry."""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Error getting last scrape: {e}")
            return None

    def get_product_count(self) -> int:
        """Get the total number of tracked products."""
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error as e:
            logger.error(f"Error counting products: {e}")
            return 0

    # ── Watchlist ─────────────────────────────────────────────────────

    def add_watch(self, keyword: str) -> bool:
        """Add a keyword to the watchlist. Returns True if added, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (keyword, added_at) VALUES (?, ?)",
                (keyword.strip().lower(), now),
            )
            conn.commit()
            changed = conn.total_changes
            if changed:
                logger.info(f"Watchlist: added '{keyword}'")
                return True
            logger.info(f"Watchlist: '{keyword}' already exists")
            return False
        except sqlite3.Error as e:
            logger.error(f"Error adding watch: {e}")
            return False

    def remove_watch(self, keyword: str) -> bool:
        """Remove a keyword from the watchlist. Returns True if removed."""
        try:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM watchlist WHERE keyword = ?",
                (keyword.strip().lower(),),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Watchlist: removed '{keyword}'")
                return True
            return False
        except sqlite3.Error as e:
            logger.error(f"Error removing watch: {e}")
            return False

    def get_watchlist(self) -> list[dict]:
        """Get all watchlist entries."""
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT keyword, added_at FROM watchlist ORDER BY added_at"
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error fetching watchlist: {e}")
            return []

    def matches_watchlist(self, product_name: str) -> list[str]:
        """
        Check if a product name matches any watchlist keywords.
        Returns list of matched keywords (case-insensitive partial match).
        """
        watches = self.get_watchlist()
        name_lower = product_name.lower()
        return [
            w["keyword"] for w in watches
            if w["keyword"] in name_lower
        ]
