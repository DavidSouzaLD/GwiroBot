"""Agenda a busca e o envio sem repetir a mesma oferta."""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta, timezone

from app.channels import STORE_LINES, ChannelError, deliver, render
from app.sources import (
    LABELS,
    SourceError,
    affiliate_ml,
    as_float,
    clean_image,
    collect,
    collect_ml,
    make_offer,
)
from app.store import Store

class Engine:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.running = False
        self.busy = False
        self.busy_shop = ""
        self.started_at: str | None = None
        self.last_cycle_at: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="gwiro-scheduler", daemon=True)
        self._thread.start()
        for shop in store.shops():
            if shop.get("enabled") and shop.get("bot", {}).get("autostart"):
                self._arm(shop["id"])

    def _arm(self, shop_id: str) -> None:
        shop = self.store.find_shop(shop_id)
        if shop is None:
            return
        nxt = self.store.shop_state(shop_id).setdefault("nextRun", {})
        for name in shop["marketplaces"]:
            nxt[name] = 0
        self.store.save_state()

    def set_group_enabled(self, shop_id: str, enabled: bool) -> dict:
        shop = self.store.find_shop(shop_id)
        if shop is None:
            raise KeyError(shop_id)
        public = self.store.set_enabled(shop_id, enabled)
        shop = self.store.find_shop(shop_id)
        if enabled and shop and shop.get("bot", {}).get("runOnStart", True):
            self._arm(shop_id)
        self.log("info", "Grupo ativado." if enabled else "Grupo pausado.", shop)
        return public

    def start(self) -> None:
        shop_id = self.store.active_id()
        self.set_group_enabled(shop_id, True)

    def stop(self) -> None:
        shop_id = self.store.active_id()
        self.set_group_enabled(shop_id, False)

    def shutdown(self) -> None:
        self._stop.set()

    def status(self, shop_id: str | None = None) -> dict:
        with self.store._lock:
            config = copy.deepcopy(self.store.config)
            state = copy.deepcopy(self.store.state)
        shop = next((item for item in config["shops"] if item["id"] == (shop_id or config.get("activeShop"))), config["shops"][0])
        slot = (state.get("shops") or {}).get(shop["id"]) or {}
        markets = {}
        for name in shop["marketplaces"]:
            info = (slot.get("marketplaces") or {}).get(name, {})
            nxt = (slot.get("nextRun") or {}).get(name)
            markets[name] = {
                "label": LABELS[name],
                "enabled": shop["marketplaces"][name].get("enabled"),
                "lastRun": info.get("lastRun"),
                "lastFound": info.get("lastFound", 0),
                "lastError": info.get("lastError", ""),
                "nextRun": datetime.fromtimestamp(nxt, timezone.utc).isoformat(timespec="seconds") if nxt else None,
            }
        return {
            "running": bool(shop.get("enabled")),
            "busy": self.busy_shop == shop["id"],
            "startedAt": self.started_at,
            "lastCycleAt": self.last_cycle_at,
            "shopId": shop["id"],
            "shopName": shop.get("name") or "Grupo",
            "shops": [
                {
                    "id": item["id"],
                    "name": item.get("name") or "Grupo",
                    "enabled": bool(item.get("enabled")),
                    "busy": self.busy_shop == item["id"],
                }
                for item in config["shops"]
            ],
            "totals": slot.get("totals") or {},
            "marketplaces": markets,
            "channels": shop["channels"].get("mode"),
            "niches": [
                {
                    "name": niche.get("name") or "Nicho",
                    "enabled": bool(niche.get("enabled")),
                    "stores": niche.get("stores") or [],
                }
                for niche in shop.get("niches") or []
            ],
        }

    def cycle(self, plan: list | None = None, send: bool = True, shop_id: str | None = None, names: list[str] | None = None) -> dict:
        with self._lock:
            if self.busy:
                return {"ok": False, "detail": "Já existe um ciclo em andamento."}
            self.busy = True
        try:
            return self._cycle(plan, send, shop_id, names)
        finally:
            self.busy = False

    def test(self, channel: str | None = None, shop_id: str | None = None) -> dict:
        config = self.store.snapshot_shop(shop_id)
        if config is None:
            return {"ok": False, "detail": "Grupo não encontrado."}
        if channel in {"telegram", "whatsapp", "both", "none"}:
            config["channels"]["mode"] = channel
        sample = {
            "title": "Oferta de teste do Gwiro",
            "priceLabel": "R$ 79,90",
            "originalLabel": "R$ 149,90",
            "discount": 47,
            "storeLabel": "Gwiro",
            "url": "https://example.com/oferta-teste",
            "store": "mercadolivre",
            "keyword": "teste",
            "niche": "Eletrônicos",
            "extra": "⭐️ 4.8 · +50mil vendidos · 💠 preço no Pix",
        }
        try:
            results = deliver(config, sample, config["timing"]["requestTimeoutSec"])
        except ChannelError as error:
            self.log("error", str(error))
            return {"ok": False, "detail": str(error)}
        failed = [item for item in results if not item["ok"]]
        for item in results:
            level = "info" if item["ok"] else "error"
            self.log(level, f"Teste {item['channel']}: {item['detail']}", config)
        return {
            "ok": not failed,
            "results": results,
            "preview": render(config["message"].get("template") or "", sample),
        }

    def publish_manual(self, payload: dict, send: bool, shop_id: str | None = None) -> dict:
        config = self.store.snapshot_shop(shop_id or str(payload.get("shopId") or "") or None)
        if config is None:
            return {"ok": False, "detail": "Grupo não encontrado."}
        try:
            offer = build_manual_offer(payload, config)
        except ValueError as error:
            return {"ok": False, "detail": str(error)}
        offer["shopId"] = config["id"]
        offer["shopName"] = config.get("name") or "Grupo"
        preview = render(config["message"].get("template") or "", offer)
        if not send:
            self._store_offer(offer, "pronta", "Oferta manual guardada.")
            self.log("info", f"Oferta manual guardada: {offer['title']}", config)
            return {"ok": True, "detail": "Oferta guardada na lista.", "preview": preview, "id": offer["id"]}
        outcome = self._send_one(config, offer, mark=True)
        if outcome["ok"]:
            totals = self.store.shop_state(config["id"]).setdefault("totals", {"cycles": 0, "found": 0, "sent": 0})
            totals["sent"] = int(totals.get("sent", 0)) + 1
            self.store.save_state()
            self.log("info", f"Oferta manual enviada: {offer['title']}", config)
        return {**outcome, "preview": preview, "id": offer["id"]}

    def resend(self, offer_id: str, shop_id: str | None = None) -> dict:
        offer = None
        for item in reversed(self.store.offers):
            if item.get("id") != offer_id:
                continue
            if shop_id and (item.get("shopId") or "principal") != shop_id:
                continue
            offer = item
            break
        if not offer:
            return {"ok": False, "detail": "Oferta não encontrada."}
        config = self.store.snapshot_shop(offer.get("shopId") or shop_id)
        if config is None:
            return {"ok": False, "detail": "Grupo não encontrado."}
        return self._send_one(config, offer, mark=False)

    def log(self, level: str, message: str, shop: dict | None = None) -> None:
        if shop is not None:
            message = f"{shop.get('name') or 'Grupo'}: {message}"
        self.store.logs.append({"at": iso_now(), "level": level, "message": message, "shopId": (shop or {}).get("id", "")})
        self.store.save_logs()

    def _loop(self) -> None:
        while not self._stop.is_set():
            due = self._due_markets()
            if due:
                self.cycle(plan=due, send=True)
            self._stop.wait(2)

    def _due_markets(self) -> list[tuple[str, str]]:
        now = time.time()
        due = []
        for shop in self.store.shops():
            if not shop.get("enabled") or self.quiet_now(shop):
                continue
            nxt = self.store.shop_state(shop["id"]).setdefault("nextRun", {})
            for name, market in shop["marketplaces"].items():
                if not market.get("enabled"):
                    continue
                if now >= float(nxt.get(name) or 0):
                    due.append((shop["id"], name))
        return due

    def _cycle(self, plan: list | None, send: bool, shop_id: str | None, names: list[str] | None) -> dict:
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        if plan:
            for item in plan:
                if isinstance(item, str):
                    sid, name = shop_id or self.store.active_id(), item
                else:
                    sid, name = item
                if sid not in grouped:
                    order.append(sid)
                    grouped[sid] = []
                if name not in grouped[sid]:
                    grouped[sid].append(name)
        else:
            shop = self.store.find_shop(shop_id)
            if shop is None:
                return {"ok": False, "detail": "Grupo não encontrado."}
            chosen = names or [name for name, market in shop["marketplaces"].items() if market.get("enabled")]
            order = [shop["id"]]
            grouped[shop["id"]] = chosen
        summaries = []
        for sid in order:
            summaries.append(self._cycle_shop(sid, grouped[sid], send))
        if not summaries:
            return {"ok": False, "detail": "Nenhum grupo para buscar."}
        return {
            "ok": all(item.get("ok", True) for item in summaries),
            "found": sum(item.get("found", 0) for item in summaries),
            "queued": sum(item.get("queued", 0) for item in summaries),
            "sent": sum(item.get("sent", 0) for item in summaries),
            "skipped": sum(item.get("skipped", 0) for item in summaries),
            "errors": [error for item in summaries for error in item.get("errors", [])],
            "sendErrors": [error for item in summaries for error in item.get("sendErrors", [])],
        }

    def _cycle_shop(self, shop_id: str, names: list[str], send: bool) -> dict:
        config = self.store.snapshot_shop(shop_id)
        if config is None:
            return {"ok": False, "detail": "Grupo não encontrado.", "found": 0, "queued": 0, "sent": 0, "skipped": 0, "errors": [], "sendErrors": []}
        if not config.get("enabled"):
            return {"ok": True, "found": 0, "queued": 0, "sent": 0, "skipped": 0, "errors": [], "sendErrors": []}
        self.busy_shop = config["id"]
        timeout = config["timing"]["requestTimeoutSec"]
        per_market = config["timing"]["maxPerMarketplace"]
        found: list[dict] = []
        errors = []
        now = time.time()

        for name in names:
            market = config["marketplaces"].get(name)
            if not market:
                continue
            self.store.shop_state(config["id"]).setdefault("nextRun", {})[name] = now + int(market.get("intervalSec") or 300)
            plans = search_plans(name, market, config)
            batch = []
            warnings = []
            plan_errors = []
            if name == "mercadolivre":
                try:
                    batch = collect_ml(plans, per_market, timeout)
                except SourceError as error:
                    plan_errors.append(str(error))
            else:
                for plan in plans:
                    try:
                        part, part_warnings = collect(name, plan, timeout)
                    except SourceError as error:
                        plan_errors.append(str(error))
                        continue
                    batch.extend(part)
                    warnings.extend(part_warnings)
            label = LABELS[name]
            slot = self.store.shop_state(config["id"]).setdefault("marketplaces", {}).setdefault(name, {})
            slot["lastRun"] = iso_now()
            if plan_errors and not batch:
                detail = plan_errors[-1]
                slot["lastFound"] = 0
                slot["lastError"] = detail
                errors.append({"store": name, "detail": detail})
                self.log("error", f"{label}: {detail}", config)
                continue
            batch = dedupe_offers(batch)[:per_market]
            for warning in warnings + plan_errors:
                self.log("error", f"{label}: {warning}", config)
            slot["lastFound"] = len(batch)
            slot["lastError"] = plan_errors[-1] if plan_errors else ""
            for offer in batch:
                offer["shopId"] = config["id"]
                offer["shopName"] = config.get("name") or "Grupo"
            found.extend(batch)
            niche_names = [plan.get("nicheName") for plan in plans if plan.get("nicheName")]
            scope = f" · nichos: {', '.join(niche_names)}" if niche_names else ""
            self.log("info", f"{label}: {len(batch)} oferta(s) dentro do filtro.{scope}", config)

        fresh = []
        skipped = 0
        for offer in found:
            if self._recent(config["id"], offer["id"], config["timing"]["dedupHours"]):
                skipped += 1
                continue
            fresh.append(offer)
        limit = config["timing"]["maxOffersPerCycle"]
        queued = fresh[:limit]
        overflow = fresh[limit:]

        sent = 0
        send_errors = []
        if send and not self.quiet_now(config):
            for index, offer in enumerate(queued):
                outcome = self._send_one(config, offer, mark=True)
                if outcome["ok"]:
                    sent += 1
                else:
                    send_errors.append(outcome["detail"])
                if index < len(queued) - 1:
                    time.sleep(config["timing"]["delayBetweenMessagesMs"] / 1000)
        else:
            if send:
                self.log("info", "Horário silencioso. As ofertas foram guardadas e não foram enviadas.", config)
            for offer in queued:
                self._store_offer(offer, "coletada", "Aguardando envio.")

        self._remember(config["id"], queued if send else [], overflow)
        totals = self.store.shop_state(config["id"]).setdefault("totals", {"cycles": 0, "found": 0, "sent": 0})
        totals["cycles"] = int(totals.get("cycles", 0)) + 1
        totals["found"] = int(totals.get("found", 0)) + len(found)
        totals["sent"] = int(totals.get("sent", 0)) + sent
        self.last_cycle_at = iso_now()
        self.store.save_state()
        summary = {
            "ok": True,
            "found": len(found),
            "queued": len(queued),
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
            "sendErrors": send_errors,
        }
        self.log(
            "info",
            f"Ciclo: {summary['found']} encontradas, {summary['sent']} enviadas, {summary['skipped']} repetidas.",
            config,
        )
        if self.busy_shop == config["id"]:
            self.busy_shop = ""
        return summary

    def _send_one(self, config: dict, offer: dict, mark: bool) -> dict:
        try:
            results = deliver(config, offer, config["timing"]["requestTimeoutSec"])
        except ChannelError as error:
            self.log("error", str(error))
            self._store_offer(offer, "erro", str(error))
            return {"ok": False, "detail": str(error)}
        failed = [item["detail"] for item in results if not item["ok"]]
        ok = [item for item in results if item["ok"]]
        offer["shopId"] = config["id"]
        offer["shopName"] = config.get("name") or "Grupo"
        if ok and mark:
            self.store.shop_state(config["id"]).setdefault("sent", {})[offer["id"]] = time.time()
        status = "enviada" if ok and not failed else ("parcial" if ok else "erro")
        detail = " · ".join(item["detail"] for item in results)
        self._store_offer(offer, status, detail)
        if failed and not ok:
            return {"ok": False, "detail": detail}
        return {"ok": True, "detail": detail, "results": results}

    def _store_offer(self, offer: dict, status: str, detail: str) -> None:
        record = dict(offer)
        record["status"] = status
        record["detail"] = detail
        record["sentAt"] = iso_now()
        key = f"{record.get('shopId') or 'principal'}:{record.get('id')}"
        self.store.offers = [
            item
            for item in self.store.offers
            if f"{item.get('shopId') or 'principal'}:{item.get('id')}" != key
        ]
        self.store.offers.append(record)
        self.store.save_offers()

    def _remember(self, shop_id: str, sent: list[dict], held: list[dict]) -> None:
        for offer in held:
            key = f"{shop_id}:{offer.get('id')}"
            if not any(f"{item.get('shopId') or 'principal'}:{item.get('id')}" == key for item in self.store.offers):
                self._store_offer(offer, "na fila", "Acima do limite deste ciclo.")
        if sent:
            self.store.save_state()

    def _recent(self, shop_id: str, offer_id: str, hours: int) -> bool:
        sent = self.store.shop_state(shop_id).setdefault("sent", {})
        cutoff = time.time() - hours * 3600
        stale = [key for key, stamp in sent.items() if float(stamp) < cutoff]
        for key in stale:
            sent.pop(key, None)
        stamp = sent.get(offer_id)
        return stamp is not None and float(stamp) >= cutoff

    def quiet_now(self, shop: dict) -> bool:
        timing = shop["timing"]
        if not timing.get("quietHoursEnabled"):
            return False
        current = datetime.now().strftime("%H:%M")
        start = timing.get("quietStart") or "23:00"
        end = timing.get("quietEnd") or "08:00"
        if start <= end:
            return start <= current < end
        return current >= start or current < end


def build_manual_offer(payload: dict, config: dict) -> dict:
    store = str(payload.get("store") or "").strip()
    if store not in LABELS:
        raise ValueError("Escolha a vitrine.")
    title = " ".join(str(payload.get("title") or "").split())
    if not title:
        raise ValueError("Informe o título.")
    price = as_float(payload.get("price"))
    if price is None or price <= 0:
        raise ValueError("Informe o preço atual.")
    original = as_float(payload.get("original"))
    if original is not None and original <= 0:
        original = None
    given_discount = parse_discount(payload.get("discount"))
    if original is None and given_discount and 0 < given_discount < 100:
        original = round(price / (1 - given_discount / 100), 2)
    url = str(payload.get("url") or "").strip()
    if not url.startswith("http"):
        raise ValueError("Informe o link da oferta, começando com http.")
    if store == "mercadolivre" and "meli.la" not in url and "matt_tool=" not in url:
        url = affiliate_ml(url, config["marketplaces"]["mercadolivre"])
    extra = manual_extra(payload)
    offer = make_offer(
        store,
        url,
        title,
        price,
        original,
        "BRL",
        url,
        clean_image(str(payload.get("image") or "")),
        "manual",
        extra=extra,
    )
    if given_discount is not None:
        offer["discount"] = given_discount
    niche = " ".join(str(payload.get("niche") or "").split())[:40]
    if niche:
        offer["niche"] = niche
    offer["manual"] = True
    offer["storeLine"] = STORE_LINES.get(store, offer["storeLabel"])
    return offer


def parse_discount(value) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("%", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        raise ValueError("Desconto inválido.")
    return max(0, min(95, int(round(number))))


def manual_extra(payload: dict) -> str:
    parts = []
    rating = " ".join(str(payload.get("rating") or "").split())
    if rating.startswith("⭐️"):
        rating = rating.removeprefix("⭐️").strip()
    if rating:
        parts.append("⭐️ " + rating[:80])
    if payload.get("pix"):
        parts.append("💠 preço no Pix")
    if payload.get("shipping"):
        parts.append("🚚 Frete grátis")
    note = " ".join(str(payload.get("note") or "").split())
    if note:
        parts.append(note[:180])
    return " · ".join(parts)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def search_plans(name: str, market: dict, config: dict) -> list[dict]:
    plans = []
    for niche in config.get("niches") or []:
        if not niche.get("enabled"):
            continue
        if name not in (niche.get("stores") or []):
            continue
        if not str(niche.get("keywords") or "").strip():
            continue
        scoped = copy.deepcopy(market)
        scoped["keywords"] = niche.get("keywords") or ""
        scoped["minDiscount"] = niche.get("minDiscount") or 0
        scoped["minPrice"] = niche.get("minPrice") or 0
        scoped["maxPrice"] = niche.get("maxPrice") or 0
        scoped["nicheName"] = niche.get("name") or "Nicho"
        plans.append(scoped)
    return plans or [market]


def dedupe_offers(offers: list[dict]) -> list[dict]:
    unique = []
    seen = set()
    for offer in sorted(offers, key=lambda item: item.get("discount") or 0, reverse=True):
        if offer.get("id") in seen:
            continue
        seen.add(offer["id"])
        unique.append(offer)
    return unique
