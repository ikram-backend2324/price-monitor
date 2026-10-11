"""Take portfolio screenshots of the running app.

    docker compose up -d && docker compose exec web python manage.py seed_demo
    python scripts/screenshots.py --base http://localhost --password demo12345

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost")
    parser.add_argument("--email", default="demo@pricewatch.local")
    parser.add_argument("--password", default="demo12345")
    parser.add_argument("--lang", default="ru")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="ru-RU")
        ctx.add_cookies([{"name": "django_language", "value": args.lang, "url": args.base}])
        page = ctx.new_page()

        def shot(name: str, full: bool = False) -> None:
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
            print("saved", name)

        page.goto(f"{args.base}/login/")
        shot("01-login")
        page.fill("#id_username", args.email)
        page.fill("#id_password", args.password)
        page.click("button[type=submit], form button")
        page.wait_for_url(re.compile(r".*/$"))
        shot("02-dashboard", full=True)

        page.goto(f"{args.base}/products/")
        shot("03-products")

        page.goto(f"{args.base}/products/?filter=expensive")
        first = page.locator("tbody tr").first
        first.click()
        page.wait_for_selector("canvas#chart")
        page.wait_for_timeout(1500)
        shot("04-product-detail", full=True)

        page.goto(f"{args.base}/alerts/")
        shot("05-alerts")
        page.goto(f"{args.base}/pricing/")
        shot("06-pricing-rules")
        page.goto(f"{args.base}/scrapers/")
        shot("07-scraper-health")
        page.goto(f"{args.base}/import/")
        shot("08-import-export")
        page.goto(f"{args.base}/billing/")
        shot("09-billing", full=True)
        page.goto(f"{args.base}/telegram/")
        shot("10-telegram")
        page.goto(f"{args.base}/api/docs/")
        page.wait_for_timeout(1500)
        shot("11-api-docs")

        # Dark theme
        page.goto(f"{args.base}/")
        page.evaluate("localStorage.setItem('pw-theme','dark')")
        page.reload()
        shot("12-dashboard-dark", full=True)
        page.goto(f"{args.base}/products/?filter=expensive")
        page.locator("tbody tr").first.click()
        page.wait_for_selector("canvas#chart")
        page.wait_for_timeout(1500)
        shot("13-product-detail-dark", full=True)

        # Mobile
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True
        )
        mobile.add_cookies(ctx.cookies())
        m = mobile.new_page()
        m.goto(f"{args.base}/")
        m.wait_for_timeout(800)
        m.screenshot(path=str(OUT / "14-mobile-dashboard.png"), full_page=True)
        print("saved 14-mobile-dashboard")

        # Admin "Test selectors on URL"
        admin = browser.new_context(viewport={"width": 1440, "height": 900})
        a = admin.new_page()
        a.goto(f"{args.base}/admin/login/")
        a.fill("#id_username", "admin@pricewatch.local")
        a.fill("#id_password", args.password)
        a.click("input[type=submit]")
        a.goto(f"{args.base}/admin/catalog/store/")
        a.wait_for_timeout(500)
        a.screenshot(path=str(OUT / "15-admin-stores.png"))
        print("saved 15-admin-stores")
        a.locator("a:has-text('Test selectors on URL')").nth(1).click()
        a.click("input[type=submit]")
        a.wait_for_timeout(1500)
        a.screenshot(path=str(OUT / "16-admin-selector-test.png"), full_page=True)
        print("saved 16-admin-selector-test")
        browser.close()


if __name__ == "__main__":
    main()
