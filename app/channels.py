"""Envio das ofertas para Telegram e WhatsApp Cloud API."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

STORE_LINES = {
    "mercadolivre": "💛 Mercado Livre",
    "amazon": "📦 Amazon",
    "shopee": "🧡 Shopee",
    "aliexpress": "🛒 AliExpress",
}


class ChannelError(Exception):
    pass


def render(template: str, offer: dict) -> str:
    values = {
        "title": offer.get("title") or "",
        "price": offer.get("priceLabel") or "—",
        "original": offer.get("originalLabel") or "—",
        "discount": str(offer.get("discount") or 0),
        "store": offer.get("storeLabel") or "",
        "url": offer.get("url") or "",
        "keyword": offer.get("keyword") or "",
        "niche": offer.get("niche") or "",
        "extra": offer.get("extra") or "",
        "storeLine": STORE_LINES.get(offer.get("store") or "", offer.get("storeLabel") or ""),
    }
    text = template or "{title}\n{url}"
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def caption_html(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("🔥 "):
            lines.append("🔥 <b>" + html.escape(line.removeprefix("🔥 ")) + "</b>")
        elif line.startswith("❌ De: "):
            lines.append("❌ De: <s>" + html.escape(line.removeprefix("❌ De: ")) + "</s>")
        elif line.startswith("✅ Por: "):
            body = line.removeprefix("✅ Por: ")
            price, separator, rest = body.partition("  🔻")
            built = "✅ Por: <b>" + html.escape(price) + "</b>"
            if separator:
                built += "  🔻 <b>" + html.escape(rest.strip()) + "</b>"
            lines.append(built)
        else:
            lines.append(html.escape(line))
    return "\n".join(lines)


def selected_channels(config: dict) -> list[str]:
    mode = config["channels"].get("mode") or "none"
    if mode == "both":
        return ["telegram", "whatsapp"]
    if mode in {"telegram", "whatsapp"}:
        return [mode]
    return []


def deliver(config: dict, offer: dict, timeout: int) -> list[dict]:
    text = render(config["message"].get("template") or "", offer)
    results = []
    for name in selected_channels(config):
        try:
            if name == "telegram":
                detail = send_telegram(config["channels"]["telegram"], offer, text, timeout)
            else:
                detail = send_whatsapp(config["channels"]["whatsapp"], offer, text, timeout)
            results.append({"channel": name, "ok": True, "detail": detail})
        except ChannelError as error:
            results.append({"channel": name, "ok": False, "detail": str(error)})
    if not results:
        raise ChannelError("Nenhum canal está selecionado. Escolha Telegram, WhatsApp ou os dois.")
    return results


def telegram_chat_ids(chat_id: str) -> list[str]:
    chat_id = str(chat_id or "").strip()
    options = [chat_id] if chat_id else []
    if re.fullmatch(r"-\d{6,}", chat_id) and not chat_id.startswith("-100"):
        options.append("-100" + chat_id[1:])
    return options


def explain_telegram(detail: str) -> str:
    text = str(detail or "O Telegram recusou a mensagem.")
    low = text.lower()
    if "chat not found" in low or "group chat was upgraded" in low:
        return "Chat não encontrado. O bot precisa estar no grupo, e o chat ID de supergrupo começa com -100."
    if "bot was blocked" in low:
        return "O bot foi bloqueado nesse chat."
    if "not enough rights" in low or "have no rights" in low or "not a member" in low:
        return "O bot não pode publicar nesse chat. Coloque ele no grupo, com permissão de enviar mensagens."
    if "can't parse" in low or "parse entities" in low:
        return "O Telegram não aceitou a formatação da mensagem."
    if "message is too long" in low:
        return "A mensagem passou do limite do Telegram."
    return text


def send_telegram(settings: dict, offer: dict, text: str, timeout: int) -> str:
    token = str(settings.get("botToken") or "").strip()
    chat_ids = telegram_chat_ids(str(settings.get("chatId") or ""))
    if not token or not chat_ids:
        raise ChannelError("Informe o token do bot e o chat ID do Telegram.")
    last = "O Telegram recusou a mensagem."
    for index, chat_id in enumerate(chat_ids):
        try:
            detail = post_telegram(token, chat_id, offer, text, timeout)
        except ChannelError as error:
            last = str(error)
            if index + 1 < len(chat_ids) and "chat not found" in last.lower():
                continue
            raise ChannelError(explain_telegram(last)) from error
        if chat_id != str(settings.get("chatId") or "").strip():
            settings["chatId"] = chat_id
            return detail + " O chat ID foi ajustado para o formato de supergrupo."
        return detail
    raise ChannelError(explain_telegram(last))


def post_telegram(token: str, chat_id: str, offer: dict, text: str, timeout: int) -> str:
    caption = caption_html(text)[:1024]
    payload = {"chat_id": chat_id, "parse_mode": "HTML"}
    button = offer_button(offer.get("url") or "")
    if button["inline_keyboard"]:
        payload["reply_markup"] = json.dumps(button, ensure_ascii=False)
    image = str(offer.get("image") or "")
    if image:
        payload["photo"] = image
        payload["caption"] = caption
        data = post_json(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            urllib.parse.urlencode(payload).encode("utf-8"),
            {"Content-Type": "application/x-www-form-urlencoded"},
            timeout,
        )
        if data.get("ok"):
            return "Foto publicada no Telegram."
        if "chat not found" in str(data.get("description") or "").lower():
            raise ChannelError(str(data.get("description")))
    payload.pop("photo", None)
    payload.pop("caption", None)
    payload["text"] = caption
    payload["disable_web_page_preview"] = "true"
    data = post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        urllib.parse.urlencode(payload).encode("utf-8"),
        {"Content-Type": "application/x-www-form-urlencoded"},
        timeout,
    )
    if not data.get("ok"):
        raise ChannelError(data.get("description") or "O Telegram recusou a mensagem.")
    return "Mensagem publicada no Telegram."


def offer_button(url: str) -> dict:
    if not str(url).startswith("http"):
        return {"inline_keyboard": []}
    return {"inline_keyboard": [[{"text": "🛒 Pegar oferta", "url": url}]]}


def send_whatsapp(settings: dict, offer: dict, text: str, timeout: int) -> str:
    token = str(settings.get("accessToken") or "").strip()
    phone_id = str(settings.get("phoneNumberId") or "").strip()
    recipient = "".join(ch for ch in str(settings.get("recipient") or "") if ch.isdigit())
    version = str(settings.get("apiVersion") or "v21.0").strip() or "v21.0"
    if not token or not phone_id or not recipient:
        raise ChannelError("Informe o token, o Phone Number ID e o destinatário do WhatsApp.")

    if settings.get("delivery") == "template":
        name = str(settings.get("templateName") or "").strip()
        if not name:
            raise ChannelError("Informe o nome do template aprovado no WhatsApp.")
        language = str(settings.get("templateLanguage") or "pt_BR").strip() or "pt_BR"
        parameters = [
            offer.get("title") or "",
            offer.get("priceLabel") or "",
            f"{offer.get('discount') or 0}%",
            offer.get("url") or "",
        ]
        message = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": item[:900]} for item in parameters],
                    }
                ],
            },
        }
    elif offer.get("image"):
        message = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "image",
            "image": {"link": offer["image"], "caption": text[:1024]},
        }
    else:
        message = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": True, "body": text[:4000]},
        }

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    data = post_json(
        url,
        json.dumps(message).encode("utf-8"),
        {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout,
    )
    if data.get("error"):
        err = data["error"]
        raise ChannelError(err.get("message") or "O WhatsApp recusou a mensagem.")
    return "Mensagem aceita pela API do WhatsApp."


def check_telegram(settings: dict, timeout: int) -> str:
    token = str(settings.get("botToken") or "").strip()
    if not token:
        raise ChannelError("Informe o token do bot.")
    data = get_json(f"https://api.telegram.org/bot{token}/getMe", timeout)
    if not data.get("ok"):
        raise ChannelError(data.get("description") or "Token do Telegram inválido.")
    result = data.get("result") or {}
    username = result.get("username") or result.get("first_name") or "bot"
    return f"Telegram conectado: @{username}."


def check_whatsapp(settings: dict, timeout: int) -> str:
    token = str(settings.get("accessToken") or "").strip()
    phone_id = str(settings.get("phoneNumberId") or "").strip()
    version = str(settings.get("apiVersion") or "v21.0").strip() or "v21.0"
    if not token or not phone_id:
        raise ChannelError("Informe o token e o Phone Number ID.")
    data = get_json(
        f"https://graph.facebook.com/{version}/{phone_id}",
        timeout,
        {"Authorization": f"Bearer {token}"},
    )
    if data.get("error"):
        raise ChannelError(data["error"].get("message") or "Credencial do WhatsApp inválida.")
    label = data.get("display_phone_number") or data.get("verified_name") or phone_id
    return f"WhatsApp conectado: {label}."


def post_json(url: str, body: bytes, headers: dict, timeout: int) -> dict:
    return call_json(url, body, headers, timeout)


def get_json(url: str, timeout: int, headers: dict | None = None) -> dict:
    return call_json(url, None, headers or {}, timeout)


def call_json(url: str, body: bytes | None, headers: dict, timeout: int) -> dict:
    request = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ChannelError(f"HTTP {error.code}. {raw[:240]}") from error
    except urllib.error.URLError as error:
        raise ChannelError(f"Sem conexão. {error.reason}") from error
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise ChannelError("Resposta inválida do canal.") from error
    return parsed if isinstance(parsed, dict) else {}
