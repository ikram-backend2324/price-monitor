"""Demo shop: three fake online stores whose prices and stock change on their own.

The same service answers for several hostnames (docker network aliases):
``techbozor.demo``, ``megasavdo.demo``, ``smartmarket.demo``. The shop is picked
from the Host header, or from ``?shop=`` when opened via localhost.

Each shop renders product pages differently to exercise every adapter:
* techbozor   — JSON API at /api/product/<sku>  (DemoShopAdapter)
* megasavdo   — schema.org JSON-LD in the HTML  (JsonLdAdapter)
* smartmarket — plain HTML with CSS classes     (SelectorAdapter)
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

CATALOG = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))
SHOPS: dict[str, dict] = CATALOG["shops"]
CHANGE_INTERVAL = int(os.environ.get("DEMO_SHOP_CHANGE_INTERVAL", "180"))
CHANGE_SHARE = float(os.environ.get("DEMO_SHOP_CHANGE_SHARE", "0.15"))
SEED = int(os.environ.get("DEMO_SHOP_SEED", "42"))


def _round(value: float) -> int:
    step = 1000 if value >= 100_000 else 100
    return int(round(value / step) * step)


def initial_state(seed: int = SEED) -> dict[str, dict[str, dict]]:
    rng = random.Random(seed)
    state: dict[str, dict[str, dict]] = {}
    for code, shop in SHOPS.items():
        state[code] = {}
        for p in CATALOG["products"]:
            base = p["price"] * shop["factor"] * rng.uniform(0.97, 1.03)
            price = _round(base)
            has_discount = rng.random() < 0.3
            state[code][p["sku"]] = {
                "sku": p["sku"],
                "title": p["name"],
                "category": p["category"],
                "base": p["price"],
                "price": price,
                "old_price": _round(price * rng.uniform(1.08, 1.25)) if has_discount else None,
                "in_stock": rng.random() > 0.05,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
    return state


STATE = initial_state()
_rng = random.Random(SEED + 1)


def mutate(state: dict = STATE, share: float = CHANGE_SHARE, rng: random.Random = _rng) -> int:
    """Randomly change prices/stock of ~``share`` of all items. Returns number of changes."""
    changed = 0
    for items in state.values():
        for item in items.values():
            if rng.random() > share:
                continue
            roll = rng.random()
            if roll < 0.12:
                item["in_stock"] = not item["in_stock"]
            elif roll < 0.25 and item["old_price"] is None:
                # promo: put a discount on
                item["old_price"] = item["price"]
                item["price"] = _round(item["price"] * rng.uniform(0.80, 0.93))
            elif roll < 0.35 and item["old_price"] is not None:
                # promo ends
                item["price"], item["old_price"] = item["old_price"], None
            else:
                drift = rng.uniform(-0.08, 0.06)
                new = _round(item["price"] * (1 + drift))
                # stay within a sane corridor around the base price
                item["price"] = max(_round(item["base"] * 0.7), min(new, _round(item["base"] * 1.3)))
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed += 1
    return changed


async def _ticker() -> None:  # pragma: no cover - background loop
    while True:
        await asyncio.sleep(CHANGE_INTERVAL)
        mutate()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover - exercised in docker
    task = asyncio.create_task(_ticker()) if CHANGE_INTERVAL > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="PriceWatch demo shop", lifespan=lifespan)


def shop_code(request: Request) -> str:
    q = request.query_params.get("shop")
    if q in SHOPS:
        return q
    host = (request.headers.get("host") or "").split(":")[0]
    first = host.split(".")[0]
    return first if first in SHOPS else "techbozor"


def fmt(value: int | None) -> str:
    return f"{value:,}".replace(",", " ") if value is not None else ""


def get_item(code: str, sku: str) -> dict:
    item = STATE[code].get(sku)
    if item is None:
        raise HTTPException(404, "Product not found")
    return item


@app.get("/health")
def health():
    return {"status": "ok", "shops": list(SHOPS), "products": len(CATALOG["products"])}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /admin/\nDisallow: /cart\nAllow: /\n"


@app.get("/api/product/{sku}")
def api_product(sku: str, request: Request):
    code = shop_code(request)
    item = get_item(code, sku)
    return JSONResponse({**item, "shop": code, "currency": "UZS"})


@app.post("/_mutate")
def force_mutate(share: float = 0.5):
    """Testing helper: force a round of price changes right now."""
    return {"changed": mutate(share=share)}


PAGE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} — {shop}</title>
{head}
<style>body{{font-family:system-ui;margin:0;background:#f8fafc;color:#0f172a}}header{{background:{color};color:#fff;padding:14px 24px;font-weight:700}}
main{{max-width:960px;margin:24px auto;padding:0 16px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px}}a{{color:inherit}}.price{{font-size:28px;font-weight:700}}
.old{{text-decoration:line-through;color:#94a3b8}}.oos{{color:#dc2626;font-weight:600}}button{{background:{color};color:#fff;border:0;border-radius:8px;padding:10px 16px}}</style>
</head><body><header>{shop}</header><main>{body}</main></body></html>"""

COLORS = {"techbozor": "#0ea5e9", "megasavdo": "#16a34a", "smartmarket": "#9333ea"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    code = shop_code(request)
    cards = "".join(
        f'<div class="card"><a href="/product/{i["sku"]}?shop={code}">{html.escape(i["title"])}</a>'
        f'<div class="price">{fmt(i["price"])} сум</div>{"" if i["in_stock"] else "<div class=oos>Нет в наличии</div>"}</div>'
        for i in STATE[code].values()
    )
    return PAGE.format(
        title="Каталог", shop=SHOPS[code]["name"], color=COLORS[code], head="", body=f'<div class="grid">{cards}</div>'
    )


@app.get("/product/{sku}", response_class=HTMLResponse)
def product_page(sku: str, request: Request):
    code = shop_code(request)
    item = get_item(code, sku)
    style = SHOPS[code]["style"]
    title = html.escape(item["title"])
    head = ""
    if style in ("jsonld", "api"):
        offers = {
            "@type": "Offer",
            "price": str(item["price"]),
            "priceCurrency": "UZS",
            "availability": "https://schema.org/InStock" if item["in_stock"] else "https://schema.org/OutOfStock",
        }
        if item["old_price"]:
            offers["priceSpecification"] = [
                {"@type": "UnitPriceSpecification", "price": str(item["price"]), "priceCurrency": "UZS"},
                {
                    "@type": "UnitPriceSpecification",
                    "priceType": "https://schema.org/StrikethroughPrice",
                    "price": str(item["old_price"]),
                    "priceCurrency": "UZS",
                },
            ]
        ld = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": item["title"],
            "sku": item["sku"],
            "offers": offers,
        }
        head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
    old = f'<div class="old product-old-price">{fmt(item["old_price"])} сум</div>' if item["old_price"] else ""
    stock = (
        '<button class="add-to-cart">В корзину</button>'
        if item["in_stock"]
        else '<div class="oos out-of-stock">Нет в наличии</div>'
    )
    body = (
        f'<div class="card"><h1 class="product-title">{title}</h1>'
        f'<div class="price product-price">{fmt(item["price"])}&nbsp;сум</div>{old}{stock}'
        f'<p style="color:#64748b">SKU {item["sku"]} · {html.escape(item["category"])}</p></div>'
    )
    return PAGE.format(title=title, shop=SHOPS[code]["name"], color=COLORS[code], head=head, body=body)
