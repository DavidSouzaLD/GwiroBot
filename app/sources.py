"""Coleta de ofertas nas lojas configuradas."""

from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORES = (
    ("mercadolivre", "Mercado Livre"),
    ("amazon", "Amazon"),
    ("shopee", "Shopee"),
    ("aliexpress", "AliExpress"),
)
LABELS = dict(STORES)


class SourceError(Exception):
    pass


def keywords_of(text: str, limit: int = 8) -> list[str]:
    lines = []
    for raw in str(text or "").splitlines():
        item = raw.strip()
        if item and item not in lines:
            lines.append(item)
    return lines[:limit]


def collect(name: str, market: dict, timeout: int) -> tuple[list[dict], list[str]]:
    if name == "mercadolivre":
        found = fetch_mercadolivre_deals(market, timeout)
        unique = []
        seen = set()
        for offer in sorted(found, key=lambda item: item["discount"], reverse=True):
            if offer["id"] in seen:
                continue
            seen.add(offer["id"])
            unique.append(offer)
        unique = filter_by_price(unique, market)
        niche = str(market.get("nicheName") or "").strip()
        if niche:
            for offer in unique:
                offer["niche"] = niche
        return unique, []

    fetcher = FETCHERS[name]
    found: list[dict] = []
    errors: list[str] = []
    terms = keywords_of(market.get("keywords"))
    if not terms:
        raise SourceError("Informe ao menos uma palavra-chave.")
    for index, term in enumerate(terms):
        if index:
            time.sleep(0.4 if name != "amazon" else 1.1)
        try:
            found.extend(fetcher(market, term, timeout))
        except SourceError as error:
            errors.append(str(error))
    if errors and not found:
        raise SourceError(errors[-1])
    unique = []
    seen = set()
    for offer in sorted(found, key=lambda item: item["discount"], reverse=True):
        if offer["id"] in seen:
            continue
        seen.add(offer["id"])
        unique.append(offer)
    unique = filter_by_price(unique, market)
    niche = str(market.get("nicheName") or "").strip()
    if niche:
        for offer in unique:
            offer["niche"] = niche
    return unique, [] if not found else errors


ML_OFFERS = "https://www.mercadolivre.com.br/ofertas"
ML_LIST = "https://lista.mercadolivre.com.br/"
ML_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
ML_CREATELINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_ID = re.compile(r"(MLB-?\d{6,})")
ML_FRESH_SECONDS = 180
ML_PAGES_PER_CYCLE = 8
# IDs da página de ofertas. A chave fica em minúsculas.
ML_CATEGORIES = {
    "casa e utilidades": "MLB1574",
    "casa": "MLB1574",
    "móveis e decoração": "MLB1574",
    "cozinha e utensílios": "MLB1574",
    "eletrônicos": "MLB1000",
    "informática e hardware": "MLB1648",
    "informática": "MLB1648",
    "periféricos gamer": "MLB1648",
    "games e consoles": "MLB1144",
    "games": "MLB1144",
    "celulares e smartphones": "MLB1051",
    "acessórios para celular": "MLB1051",
    "celulares": "MLB1051",
    "eletrodomésticos": "MLB5726",
    "automotivo": "MLB5672",
    "motos e acessórios": "MLB5672",
    "moda masculina": "MLB1430",
    "moda feminina": "MLB1430",
    "moda e acessórios": "MLB1430",
    "moda": "MLB1430",
    "beleza e cuidados pessoais": "MLB1246",
    "beleza": "MLB1246",
    "saúde e bem-estar": "MLB264586",
    "saúde": "MLB264586",
    "academia e fitness": "MLB1276",
    "esportes": "MLB1276",
    "produtos para pets": "MLB1071",
    "pet": "MLB1071",
    "bebês e crianças": "MLB1132",
    "brinquedos e colecionáveis": "MLB1132",
    "brinquedos": "MLB1132",
    "livros e educação": "MLB1196",
    "livros": "MLB1196",
}
ML_SKIP = (
    "ofertas amazon",
    "ofertas mercado livre",
    "ofertas shopee",
    "ofertas aliexpress",
    "cupons e cashback",
    "achadinhos baratos",
    "produtos virais",
    "produtos criativos e diy",
)


def fetch_mercadolivre(market: dict, keyword: str, timeout: int) -> list[dict]:
    scoped = dict(market)
    scoped["keywords"] = keyword
    return fetch_mercadolivre_deals(scoped, timeout)


def fetch_mercadolivre_deals(market: dict, timeout: int) -> list[dict]:
    return collect_ml([market], int(market.get("limit") or 8), timeout)


def collect_ml(plans: list[dict], limit: int, timeout: int) -> list[dict]:
    """Cada ciclo percorre várias categorias ou palavras, no Chrome que já está aberto."""
    payload = []
    for plan in plans:
        payload.append(
            {
                "terms": keywords_of(plan.get("keywords"), 80),
                "minDiscount": int(plan.get("minDiscount") or 0),
                "minPrice": plan.get("minPrice") or 0,
                "maxPrice": plan.get("maxPrice") or 0,
                "limit": max(1, int(limit)),
                "niche": plan.get("nicheName") or "",
                "etiqueta": str(plan.get("mattTool") or "").strip(),
                "mattWord": plan.get("mattWord") or "",
            }
        )
    return _ML.call(payload, max(int(timeout or 20), 70))


class _MlBrowser:
    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="ogwiro-ml", daemon=True)
        self._thread.start()

    def call(self, plans: list[dict], timeout: int) -> list[dict]:
        done: queue.Queue = queue.Queue(1)
        self._jobs.put((plans, done))
        try:
            ok, value = done.get(timeout=timeout + 20)
        except queue.Empty as error:
            raise SourceError("A busca do Mercado Livre passou do tempo.") from error
        if not ok:
            raise SourceError(str(value))
        return value

    def close(self) -> None:
        self._jobs.put(None)

    def _loop(self) -> None:
        playwright = None
        context = None
        page = None
        pages: dict[str, tuple[float, list[dict]]] = {}
        cursor = 0
        link_ready = False
        shorts: dict[str, str] = {}
        while True:
            job = self._jobs.get()
            if job is None:
                _ml_close(context, playwright)
                return
            plans, done = job
            try:
                playwright, context, page = _ml_open(playwright, context, page)
                cards, cursor, link_ready = self._fill(
                    page, plans, pages, cursor, link_ready, shorts
                )
                offers = _ml_pick(cards, plans, shorts)
                done.put((True, offers))
            except SourceError as error:
                done.put((False, str(error)))
            except Exception as error:
                _ml_close(context, playwright)
                playwright = context = page = None
                link_ready = False
                pages = {}
                done.put((False, str(error)))

    def _fill(self, page, plans, pages, cursor, link_ready, shorts):
        targets = _ml_targets(plans)
        if not targets:
            targets = [{"url": ML_OFFERS, "label": "", "niche": "", "minDiscount": 0, "minPrice": 0, "maxPrice": 0}]
        count = min(ML_PAGES_PER_CYCLE, len(targets))
        start = cursor % len(targets)
        batch = [targets[(start + index) % len(targets)] for index in range(count)]
        cursor = (start + count) % len(targets)
        cards = []
        seen = set()
        for target in batch:
            for card in _ml_cached(page, pages, target["url"]):
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                stamped = dict(card)
                stamped["term"] = target["label"]
                stamped["niche"] = target["niche"]
                stamped["minDiscount"] = target["minDiscount"]
                stamped["minPrice"] = target["minPrice"]
                stamped["maxPrice"] = target["maxPrice"]
                cards.append(stamped)
        chosen = []
        try:
            chosen = _ml_pick(cards, plans, shorts)
        except SourceError:
            chosen = []
        etiqueta = next((plan["etiqueta"] for plan in plans if plan["etiqueta"]), "")
        if etiqueta and chosen:
            link_ready = _ml_link(page, chosen, etiqueta, link_ready, shorts)
        return cards, cursor, link_ready


def _ml_open(playwright, context, page):
    if page is not None:
        try:
            if not page.is_closed():
                return playwright, context, page
        except Exception:
            pass
    _ml_close(context, playwright)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SourceError("Instale o navegador da busca: python -m pip install playwright beautifulsoup4") from error
    playwright = sync_playwright().start()
    context = _ml_browser(playwright)
    context.route("**/*", _ml_block)
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


def _ml_close(context, playwright) -> None:
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        if playwright is not None:
            playwright.stop()
    except Exception:
        pass


def _ml_block(route) -> None:
    if route.request.resource_type in {"image", "media", "font"}:
        route.abort()
    else:
        route.continue_()


def _ml_profile() -> Path:
    from app.store import DATA

    local = DATA / "ml_profile"
    borrowed = Path(r"C:\Users\david\Downloads\bot-ofertas-telegram\data\ml_profile")
    for folder in (local, borrowed):
        if folder.exists() and any(folder.iterdir()):
            return folder
    local.mkdir(parents=True, exist_ok=True)
    return local


def _ml_browser(pw):
    profile = _ml_profile()
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-extensions",
        "--window-position=-32000,-32000",
        "--window-size=1100,700",
    ]
    options = {
        "headless": False,
        "locale": "pt-BR",
        "args": args,
        "ignore_default_args": ["--enable-automation"],
        "no_viewport": True,
    }
    try:
        return pw.chromium.launch_persistent_context(str(profile), channel="chrome", **options)
    except Exception as error:
        if "chrome" not in str(error).lower():
            raise SourceError(f"Não abri o Chrome da busca. {error}") from error
        return pw.chromium.launch_persistent_context(str(profile), **options)


def _ml_fold(text: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip()


def _ml_category(label: str) -> str:
    key = _ml_fold(label)
    for name, category_id in ML_CATEGORIES.items():
        if _ml_fold(name) == key:
            return category_id
    return ""


def _ml_targets(plans: list[dict]) -> list[dict]:
    skipped = tuple(_ml_fold(item) for item in ML_SKIP)
    targets = []
    seen = set()
    for plan in plans:
        for term in plan.get("terms") or []:
            folded = _ml_fold(term)
            if not folded or any(item in folded for item in skipped):
                continue
            category_id = _ml_category(term)
            url = f"{ML_OFFERS}?category={category_id}" if category_id else _ml_search_url(term)
            if url in seen:
                continue
            seen.add(url)
            targets.append(
                {
                    "url": url,
                    "label": term,
                    "niche": plan.get("niche") or "",
                    "minDiscount": plan.get("minDiscount") or 0,
                    "minPrice": plan.get("minPrice") or 0,
                    "maxPrice": plan.get("maxPrice") or 0,
                }
            )
    return targets


def _ml_cached(page, pages: dict, url: str) -> list[dict]:
    cached = pages.get(url)
    if cached and time.time() - cached[0] < ML_FRESH_SECONDS:
        return cached[1]
    found = _ml_read(page, url)
    pages[url] = (time.time(), found)
    return found


def _ml_read(page, url: str) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=20000)
    try:
        page.wait_for_selector("div.poly-card", timeout=8000)
    except Exception:
        if any(mark in page.url for mark in ("account-verification", "/captcha/", "login")):
            raise SourceError("O Mercado Livre pediu verificação no Chrome. Abra o login do afiliado e tente de novo.")
        return []
    return _parse_ml_html(page.content())


def _ml_product_url(href: str, product_id: str) -> str:
    number = product_id.replace("-", "")
    if number.startswith("MLB") and ("mclics" in href or "click1.mercadolivre" in href):
        return f"https://produto.mercadolivre.com.br/MLB-{number[3:]}"
    return href.split("#")[0].split("?")[0]


def _ml_search_url(term: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", term.casefold()).strip("-")
    return ML_LIST + urllib.parse.quote(slug or "ofertas")


def _parse_ml_html(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select("div.poly-card"):
        link = card.select_one("a.poly-component__title")
        if not (link and link.get("href")):
            continue
        href = str(link["href"])
        found_ids = ML_ID.findall(href)
        product_id = found_ids[-1].replace("-", "") if found_ids else ""
        if not product_id:
            product_id = href.split("#")[0].split("?")[0].rstrip("/").rsplit("/", 1)[-1][:40]
        url = _ml_product_url(href, product_id)
        price = _ml_money(card, ".poly-price__current")
        original = _ml_money(card, "s.andes-money-amount--previous")
        discount = 0
        badge = card.select_one(".poly-price__discount-polylabel, .andes-money-amount__discount")
        if badge:
            match = re.search(r"(\d+)\s*%", badge.get_text())
            discount = int(match.group(1)) if match else 0
        if not discount:
            discount = discount_pct(price, original)
        if discount and price and not original and discount < 100:
            original = round(price / (1 - discount / 100), 2)
        image_node = card.select_one("img.poly-component__picture")
        image = ""
        if image_node:
            image = image_node.get("data-src") or image_node.get("src") or ""
            if str(image).startswith("data:"):
                image = ""
        cards.append(
            {
                "id": product_id,
                "title": link.get_text(" ", strip=True),
                "url": url,
                "price": price,
                "original": original,
                "discount": discount,
                "image": image,
                "extra": _ml_extra(card),
            }
        )
    return cards


def _ml_extra(card) -> str:
    parts = []
    review = card.select_one(".poly-component__review-compacted")
    if review:
        text = re.sub(r"\s*\|\s*", " · ", review.get_text(" ", strip=True))
        text = re.sub(r"\s+", " ", text).strip(" ·")
        if text:
            parts.append("⭐️ " + text)
    pix = card.select_one(".poly-price__unit-description")
    if pix and "pix" in pix.get_text(" ", strip=True).lower():
        parts.append("💠 preço no Pix")
    if "frete grátis" in card.get_text(" ", strip=True).lower():
        parts.append("🚚 Frete grátis")
    return " · ".join(parts)


def _ml_money(card, selector: str):
    whole = card.select_one(f"{selector} .andes-money-amount__fraction")
    if not whole:
        return None
    cents = card.select_one(f"{selector} .andes-money-amount__cents")
    text = whole.get_text(strip=True)
    if cents:
        text += "," + cents.get_text(strip=True)
    return parse_brl(text)


def _ml_pick_cards(cards: list[dict], plan: dict) -> list[dict]:
    minimum = int(plan["minDiscount"] or 0)
    niche = plan.get("niche") or ""
    chosen = []
    for card in sorted(cards, key=lambda item: item["discount"], reverse=True):
        if niche and card.get("niche") not in {"", niche}:
            continue
        if card["discount"] < minimum:
            continue
        chosen.append(card)
        if len(chosen) >= plan["limit"]:
            break
    return chosen


def _ml_pick(cards: list[dict], plans: list[dict], shorts: dict[str, str]) -> list[dict]:
    offers = []
    seen = set()
    for plan in plans:
        for card in _ml_pick_cards(cards, plan):
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            matched = card.get("term") or _match_keyword(card["title"], plan["terms"])
            offer = make_offer(
                "mercadolivre",
                card["id"],
                card["title"],
                card["price"],
                card["original"],
                "BRL",
                shorts.get(card["url"]) or card["url"],
                card["image"],
                matched or (plan["terms"][0] if plan["terms"] else ""),
                extra=card.get("extra") or "",
            )
            if card["discount"] and offer["discount"] < card["discount"]:
                offer["discount"] = card["discount"]
            if plan["niche"]:
                offer["niche"] = plan["niche"]
            offer = filter_by_price([offer], plan)
            if not offer:
                continue
            offers.append(offer[0])
    if cards and not offers:
        raise SourceError(
            f"A vitrine do Mercado Livre abriu com {len(cards)} produto(s), mas nenhum passou no desconto ou nas palavras do nicho."
        )
    if not offers:
        raise SourceError("A vitrine do Mercado Livre abriu sem produtos. A sessão do Chrome pode ter caído na verificação.")
    return offers


def _ml_link(page, offers: list[dict], etiqueta: str, link_ready: bool, shorts: dict[str, str]) -> bool:
    if "linkbuilder" not in page.url:
        page.goto(ML_LINKBUILDER, wait_until="domcontentloaded", timeout=20000)
        link_ready = False
    if "login" in page.url or "registration" in page.url:
        return link_ready
    if not link_ready:
        page.wait_for_timeout(400)
    urls = []
    for offer in offers:
        product = offer["url"]
        if "meli.la/" in product or product in shorts:
            continue
        urls.append(product)
    try:
        for start in range(0, len(urls), 10):
            batch = urls[start:start + 10]
            result = page.evaluate(
                """async ({api, urls, tag}) => {
                    const resp = await fetch(api, {
                        method: 'POST',
                        headers: {'content-type': 'application/json'},
                        body: JSON.stringify({urls, tag}),
                    });
                    const text = await resp.text();
                    try { return {http: resp.status, dados: JSON.parse(text)}; }
                    catch (e) { return {http: resp.status}; }
                }""",
                {"api": ML_CREATELINK, "urls": batch, "tag": etiqueta},
            )
            if result.get("http") != 200 or not result.get("dados"):
                break
            links = [item.get("short_url") or "" for item in (result["dados"].get("urls") or [])]
            if len(links) != len(batch) or not all(links):
                break
            for product, link in zip(batch, links):
                shorts[product] = link
    except Exception:
        return "linkbuilder" in page.url
    for product in urls:
        if product not in shorts:
            shorts[product] = affiliate_ml(product, {"mattTool": etiqueta, "mattWord": ""})
    return True


_ML = _MlBrowser()
atexit.register(_ML.close)


def _match_keyword(title: str, terms: list[str]) -> str:
    haystack = title.casefold()
    for term in terms:
        words = [word for word in re.split(r"\s+", term.casefold()) if len(word) >= 3]
        if words and any(word in haystack for word in words):
            return term
    return ""


def parse_brl(text: str):
    digits = re.sub(r"[^\d,]", "", str(text or ""))
    if not digits:
        return None
    return as_float(digits.replace(".", "").replace(",", "."))


def fetch_amazon(market: dict, keyword: str, timeout: int) -> list[dict]:
    access = str(market.get("accessKey") or "").strip()
    secret = str(market.get("secretKey") or "").strip()
    tag = str(market.get("partnerTag") or "").strip()
    host = str(market.get("host") or "webservices.amazon.com.br").strip()
    region = str(market.get("region") or "us-east-1").strip()
    marketplace = str(market.get("marketplace") or "www.amazon.com.br").strip()
    if not (access and secret and tag):
        raise SourceError("Preencha access key, secret key e partner tag da Amazon.")

    body = {
        "Keywords": keyword,
        "PartnerTag": tag,
        "PartnerType": "Associates",
        "Marketplace": marketplace,
        "ItemCount": min(int(market.get("limit") or 5), 10),
        "Resources": [
            "Images.Primary.Medium",
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.SavingBasis",
        ],
    }
    payload = json.dumps(body, separators=(",", ":"))
    target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    headers = amazon_headers(access, secret, region, host, payload, target)
    data = request_json(f"https://{host}/paapi5/searchitems", payload.encode("utf-8"), headers, timeout)
    if data.get("Errors"):
        message = data["Errors"][0].get("Message") or "A Amazon recusou a busca."
        raise SourceError(message)

    offers = []
    for item in (data.get("SearchResult") or {}).get("Items") or []:
        listings = ((item.get("Offers") or {}).get("Listings")) or []
        listing = listings[0] if listings else {}
        price_info = listing.get("Price") or {}
        basis = listing.get("SavingBasis") or {}
        price = as_float(price_info.get("Amount"))
        original = as_float(basis.get("Amount"))
        discount = discount_pct(price, original)
        if discount < int(market.get("minDiscount") or 0):
            continue
        title = ((item.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue")
        image = (((item.get("Images") or {}).get("Primary") or {}).get("Medium") or {}).get("URL") or ""
        currency = price_info.get("Currency") or "BRL"
        offers.append(
            make_offer(
                "amazon",
                str(item.get("ASIN") or item.get("DetailPageURL") or ""),
                title or "Oferta Amazon",
                price,
                original,
                currency,
                item.get("DetailPageURL") or "",
                image,
                keyword,
                price_info.get("DisplayAmount"),
                basis.get("DisplayAmount"),
            )
        )
    return offers


def fetch_shopee(market: dict, keyword: str, timeout: int) -> list[dict]:
    app_id = str(market.get("appId") or "").strip()
    secret = str(market.get("secret") or "").strip()
    if not (app_id and secret):
        raise SourceError("Preencha App ID e Secret da Shopee Afiliados.")

    limit = min(int(market.get("limit") or 8), 20)
    query = (
        "{ productOfferV2(keyword: "
        + json.dumps(keyword)
        + f", sortType: 2, page: 1, limit: {limit}) "
        + "{ nodes { itemId productName offerLink productLink imageUrl priceMin priceMax priceDiscountRate shopName } } }"
    )
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signature = hashlib.sha256(f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}",
    }
    data = request_json(
        "https://open-api.affiliate.shopee.com.br/graphql",
        payload.encode("utf-8"),
        headers,
        timeout,
    )
    if data.get("errors"):
        message = data["errors"][0].get("message") or "A Shopee recusou a busca."
        raise SourceError(message)
    nodes = (((data.get("data") or {}).get("productOfferV2") or {}).get("nodes")) or []
    divisor = max(int(market.get("priceDivisor") or 1), 1)
    offers = []
    for node in nodes:
        discount = as_float(node.get("priceDiscountRate")) or 0
        if 0 < discount <= 1:
            discount *= 100
        if discount < int(market.get("minDiscount") or 0):
            continue
        price = money_div(node.get("priceMin"), divisor)
        original = None
        if price is not None and discount:
            original = round(price / (1 - discount / 100), 2) if discount < 100 else price
        url = node.get("offerLink") or node.get("productLink") or ""
        offers.append(
            make_offer(
                "shopee",
                str(node.get("itemId") or url),
                node.get("productName") or "Oferta Shopee",
                price,
                original,
                "BRL",
                url,
                node.get("imageUrl") or "",
                keyword,
            )
        )
    return offers


def fetch_aliexpress(market: dict, keyword: str, timeout: int) -> list[dict]:
    app_key = str(market.get("appKey") or "").strip()
    secret = str(market.get("appSecret") or "").strip()
    if not (app_key and secret):
        raise SourceError("Preencha App Key e App Secret do AliExpress.")

    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "method": "aliexpress.affiliate.product.query",
        "app_key": app_key,
        "sign_method": "sha256",
        "timestamp": stamp,
        "format": "json",
        "v": "2.0",
        "simplify": "true",
        "keywords": keyword,
        "page_no": "1",
        "page_size": str(min(int(market.get("limit") or 8), 20)),
        "sort": str(market.get("sort") or "LAST_VOLUME_DESC"),
        "target_currency": str(market.get("currency") or "BRL"),
        "target_language": str(market.get("language") or "PT"),
        "ship_to_country": str(market.get("shipTo") or "BR"),
        "fields": "product_id,product_title,product_main_image_url,promotion_link,product_detail_url,target_sale_price,target_original_price,target_sale_price_currency,discount",
    }
    tracking = str(market.get("trackingId") or "").strip()
    if tracking:
        params["tracking_id"] = tracking
    material = "".join(f"{key}{params[key]}" for key in sorted(params))
    params["sign"] = hmac.new(secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    body = urllib.parse.urlencode(params).encode("utf-8")
    data = request_json(
        "https://api-sg.aliexpress.com/sync",
        body,
        {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout,
    )
    if data.get("error_response"):
        message = data["error_response"].get("msg") or data["error_response"].get("sub_msg") or "O AliExpress recusou a busca."
        raise SourceError(message)

    products = find_products(data)
    offers = []
    for product in products:
        price = as_float(product.get("target_sale_price"))
        original = as_float(product.get("target_original_price") or product.get("original_price"))
        discount = parse_percent(product.get("discount"))
        if not discount:
            discount = discount_pct(price, original)
        if discount < int(market.get("minDiscount") or 0):
            continue
        currency = product.get("target_sale_price_currency") or market.get("currency") or "BRL"
        url = product.get("promotion_link") or product.get("product_detail_url") or ""
        offers.append(
            make_offer(
                "aliexpress",
                str(product.get("product_id") or url),
                product.get("product_title") or "Oferta AliExpress",
                price,
                original,
                currency,
                url,
                product.get("product_main_image_url") or "",
                keyword,
            )
        )
    return offers


FETCHERS = {
    "mercadolivre": fetch_mercadolivre,
    "amazon": fetch_amazon,
    "shopee": fetch_shopee,
    "aliexpress": fetch_aliexpress,
}


def request_json(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 20) -> dict:
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "OgwiroOfertas/1.0")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        raise SourceError(f"HTTP {error.code}. {detail or error.reason}") from error
    except urllib.error.URLError as error:
        raise SourceError(f"Sem conexão com a vitrine. {error.reason}") from error
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise SourceError("A vitrine não devolveu JSON.") from error
    if not isinstance(parsed, dict):
        raise SourceError("Resposta inesperada da vitrine.")
    return parsed


def amazon_headers(access: str, secret: str, region: str, host: str, payload: str, target: str) -> dict:
    service = "ProductAdvertisingAPI"
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_headers = (
        "content-encoding:amz-1.0\n"
        "content-type:application/json; charset=utf-8\n"
        f"host:{host}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{target}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    canonical = "\n".join(
        ["POST", "/paapi5/searchitems", "", canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ]
    )
    key = ("AWS4" + secret).encode("utf-8")
    for part in (date_stamp, region, service, "aws4_request"):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "x-amz-date": amz_date,
        "x-amz-target": target,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }


def affiliate_ml(url: str, market: dict) -> str:
    if not url:
        return ""
    tool = str(market.get("mattTool") or "").strip()
    word = str(market.get("mattWord") or "").strip()
    extra = []
    if tool:
        extra.append("matt_tool=" + urllib.parse.quote(tool))
    if word:
        extra.append("matt_word=" + urllib.parse.quote(word))
    if not extra:
        return url
    joiner = "&" if "?" in url else "?"
    return url + joiner + "&".join(extra)


def make_offer(
    store: str,
    product_id: str,
    title: str,
    price: float | None,
    original: float | None,
    currency: str,
    url: str,
    image: str,
    keyword: str,
    price_label: str | None = None,
    original_label: str | None = None,
    extra: str = "",
) -> dict:
    discount = discount_pct(price, original)
    identity = f"{store}:{product_id}"
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "store": store,
        "storeLabel": LABELS[store],
        "title": re.sub(r"\s+", " ", str(title)).strip()[:180],
        "price": price,
        "original": original,
        "currency": currency or "BRL",
        "priceLabel": price_label or format_money(price, currency),
        "originalLabel": original_label or format_money(original, currency),
        "discount": discount,
        "url": url if str(url).startswith("http") else "",
        "image": clean_image(image),
        "extra": re.sub(r"\s+", " ", str(extra or "")).strip(),
        "keyword": keyword,
        "foundAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def clean_image(image: str) -> str:
    value = str(image or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    if not value.startswith("http") or value.startswith("data:"):
        return ""
    return value


def format_money(amount: float | None, currency: str = "BRL") -> str:
    if amount is None:
        return "—"
    symbols = {"BRL": "R$", "USD": "US$", "EUR": "€"}
    symbol = symbols.get(currency, currency)
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{symbol} {text}"


def filter_by_price(offers: list[dict], market: dict) -> list[dict]:
    minimum = as_float(market.get("minPrice")) or 0
    maximum = as_float(market.get("maxPrice")) or 0
    if minimum <= 0 and maximum <= 0:
        return offers
    kept = []
    for offer in offers:
        price = offer.get("price")
        if price is None:
            continue
        if minimum > 0 and price < minimum:
            continue
        if maximum > 0 and price > maximum:
            continue
        kept.append(offer)
    return kept


def discount_pct(price: float | None, original: float | None) -> int:
    if price is None or original is None or original <= 0 or price >= original:
        return 0
    return int(round((original - price) / original * 100))


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def money_div(value, divisor: int) -> float | None:
    number = as_float(value)
    if number is None:
        return None
    return round(number / divisor, 2)


def parse_percent(value) -> int:
    if value is None:
        return 0
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return 0
    return int(round(float(match.group(0).replace(",", "."))))


def find_products(payload: dict) -> list:
    products = payload.get("products")
    if isinstance(products, dict) and isinstance(products.get("product"), list):
        return products["product"]
    result = payload.get("result") or payload.get("resp_result") or {}
    if isinstance(result, dict):
        nested = result.get("products") or {}
        if isinstance(nested, dict) and isinstance(nested.get("product"), list):
            return nested["product"]
        if isinstance(nested, list):
            return nested
    response = payload.get("aliexpress_affiliate_product_query_response")
    if isinstance(response, dict):
        return find_products(response)
    return []
