"""Image consultants: called on demand for one image, never seated in the arc.

Each provider uses its own key from the backend .env; a provider without a key is simply
unavailable. Keys are sent only to that provider, never to the browser or to a model.
The "practice" consultant draws simple SVG logos and banners locally, for free, so the
whole flow works without any image keys (and in tests).
"""

import base64
import hashlib
import html
import re
from dataclasses import dataclass

import httpx

from app.config import get_settings

MAX_IMAGE_BYTES = 4_000_000


class ImageError(RuntimeError):
    pass


@dataclass
class ImageResult:
    data: bytes
    ext: str  # ".svg", ".png", ".webp" or ".jpg"
    consultant: str
    cost_usd: float


@dataclass(frozen=True)
class Consultant:
    key: str
    label: str
    env_key: str  # setting name holding the API key ("" = none needed)
    vector: bool = False

    def available(self) -> bool:
        return not self.env_key or bool(getattr(get_settings(), self.env_key, ""))

    def price(self) -> float:
        return float(get_settings().image_prices.get(self.key, 0.08))


CONSULTANTS: dict[str, Consultant] = {
    c.key: c
    for c in [
        Consultant("recraft", "Recraft (vector)", "recraft_api_key", vector=True),
        Consultant("openai", "OpenAI images", "openai_api_key"),
        Consultant("gemini", "Gemini image", "gemini_api_key"),
        Consultant("flux", "FLUX (Black Forest Labs)", "bfl_api_key"),
        Consultant("seedream", "Seedream (ByteDance)", "seedream_api_key"),
        Consultant("practice", "Practice (local SVG)", ""),
    ]
}


def available_consultants() -> list[str]:
    return [k for k, c in CONSULTANTS.items() if c.available()]


def pick_consultant(requested: str | None, kind: str) -> Consultant:
    """The design lead's choice if it is available; else Recraft for logos, else the first
    available real provider; else the practice consultant."""
    avail = available_consultants()
    if requested in avail:
        return CONSULTANTS[requested]
    order = (["recraft"] if kind == "logo" else []) + ["openai", "gemini", "flux", "seedream", "recraft"]
    for key in order:
        if key in avail:
            return CONSULTANTS[key]
    return CONSULTANTS["practice"]


# ---------------------------------------------------------------- SVG safety

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
SVG_ELEMENTS = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan",
    "defs", "lineargradient", "radialgradient", "stop", "clippath", "mask", "title", "desc", "symbol",
    "use", "pattern", "filter", "fegaussianblur", "feoffset", "feblend", "fecolormatrix", "feflood",
    "fecomposite", "femerge", "femergenode", "fedropshadow", "metadata",
}
SVG_ATTRIBUTES = {
    "viewbox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d",
    "points", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-miterlimit", "opacity", "transform",
    "offset", "stop-color", "stop-opacity", "gradientunits", "gradienttransform", "spreadmethod", "fx", "fy",
    "font-family", "font-size", "font-weight", "font-style", "text-anchor", "dominant-baseline",
    "letter-spacing", "id", "class", "clip-path", "clip-rule", "mask", "filter", "preserveaspectratio",
    "role", "aria-label", "href", "patternunits", "patterncontentunits", "stddeviation", "dx", "dy",
    "in", "in2", "result", "mode", "values", "type", "flood-color", "flood-opacity", "operator",
    "version", "style", "display", "visibility", "vector-effect", "paint-order",
}
_UNSAFE_VALUE = re.compile(r"javascript:|data:|expression\(|url\(\s*['\"]?(?!#)|@import", re.I)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def sanitize_svg(data: bytes) -> bytes:
    """SVG can carry code. Parse it and keep only known drawing elements and attributes;
    links may only point inside the image (#id). Anything else is dropped."""
    from xml.etree import ElementTree

    import defusedxml.ElementTree as SafeET
    from defusedxml import DefusedXmlException

    try:
        root = SafeET.fromstring(data)
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as exc:
        raise ImageError(f"The SVG could not be read safely: {exc}") from exc
    if _local(root.tag) != "svg":
        raise ImageError("The consultant did not return an SVG.")

    def clean(el) -> None:
        for child in list(el):
            if not isinstance(child.tag, str) or _local(child.tag) not in SVG_ELEMENTS:
                el.remove(child)
            else:
                clean(child)
        for attr in list(el.attrib):
            name = _local(attr)
            value = el.attrib[attr]
            if name not in SVG_ATTRIBUTES or _UNSAFE_VALUE.search(value):
                del el.attrib[attr]
            elif name == "href" and not value.strip().startswith("#"):
                del el.attrib[attr]

    clean(root)
    ElementTree.register_namespace("", SVG_NS)
    ElementTree.register_namespace("xlink", XLINK_NS)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=False)


def sniff(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if b"<svg" in data[:2000].lower():
        return ".svg"
    raise ImageError("The consultant returned something that is not a PNG, JPEG, WebP or SVG image.")


def check_image(data: bytes) -> tuple[bytes, str]:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"The image is larger than {MAX_IMAGE_BYTES // 1_000_000} MB.")
    ext = sniff(data)
    if ext == ".svg":
        data = sanitize_svg(data)
    return data, ext


# ---------------------------------------------------------------- providers


def practice_svg(prompt: str, kind: str, palette: list[str] | None = None) -> bytes:
    """A clean, deterministic SVG: a monogram mark for logos, a soft banner otherwise."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z']+", prompt) if len(w) > 2][:6]
    name = next((m.group(1) for m in [re.search(r'"([^"]{2,40})"', prompt)] if m), None) or (
        " ".join(words[:2]).title() if words else "Studio")
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "S"
    h = int(hashlib.sha256(prompt.encode()).hexdigest(), 16)
    colours = palette or ["#7c6cf2", "#ff8a5b", "#22d3ee", "#34d399", "#f5a524"]
    a, b = colours[h % len(colours)], colours[(h // 7) % len(colours)]
    if a == b:
        b = colours[(colours.index(a) + 1) % len(colours)]
    label = html.escape(name)
    if kind == "logo":
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" width="240" height="240" role="img" aria-label="{label} logo">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
  <rect x="12" y="12" width="216" height="216" rx="56" fill="url(#g)"/>
  <circle cx="120" cy="120" r="74" fill="none" stroke="#ffffff" stroke-opacity=".35" stroke-width="6"/>
  <text x="120" y="142" text-anchor="middle" font-family="system-ui, sans-serif" font-size="68" font-weight="700" fill="#ffffff">{html.escape(initials)}</text>
</svg>
""".encode()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 600" width="1200" height="600" role="img" aria-label="{label}">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
  <rect width="1200" height="600" fill="url(#g)"/>
  <circle cx="{200 + h % 700}" cy="{150 + h % 300}" r="220" fill="#ffffff" fill-opacity=".12"/>
  <circle cx="{900 - h % 400}" cy="{420 - h % 200}" r="160" fill="#000000" fill-opacity=".10"/>
  <text x="600" y="320" text-anchor="middle" font-family="system-ui, sans-serif" font-size="72" font-weight="700" fill="#ffffff">{label}</text>
</svg>
""".encode()


async def _post(url: str, headers: dict[str, str], json_body: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        raise ImageError(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code >= 400:
        raise ImageError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def _download(url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        raise ImageError(f"Could not download the image: {exc}") from exc


async def generate(consultant: Consultant, prompt: str, kind: str, palette: list[str] | None = None) -> ImageResult:
    s = get_settings()
    key = consultant.key
    if key == "practice":
        data = practice_svg(prompt, kind, palette)
    elif key == "recraft":
        body = await _post(
            "https://external.api.recraft.ai/v1/images/generations",
            {"Authorization": f"Bearer {s.recraft_api_key}"},
            {"prompt": prompt, "style": "vector_illustration" if kind != "logo" else "icon",
             "model": "recraftv3", "response_format": "url", "size": "1024x1024"},
        )
        data = await _download(body["data"][0]["url"])
    elif key == "openai":
        body = await _post(
            "https://api.openai.com/v1/images/generations",
            {"Authorization": f"Bearer {s.openai_api_key}"},
            {"model": s.openai_image_model, "prompt": prompt, "size": "1024x1024", "n": 1},
        )
        item = body["data"][0]
        data = base64.b64decode(item["b64_json"]) if item.get("b64_json") else await _download(item["url"])
    elif key == "gemini":
        body = await _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_image_model}:generateContent",
            {"x-goog-api-key": s.gemini_api_key},
            {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {"responseModalities": ["IMAGE"]}},
        )
        parts = body["candidates"][0]["content"]["parts"]
        inline = next((p.get("inlineData") or p.get("inline_data") for p in parts
                       if p.get("inlineData") or p.get("inline_data")), None)
        if not inline:
            raise ImageError("Gemini returned no image.")
        data = base64.b64decode(inline["data"])
    elif key == "flux":
        body = await _post(
            f"https://api.bfl.ai/v1/{s.flux_model}", {"x-key": s.bfl_api_key},
            {"prompt": prompt, "width": 1024, "height": 1024},
        )
        data = await _poll_flux(body)
    elif key == "seedream":
        body = await _post(
            "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations",
            {"Authorization": f"Bearer {s.seedream_api_key}"},
            {"model": s.seedream_model, "prompt": prompt, "response_format": "b64_json", "size": "1024x1024"},
        )
        data = base64.b64decode(body["data"][0]["b64_json"])
    else:
        raise ImageError(f"Unknown consultant: {key}")
    data, ext = check_image(data)
    return ImageResult(data, ext, key, consultant.price())


async def _poll_flux(job: dict) -> bytes:
    import asyncio

    url = job.get("polling_url")
    if not url:
        raise ImageError("FLUX returned no polling URL.")
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(60):
            resp = await client.get(url, headers={"x-key": get_settings().bfl_api_key})
            body = resp.json()
            if body.get("status") == "Ready":
                return await _download(body["result"]["sample"])
            if body.get("status") in ("Error", "Failed", "Content Moderated", "Request Moderated"):
                raise ImageError(f"FLUX: {body.get('status')}")
            await asyncio.sleep(2)
    raise ImageError("FLUX did not finish in time.")
