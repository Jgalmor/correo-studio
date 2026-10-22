"""Extract attributable website copy and render a portable marketing email."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit


SPACES = re.compile(r"\s+")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def clean(value: str, limit: int = 180) -> str:
    return SPACES.sub(" ", html.unescape(value or "")).strip()[:limit]


def validate_url(value: str) -> str:
    value = (value or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Introduce una URL pública HTTP o HTTPS válida, sin credenciales.")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Puerto no válido.") from exc
    if port not in (None, 80, 443):
        raise ValueError("Solo se permiten los puertos web estándar.")
    hostname = parts.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost") or "." not in hostname:
        raise ValueError("La URL debe apuntar a un dominio público.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("No se admiten direcciones IP directas.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def public_addresses(url: str) -> list[str]:
    parts = urlsplit(validate_url(url))
    try:
        results = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("No se pudo resolver el dominio.") from exc
    addresses = [result[4][0] for result in results]
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("El dominio resuelve a una red privada o no pública.")
    return addresses


def asset_url(base: str, value: str) -> str:
    if not value or not value.strip():
        return ""
    candidate = urljoin(base, html.unescape(value).strip())
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    if parts.path.lower().endswith((".svg", ".gif")):
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = "es"
        self.title = ""
        self.description = ""
        self.site_name = ""
        self.og_image = ""
        self.theme_color = ""
        self.logo = ""
        self.images: list[tuple[int, str]] = []
        self.claims: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.styles = ""
        self._capture = ""
        self._text: list[str] = []
        self._href = ""
        self._ignore = 0
        self._header = 0
        self._cookie_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if self._capture and tag in ("span", "strong", "em", "b", "i", "br") and self._text:
            self._text.append(" ")
        if tag in ("div", "section", "aside", "dialog"):
            marker = ((attr.get("class") or "") + " " + (attr.get("id") or "")).lower()
            if self._cookie_depth or any(word in marker for word in ("cookie", "consent", "gdpr")):
                self._cookie_depth += 1
        if tag in ("script", "noscript", "svg", "footer", "nav"):
            self._ignore += 1
        if tag == "html":
            self.lang = (attr.get("lang") or "es").split("-")[0].lower()
        if tag == "header":
            self._header += 1
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content") or ""
            for prop, field in (("description", "description"), ("og:description", "description"), ("og:site_name", "site_name"), ("og:image", "og_image"), ("theme-color", "theme_color")):
                if key == prop and (field != "description" or not self.description):
                    setattr(self, field, content)
        if tag == "img" and not self._ignore and not self._cookie_depth:
            src = attr.get("src") or attr.get("data-src") or ""
            alt = (attr.get("alt") or "").lower()
            classes = ((attr.get("class") or "") + " " + (attr.get("id") or "")).lower()
            if src:
                if "logo" in (alt + classes + src.lower()) or self._header:
                    if not self.logo:
                        self.logo = src
                else:
                    score = 2 if "hero" in classes or "banner" in classes else 1
                    self.images.append((score, src))
        if self._ignore or self._cookie_depth:
            return
        if tag in ("title", "h1", "h2", "h3", "p", "a", "style"):
            self._capture = tag
            self._text = []
            self._href = attr.get("href") or "" if tag == "a" else ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag in ("span", "strong", "em", "b", "i"):
            self._text.append(" ")
        if tag == self._capture:
            text = clean("".join(self._text), 400 if tag == "style" else 180)
            if tag == "title":
                self.title = text
            elif tag == "style":
                self.styles += text + " "
            elif tag == "a" and text:
                self.links.append((text, self._href))
            elif tag in ("h1", "h2", "h3", "p") and len(text) >= 12:
                self.claims.append(text)
            self._capture = ""
            self._text = []
        if tag == "header":
            self._header = max(0, self._header - 1)
        if tag in ("div", "section", "aside", "dialog") and self._cookie_depth:
            self._cookie_depth -= 1
        if tag in ("script", "noscript", "svg", "footer", "nav"):
            self._ignore = max(0, self._ignore - 1)


def readable_color(value: str) -> str:
    match = HEX.search(value or "")
    if not match:
        return "#183D45"
    color = match.group().upper()
    if len(color) == 4:
        color = "#" + "".join(c * 2 for c in color[1:])
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    # White text must be readable on the campaign's main call-to-action.
    def linear(component: int) -> float:
        fraction = component / 255
        return fraction / 12.92 if fraction <= 0.04045 else ((fraction + 0.055) / 1.055) ** 2.4
    luminance = 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
    if (1.05 / (luminance + 0.05)) < 4.5:
        for scale_percent in range(99, 0, -1):
            components = [round(component * scale_percent / 100) for component in (red, green, blue)]
            luminance = sum(weight * linear(component) for weight, component in zip((0.2126, 0.7152, 0.0722), components))
            if (1.05 / (luminance + 0.05)) >= 4.5:
                return "#" + "".join(f"{component:02X}" for component in components)
    return color


def analyze_page(url: str, source: str) -> dict:
    url = validate_url(url)
    parser = PageParser()
    parser.feed(source[:1_500_000])
    if any(phrase in parser.title.lower() for phrase in ("routing to checkout", "temporarily unavailable", "access denied", "just a moment", "service unavailable")):
        raise ValueError("La web muestra una página de mantenimiento o bloqueo; prueba otra URL pública.")
    name = clean(parser.site_name or parser.title.split("|")[0].split("—")[0] or urlsplit(url).hostname, 70)
    claims = []
    for text in parser.claims:
        if any(phrase in text.lower() for phrase in ("choose your language", "following languages", "selecciona tu idioma", "elige tu idioma")):
            continue
        if text.casefold() not in {claim.casefold() for claim in claims}:
            claims.append(text)
    logo = asset_url(url, parser.logo)
    promo = asset_url(url, parser.og_image)
    if not promo:
        for _, image in sorted(parser.images, reverse=True):
            promo = asset_url(url, image)
            if promo:
                break
    cta_pattern = re.compile(r"^(?:descubr\w*|compr\w*|explor\w*|ver|shop\s+(?:now|all|our|the)|discover|learn|conoc\w*|reserv\w*|visita\w*)\b", re.I)
    cta_text = "Visitar la web" if parser.lang == "es" else "Visit the website"
    destination = url
    for text, href in parser.links:
        target = asset_url(url, href)
        if target and urlsplit(target).hostname == urlsplit(url).hostname and cta_pattern.search(text):
            cta_text, destination = clean(text, 48), target
            break
    css_colors = re.search(r"--(?:brand|primary|main)(?:-[\w-]+)?\s*:\s*(#[0-9a-fA-F]{3,6})\b", parser.styles, re.I)
    detected_color = parser.theme_color or (css_colors.group(1) if css_colors else "")
    return {
        "name": name,
        "url": url,
        "logo": logo,
        "image": promo if promo != logo else "",
        "color": readable_color(detected_color),
        "color_detected": bool(HEX.search(detected_color)),
        "headline": claims[0] if claims else clean(parser.description or parser.title or name),
        "claims": claims[1:3],
        "description": clean(parser.description, 200),
        "cta": cta_text,
        "destination": destination,
        "lang": parser.lang if parser.lang in ("es", "en") else "es",
    }


def render_email(data: dict) -> str:
    e = lambda value: html.escape(str(value or ""), quote=True)
    spanish = data["lang"] == "es"
    caption = "UNA SELECCIÓN PARA TI" if spanish else "A SELECTION FOR YOU"
    footer = f"Comunicación de {e(data['name'])}." if spanish else f"A message from {e(data['name'])}."
    unsubscribe = "Darse de baja" if spanish else "Unsubscribe"
    headline = e(data["headline"] or data["name"])
    description = e(data["description"])
    detail = "" if not description or description.casefold() == headline.casefold() else f'<p style="margin:0 0 20px;color:#48565A;font-size:16px;line-height:25px;">{description}</p>'
    claims = "".join(f'<tr><td style="padding:0 0 12px;color:#29383C;font-size:15px;line-height:23px;">&#10003;&nbsp; {e(item)}</td></tr>' for item in data["claims"])
    claim_block = f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:6px 0 24px;">{claims}</table>' if claims else ""
    image = f'<tr><td><img src="{e(data["image"])}" width="600" alt="{e(data["name"])}" style="display:block;width:100%;max-width:600px;height:auto;border:0;"></td></tr>' if data["image"] else ""
    logo = f'<img src="{e(data["logo"])}" width="140" alt="{e(data["name"])}" style="display:block;max-width:140px;max-height:64px;width:auto;height:auto;border:0;">' if data["logo"] else f'<strong style="font-size:22px;letter-spacing:-.6px;color:{e(data["color"])};">{e(data["name"])}</strong>'
    return f'''<!doctype html>
<html lang="{e(data['lang'])}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data['name'])}</title></head>
<body style="margin:0;padding:0;background:#F1F3F1;font-family:Arial,Helvetica,sans-serif;color:#1F3034;">
<div style="display:none;font-size:1px;color:#F1F3F1;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{e(data['description'] or data['headline'])}</div>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#F1F3F1;"><tr><td align="center" style="padding:28px 12px 40px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="600" style="width:100%;max-width:600px;background:#FFFFFF;">
<tr><td style="padding:30px 36px;">{logo}</td></tr>
{image}
<tr><td style="padding:36px 36px 42px;">
<p style="margin:0 0 12px;color:{e(data['color'])};font-size:11px;font-weight:bold;letter-spacing:2px;">{caption}</p>
<h1 style="margin:0 0 18px;color:#182B30;font-size:30px;line-height:37px;font-weight:700;">{headline}</h1>
{detail}{claim_block}
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td bgcolor="{e(data['color'])}" style="background:{e(data['color'])};padding:16px 26px;text-align:center;">
<a href="{e(data['destination'])}" style="color:#FFFFFF;text-decoration:none;font-size:15px;font-weight:bold;display:inline-block;">{e(data['cta'])} &rarr;</a>
</td></tr></table></td></tr>
<tr><td style="border-top:1px solid #E6EAE6;padding:24px 36px 30px;color:#647174;font-size:12px;line-height:20px;">
{e(footer)}<br>{{{{sender_address}}}}<br><a href="{{{{unsubscribe_url}}}}" style="color:{e(data['color'])};text-decoration:underline;">{unsubscribe}</a>
</td></tr></table></td></tr></table></body></html>'''
