"""Persistência local da configuração, do estado e do histórico."""

from __future__ import annotations

import copy
import json
import random
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PUBLIC = ROOT / "public"

SHOP_SECRET_PATHS = (
    ("channels", "telegram", "botToken"),
    ("channels", "whatsapp", "accessToken"),
    ("marketplaces", "amazon", "secretKey"),
    ("marketplaces", "shopee", "secret"),
    ("marketplaces", "aliexpress", "appSecret"),
)
DASHBOARD_SECRET = ("token",)

CLEAR = "__clear__"
MAX_SHOPS = 20


def shop_body() -> dict:
    return {
        "description": "",
        "bot": {
            "autostart": False,
            "runOnStart": True,
        },
        "timing": {
            "delayBetweenMessagesMs": 2500,
            "maxOffersPerCycle": 5,
            "maxPerMarketplace": 3,
            "dedupHours": 48,
            "quietHoursEnabled": False,
            "quietStart": "23:00",
            "quietEnd": "08:00",
            "requestTimeoutSec": 20,
        },
        "message": {
            "template": (
                "🔥 {title}\n\n"
                "❌ De: {original}\n"
                "✅ Por: {price}  🔻 -{discount}%\n"
                "{extra}\n\n"
                "{storeLine}"
            )
        },
        "niches": [
            {
                "id": "eletronicos",
                "name": "Eletrônicos",
                "enabled": True,
                "keywords": "fone bluetooth\nsmartwatch\ncarregador turbo",
                "minDiscount": 15,
                "minPrice": 0,
                "maxPrice": 0,
                "stores": ["mercadolivre", "amazon", "shopee", "aliexpress"],
            },
            {
                "id": "casa",
                "name": "Casa e cozinha",
                "enabled": True,
                "keywords": "air fryer\nliquidificador\norganizador",
                "minDiscount": 20,
                "minPrice": 0,
                "maxPrice": 0,
                "stores": ["mercadolivre", "amazon", "shopee", "aliexpress"],
            },
            {
                "id": "beleza",
                "name": "Beleza",
                "enabled": False,
                "keywords": "perfume\nsecador de cabelo",
                "minDiscount": 15,
                "minPrice": 0,
                "maxPrice": 0,
                "stores": ["mercadolivre", "amazon", "shopee", "aliexpress"],
            },
        ],
        "channels": {
            "mode": "telegram",
            "telegram": {
                "botToken": "",
                "chatId": "",
            },
            "whatsapp": {
                "accessToken": "",
                "phoneNumberId": "",
                "recipient": "",
                "apiVersion": "v21.0",
                "delivery": "text",
                "templateName": "",
                "templateLanguage": "pt_BR",
            },
        },
        "marketplaces": {
            "mercadolivre": {
                "enabled": True,
                "intervalSec": 300,
                "site": "MLB",
                "keywords": "fone bluetooth\nair fryer\nsmartwatch",
                "minDiscount": 15,
                "limit": 8,
                "sort": "relevance",
                "mattTool": "",
                "mattWord": "gwiro",
            },
            "amazon": {
                "enabled": False,
                "intervalSec": 600,
                "accessKey": "",
                "secretKey": "",
                "partnerTag": "",
                "host": "webservices.amazon.com.br",
                "region": "us-east-1",
                "marketplace": "www.amazon.com.br",
                "keywords": "oferta do dia",
                "minDiscount": 10,
                "limit": 5,
            },
            "shopee": {
                "enabled": False,
                "intervalSec": 600,
                "appId": "",
                "secret": "",
                "keywords": "fone bluetooth",
                "minDiscount": 15,
                "limit": 8,
                "priceDivisor": 1,
            },
            "aliexpress": {
                "enabled": False,
                "intervalSec": 600,
                "appKey": "",
                "appSecret": "",
                "trackingId": "",
                "keywords": "fone bluetooth",
                "minDiscount": 20,
                "limit": 8,
                "sort": "LAST_VOLUME_DESC",
                "currency": "BRL",
                "language": "PT",
                "shipTo": "BR",
            },
        },
    }


def new_shop(name: str = "Novo grupo", shop_id: str = "principal", enabled: bool = True) -> dict:
    shop = shop_body()
    shop["id"] = shop_id
    shop["name"] = name
    shop["enabled"] = enabled
    return shop


def defaults() -> dict:
    return {
        "dashboard": {"token": "", "showHints": True},
        "activeShop": "principal",
        "shops": [new_shop()],
    }


def fresh_state() -> dict:
    return {"shops": {}}


def blank_shop_state() -> dict:
    return {
        "nextRun": {},
        "sent": {},
        "totals": {"cycles": 0, "found": 0, "sent": 0},
        "marketplaces": {},
    }


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        DATA.mkdir(exist_ok=True)
        self.config = self._load_config()
        self.state = self._load_state()
        self._write("state.json", self.state)
        self.offers: list[dict] = self._load_list("offers.json")
        self.logs: list[dict] = self._load_list("logs.json")

    def _path(self, name: str) -> Path:
        return DATA / name

    def _read_json(self, name: str):
        path = self._path(name)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None

    def _load_config(self) -> dict:
        raw = self._read_json("config.json")
        if not isinstance(raw, dict):
            config = defaults()
        else:
            config = prepare_config(raw)
        self._write("config.json", config)
        return config

    def _load_state(self) -> dict:
        raw = self._read_json("state.json")
        if not isinstance(raw, dict):
            return fresh_state()
        return migrate_state(raw)

    def _load_list(self, name: str) -> list:
        raw = self._read_json(name)
        return raw if isinstance(raw, list) else []

    def _write(self, name: str, payload) -> None:
        path = self._path(name)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary.replace(path)

    def save_config(self) -> None:
        with self._lock:
            self._write("config.json", self.config)

    def save_state(self) -> None:
        with self._lock:
            self._write("state.json", self.state)

    def save_offers(self) -> None:
        with self._lock:
            self._write("offers.json", self.offers[-300:])
            self.offers = self.offers[-300:]

    def save_logs(self) -> None:
        with self._lock:
            self._write("logs.json", self.logs[-400:])
            self.logs = self.logs[-400:]

    def shops(self) -> list[dict]:
        return self.config["shops"]

    def active_id(self) -> str:
        return self.config.get("activeShop") or self.config["shops"][0]["id"]

    def find_shop(self, shop_id: str | None) -> dict | None:
        wanted = shop_id or self.active_id()
        for shop in self.config["shops"]:
            if shop["id"] == wanted:
                return shop
        if shop_id:
            return None
        return self.config["shops"][0] if self.config["shops"] else None

    def snapshot_shop(self, shop_id: str | None = None) -> dict | None:
        with self._lock:
            shop = self.find_shop(shop_id)
            return copy.deepcopy(shop) if shop else None

    def shop_state(self, shop_id: str) -> dict:
        shops = self.state.setdefault("shops", {})
        slot = shops.get(shop_id)
        if not isinstance(slot, dict):
            slot = blank_shop_state()
            shops[shop_id] = slot
        slot.setdefault("nextRun", {})
        slot.setdefault("sent", {})
        slot.setdefault("totals", {"cycles": 0, "found": 0, "sent": 0})
        slot.setdefault("marketplaces", {})
        return slot

    def save_panel(self, shop_id: str, incoming: dict, dashboard: dict | None, roster) -> dict:
        with self._lock:
            current = self.find_shop(shop_id)
            if current is None:
                raise KeyError(shop_id)
            merged = deep_merge(shop_body(), incoming if isinstance(incoming, dict) else {})
            merged["id"] = current["id"]
            merged["name"] = current["name"]
            merged["enabled"] = current["enabled"]
            restore_shop_secrets(current, merged)
            merged = sanitize_shop(merged)
            index = self.config["shops"].index(current)
            self.config["shops"][index] = merged
            self._apply_roster(roster)
            if isinstance(dashboard, dict):
                self._apply_dashboard(dashboard)
            self.config = prepare_config(self.config)
            self._write("config.json", self.config)
            return public_config(self.config)

    def reset_shop(self, shop_id: str, section: str) -> dict:
        with self._lock:
            current = self.find_shop(shop_id)
            if current is None:
                raise KeyError(shop_id)
            section = str(section or "all")
            fresh = shop_body()
            if section == "all":
                shop = sanitize_shop(copy.deepcopy(fresh))
                shop["id"] = current["id"]
                shop["name"] = current["name"]
                shop["enabled"] = current["enabled"]
                shop["description"] = ""
            elif section == "timing":
                current["timing"] = copy.deepcopy(fresh["timing"])
                current["bot"] = copy.deepcopy(fresh["bot"])
                for name, market in fresh["marketplaces"].items():
                    if name in current["marketplaces"]:
                        current["marketplaces"][name]["intervalSec"] = market["intervalSec"]
                shop = sanitize_shop(current)
            elif section in {"niches", "marketplaces", "channels", "message"}:
                current[section] = copy.deepcopy(fresh[section])
                shop = sanitize_shop(current)
            else:
                raise ValueError("Não há padrão para restaurar aqui.")
            index = self.config["shops"].index(current)
            self.config["shops"][index] = shop
            self._write("config.json", self.config)
            return public_config(self.config)

    def set_enabled(self, shop_id: str, enabled: bool) -> dict:
        with self._lock:
            shop = self.find_shop(shop_id)
            if shop is None:
                raise KeyError(shop_id)
            shop["enabled"] = bool(enabled)
            self._write("config.json", self.config)
            return public_config(self.config)

    def mutate_shop(self, action: str, payload: dict) -> dict:
        with self._lock:
            action = str(action or "")
            if action == "create":
                self._create(str(payload.get("name") or "Novo grupo"))
            elif action == "duplicate":
                self._duplicate(str(payload.get("id") or ""))
            elif action == "delete":
                self._delete(str(payload.get("id") or ""))
            elif action == "select":
                shop = self.find_shop(str(payload.get("id") or ""))
                if shop is None:
                    raise KeyError("missing")
                self.config["activeShop"] = shop["id"]
            else:
                raise ValueError("Ação inválida.")
            self.config = prepare_config(self.config)
            self._write("config.json", self.config)
            return public_config(self.config)

    def _create(self, name: str) -> None:
        if len(self.config["shops"]) >= MAX_SHOPS:
            raise ValueError(f"O limite é de {MAX_SHOPS} grupos.")
        shop = new_shop(clean_name(name, "Novo grupo"), unique_id(self._ids()), True)
        shop["niches"] = [
            {
                "id": "geral",
                "name": shop["name"],
                "enabled": True,
                "keywords": "",
                "minDiscount": 15,
                "minPrice": 0,
                "maxPrice": 0,
                "stores": list(STORE_IDS),
            }
        ]
        for market in shop["marketplaces"].values():
            market["enabled"] = False
            market["keywords"] = ""
        self.config["shops"].append(sanitize_shop(shop))
        self.config["activeShop"] = shop["id"]

    def _duplicate(self, shop_id: str) -> None:
        if len(self.config["shops"]) >= MAX_SHOPS:
            raise ValueError(f"O limite é de {MAX_SHOPS} grupos.")
        source = self.find_shop(shop_id)
        if source is None:
            raise KeyError(shop_id)
        shop = copy.deepcopy(source)
        shop["id"] = unique_id(self._ids())
        shop["name"] = clean_name(f"Cópia de {source.get('name') or 'grupo'}", "Cópia")
        shop["enabled"] = False
        self.config["shops"].append(sanitize_shop(shop))
        self.config["activeShop"] = shop["id"]

    def _delete(self, shop_id: str) -> None:
        if len(self.config["shops"]) <= 1:
            raise ValueError("O último grupo não pode ser removido.")
        kept = [shop for shop in self.config["shops"] if shop["id"] != shop_id]
        if len(kept) == len(self.config["shops"]):
            raise KeyError(shop_id)
        self.config["shops"] = kept
        self.state.setdefault("shops", {}).pop(shop_id, None)
        if self.config.get("activeShop") == shop_id:
            self.config["activeShop"] = kept[0]["id"]

    def _ids(self) -> set[str]:
        return {shop["id"] for shop in self.config["shops"]}

    def _apply_roster(self, roster) -> None:
        if not isinstance(roster, list):
            return
        by_id = {shop["id"]: shop for shop in self.config["shops"]}
        for item in roster:
            if not isinstance(item, dict):
                continue
            shop = by_id.get(str(item.get("id") or ""))
            if shop is None:
                continue
            shop["name"] = clean_name(item.get("name"), shop["name"])
            shop["enabled"] = bool(item.get("enabled"))
            if "description" in item:
                shop["description"] = clean_description(item.get("description"))

    def _apply_dashboard(self, incoming: dict) -> None:
        previous = self.config.setdefault("dashboard", {"token": "", "showHints": True})
        token = incoming.get("token", "")
        if token == CLEAR:
            previous["token"] = ""
        elif isinstance(token, str) and token.strip() and not token.startswith("•"):
            previous["token"] = token.strip()
        if "showHints" in incoming:
            previous["showHints"] = bool(incoming.get("showHints"))

    def public(self) -> dict:
        with self._lock:
            return public_config(self.config)


def prepare_config(raw: dict) -> dict:
    migrated = migrate_config(raw)
    dashboard = deep_merge({"token": "", "showHints": True}, migrated.get("dashboard") or {})
    shops = []
    seen = set()
    for item in migrated.get("shops") or []:
        if not isinstance(item, dict):
            continue
        shop = deep_merge(shop_body(), item)
        shop["id"] = clean_id(item.get("id"), "")
        if not shop["id"] or shop["id"] in seen:
            shop["id"] = unique_id(seen)
        seen.add(shop["id"])
        shop["name"] = clean_name(item.get("name"), "Grupo")
        shop["enabled"] = bool(item.get("enabled", True))
        shop["description"] = clean_description(item.get("description"))
        shops.append(sanitize_shop(shop))
    if not shops:
        shops = [sanitize_shop(new_shop())]
    active = str(migrated.get("activeShop") or "")
    if active not in {shop["id"] for shop in shops}:
        active = shops[0]["id"]
    return {
        "dashboard": {
            "token": str(dashboard.get("token") or ""),
            "showHints": bool(dashboard.get("showHints", True)),
        },
        "activeShop": active,
        "shops": shops[:MAX_SHOPS],
    }


def migrate_config(raw: dict) -> dict:
    if isinstance(raw.get("shops"), list):
        return raw
    shop = shop_body()
    for key in shop:
        if key in raw:
            shop[key] = raw[key]
    shop["id"] = "principal"
    shop["name"] = "Grupo principal"
    shop["enabled"] = True
    return {
        "dashboard": raw.get("dashboard") if isinstance(raw.get("dashboard"), dict) else {"token": "", "showHints": True},
        "activeShop": "principal",
        "shops": [shop],
    }


def migrate_state(raw: dict) -> dict:
    shops = raw.get("shops")
    if isinstance(shops, dict):
        return {"shops": shops}
    legacy = {
        "nextRun": raw.get("nextRun") if isinstance(raw.get("nextRun"), dict) else {},
        "sent": raw.get("sent") if isinstance(raw.get("sent"), dict) else {},
        "totals": raw.get("totals") if isinstance(raw.get("totals"), dict) else {"cycles": 0, "found": 0, "sent": 0},
        "marketplaces": raw.get("marketplaces") if isinstance(raw.get("marketplaces"), dict) else {},
    }
    return {"shops": {"principal": legacy}}


def deep_merge(base: dict, override: dict, *, root: bool = True) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if root and key in ("id", "name", "enabled"):
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value, root=False)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _get(data: dict, path: tuple):
    cursor = data
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return ""
        cursor = cursor[key]
    return cursor


def _set(data: dict, path: tuple, value) -> None:
    cursor = data
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def restore_shop_secrets(previous: dict, incoming: dict) -> dict:
    for path in SHOP_SECRET_PATHS:
        value = _get(incoming, path)
        if value == CLEAR:
            _set(incoming, path, "")
        elif not isinstance(value, str) or value.strip() == "" or value.startswith("•"):
            _set(incoming, path, _get(previous, path) or "")
    return incoming


def public_config(config: dict) -> dict:
    dashboard = {
        "showHints": bool(config["dashboard"].get("showHints", True)),
        "token": "",
    }
    token = str(config["dashboard"].get("token") or "")
    dashboard_hints = {}
    if token:
        dashboard_hints["dashboard.token"] = token[-4:]
    shops = []
    hints = {}
    for shop in config["shops"]:
        visible, shop_hints = public_shop(shop)
        shops.append(visible)
        hints[shop["id"]] = shop_hints
    return {
        "activeShop": config.get("activeShop") or shops[0]["id"],
        "dashboard": dashboard,
        "dashboardHints": dashboard_hints,
        "shops": shops,
        "hints": hints,
    }


def public_shop(shop: dict) -> tuple[dict, dict]:
    visible = copy.deepcopy(shop)
    hints = {}
    for path in SHOP_SECRET_PATHS:
        value = _get(visible, path)
        dotted = ".".join(path)
        if isinstance(value, str) and value:
            hints[dotted] = value[-4:]
        _set(visible, path, "")
    return visible, hints


def sanitize_shop(shop: dict) -> dict:
    timing = shop["timing"]
    timing["delayBetweenMessagesMs"] = clamp_int(timing.get("delayBetweenMessagesMs"), 0, 60000, 2500)
    timing["maxOffersPerCycle"] = clamp_int(timing.get("maxOffersPerCycle"), 1, 30, 5)
    timing["maxPerMarketplace"] = clamp_int(timing.get("maxPerMarketplace"), 1, 20, 3)
    timing["dedupHours"] = clamp_int(timing.get("dedupHours"), 1, 720, 48)
    timing["requestTimeoutSec"] = clamp_int(timing.get("requestTimeoutSec"), 5, 60, 20)
    timing["quietHoursEnabled"] = bool(timing.get("quietHoursEnabled"))
    timing["quietStart"] = clean_clock(timing.get("quietStart"), "23:00")
    timing["quietEnd"] = clean_clock(timing.get("quietEnd"), "08:00")

    mode = shop["channels"].get("mode")
    if mode not in {"telegram", "whatsapp", "both", "none"}:
        shop["channels"]["mode"] = "telegram"
    delivery = shop["channels"]["whatsapp"].get("delivery")
    if delivery not in {"text", "template"}:
        shop["channels"]["whatsapp"]["delivery"] = "text"

    shop["niches"] = sanitize_niches(shop.get("niches"))
    shop["bot"]["autostart"] = bool(shop["bot"].get("autostart"))
    shop["bot"]["runOnStart"] = bool(shop["bot"].get("runOnStart"))
    shop["message"]["template"] = str(shop["message"].get("template") or "")[:4000]

    for name, market in shop["marketplaces"].items():
        market["enabled"] = bool(market.get("enabled"))
        market["intervalSec"] = clamp_int(market.get("intervalSec"), 30, 86400, 300)
        market["minDiscount"] = clamp_int(market.get("minDiscount"), 0, 95, 10)
        market["limit"] = clamp_int(market.get("limit"), 1, 20, 5)
        market["keywords"] = str(market.get("keywords") or "")[:2000]
        if name == "shopee":
            market["priceDivisor"] = clamp_int(market.get("priceDivisor"), 1, 1000000, 1)
    return shop


STORE_IDS = ("mercadolivre", "amazon", "shopee", "aliexpress")


def sanitize_niches(raw) -> list:
    if not isinstance(raw, list):
        return []
    cleaned = []
    seen = set()
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "Nicho").split())[:40] or "Nicho"
        niche_id = "".join(ch for ch in str(item.get("id") or "").lower() if ch.isalnum() or ch == "-")[:40]
        if not niche_id or niche_id in seen:
            niche_id = f"nicho-{len(cleaned) + 1}"
        seen.add(niche_id)
        stores = [store for store in (item.get("stores") or []) if store in STORE_IDS]
        if not stores:
            stores = list(STORE_IDS)
        min_price = clamp_int(item.get("minPrice"), 0, 1_000_000, 0)
        max_price = clamp_int(item.get("maxPrice"), 0, 1_000_000, 0)
        if max_price and min_price and max_price < min_price:
            min_price, max_price = max_price, min_price
        cleaned.append(
            {
                "id": niche_id,
                "name": name,
                "enabled": bool(item.get("enabled")),
                "keywords": str(item.get("keywords") or "")[:2000],
                "minDiscount": clamp_int(item.get("minDiscount"), 0, 95, 0),
                "minPrice": min_price,
                "maxPrice": max_price,
                "stores": stores,
            }
        )
    return cleaned


def clean_description(value) -> str:
    return " ".join(str(value or "").split())[:180]


def clean_name(value, fallback: str) -> str:
    name = " ".join(str(value or "").split())[:40]
    return name or fallback


def clean_id(value, fallback: str) -> str:
    shop_id = "".join(ch for ch in str(value or "").lower() if ch.isalnum() or ch == "-")[:40]
    return shop_id or fallback


def unique_id(taken: set[str]) -> str:
    while True:
        shop_id = "grupo-" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
        if shop_id not in taken:
            taken.add(shop_id)
            return shop_id


def clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def clean_clock(value, fallback: str) -> str:
    text = str(value or "")
    parts = text.split(":")
    if len(parts) != 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return f"{hour:02d}:{minute:02d}"
