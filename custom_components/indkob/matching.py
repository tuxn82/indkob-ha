"""Matcher et Open Food Facts-produkt mod nemligs søgeresultater.

Ren Python uden imports fra pakken, så det kan bruges fra tools/cli.py.
"""
from __future__ import annotations

import re
from typing import Any

_UNITS = {
    "kg": ("g", 1000), "g": ("g", 1), "gr": ("g", 1),
    "l": ("ml", 1000), "ltr": ("ml", 1000), "dl": ("ml", 100),
    "cl": ("ml", 10), "ml": ("ml", 1),
}
_STOP = {"med", "og", "til", "uden", "fra", "stk", "pak"}


def parse_qty(text: str | None) -> tuple[float, str] | None:
    """'1l', '1 l', '0,25 l', '6 x 33 cl', '500 g' -> (mængde i ml/g, enhed)."""
    if not text:
        return None
    t = text.lower().replace(",", ".")
    m = re.search(r"(?:(\d+)\s*x\s*)?(\d+(?:\.\d+)?)\s*(kg|gr|g|ltr|l|dl|cl|ml)\b", t)
    if not m:
        return None
    count = int(m.group(1) or 1)
    unit, factor = _UNITS[m.group(3)]
    return count * float(m.group(2)) * factor, unit


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-zæøåé]+", text.lower())
        if len(w) >= 3 and w not in _STOP
    }


def build_query(off: dict[str, Any]) -> str:
    brand = (off.get("brands") or "").split(",")[0].strip()
    name = off.get("product_name_da") or off.get("product_name") or ""
    name = re.sub(r"\d+([.,]\d+)?\s*%", "", name).strip()
    return f"{brand} {name}".strip()


def score(off: dict[str, Any], p: Any) -> float:
    """p er et api.Product (eller noget med samme felter)."""
    off_brand = (off.get("brands") or "").split(",")[0].strip().lower()
    off_name = off.get("product_name_da") or off.get("product_name") or ""
    off_text = " ".join([off_name, off.get("product_name") or "", off.get("categories") or ""])
    off_compact = re.sub(r"\s+", "", off_text.lower())
    s = 0.0

    if off_brand and (off_brand in p.brand.lower() or p.brand.lower() in off_brand):
        s += 3

    q_off = parse_qty(off.get("quantity"))
    q_p = parse_qty(p.description.split("/")[0])
    if q_off and q_p:
        same = q_off[1] == q_p[1] and abs(q_off[0] - q_p[0]) <= 0.02 * q_off[0]
        s += 3 if same else -2

    name_tokens = _tokens(p.name)
    if name_tokens:
        s += 4 * sum(t in off_compact for t in name_tokens) / len(name_tokens)

    # Ord i nemlig-varen som OFF ikke nævner (øko, laktosefri, skolemælk ...) trækker ned
    extra = (_tokens(p.name) | _tokens(p.description)) - _tokens(p.brand)
    s -= 0.75 * sum(t not in off_compact for t in extra)

    if not p.available:
        s -= 1
    return s


def rank(off: dict[str, Any], products: list[Any]) -> list[tuple[float, Any]]:
    n = max(len(products), 1)
    scored = [(score(off, p) + 0.5 * (1 - i / n), p) for i, p in enumerate(products)]
    return sorted(scored, key=lambda x: x[0], reverse=True)


# Stregkode-match har mærke og mængde fra Open Food Facts og kan nå højere scorer
# end rene tekstvarer ("mælk"), som derfor har en lavere tærskel.
BARCODE_THRESHOLD = (7.0, 1.5)
TEXT_THRESHOLD = (3.5, 1.0)


def is_confident(
    ranked: list[tuple[float, Any]], threshold: tuple[float, float] = BARCODE_THRESHOLD
) -> bool:
    if not ranked:
        return False
    best = ranked[0][0]
    second = ranked[1][0] if len(ranked) > 1 else -99
    return best >= threshold[0] and best - second >= threshold[1]


def text_as_off(name: str) -> dict[str, Any]:
    """Behandler en fritekstvare som et OFF-produkt uden mærke og mængde."""
    return {"product_name_da": name, "brands": "", "quantity": parse_qty_text(name)}


def parse_qty_text(name: str) -> str:
    m = re.search(r"\d+(?:[.,]\d+)?\s*(?:kg|gr|g|ltr|l|dl|cl|ml)\b", name.lower())
    return m.group(0) if m else ""


def display_name(off: dict[str, Any]) -> str:
    """'Arla Letmælk' ud fra et OFF-produkt."""
    name = off.get("product_name_da") or off.get("product_name") or ""
    brand = (off.get("brands") or "").split(",")[0].strip()
    if brand and brand.lower() not in name.lower():
        return f"{brand} {name}".strip()
    return name.strip()


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-zæøåé0-9]+", text.lower()))


def is_relevant(query: str, p: Any) -> bool:
    """Har produktet mindst ét ord til fælles med det søgte (i begge retninger)?"""
    cand = re.sub(r"\s+", "", f"{p.name} {p.description} {p.brand}".lower())
    q = re.sub(r"\s+", "", query.lower())
    return any(t in cand for t in _tokens(query)) or any(t in q for t in _tokens(p.name))
