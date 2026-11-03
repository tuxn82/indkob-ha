"""Uofficiel nemlig.com-klient.

Ingen Home Assistant-imports her, så modulet også kan bruges fra tools/cli.py.

Kald (de samme som nemlig.com's egen frontend bruger):
  POST www.nemlig.com/webapi/login                 -> .ASPXAUTH + XSRF-cookies
  GET  www.nemlig.com/webapi/Token                 -> bearer-token (ca. 5 min)
  GET  www.nemlig.com/webapi/basket/GetBasket      -> kurv, timeslot, leveringszone
  POST www.nemlig.com/webapi/basket/AddToBasket    -> 'quantity' er det SAMLEDE antal
  GET  webapi.prod.knl.nemlig.it/searchgateway/api/search
Stregkoder slås op i Open Food Facts, da nemlig ikke har EAN i deres data.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass
from typing import Any

import aiohttp
from yarl import URL

WWW = "https://www.nemlig.com"
API = "https://webapi.prod.knl.nemlig.it"
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{ean}.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
)
OFF_UA = "nemlig-ha/0.1 (Home Assistant custom integration)"


class NemligError(Exception):
    """Generel fejl fra nemlig."""


class NemligAuthError(NemligError):
    """Login fejlede."""


@dataclass
class Product:
    """Et produkt fra nemligs søgning."""

    product_id: str
    name: str
    brand: str
    description: str  # fx "1 l / Arla"
    price: float | None
    category: str
    subcategory: str
    available: bool

    @classmethod
    def from_search(cls, d: dict[str, Any]) -> Product:
        avail = d.get("Availability") or {}
        return cls(
            product_id=str(d.get("Id")),
            name=d.get("Name") or "",
            brand=d.get("Brand") or "",
            description=d.get("Description") or "",
            price=d.get("Price"),
            category=d.get("Category") or "",
            subcategory=d.get("SubCategory") or "",
            available=bool(
                avail.get("IsDeliveryAvailable", True)
                and avail.get("IsAvailableInStock", True)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        price = f"{self.price:.2f} kr" if isinstance(self.price, (int, float)) else "?"
        flag = "" if self.available else "  [ikke på lager]"
        return f"{self.product_id:>8}  {self.name} – {self.description}  ({price}){flag}"


class NemligClient:
    """Async klient. Sessionen skal have sin egen cookie-jar."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._s = session
        self._user = username
        self._pass = password
        self._token: str | None = None
        self._token_exp = 0.0
        self.timeslot_utc: str | None = None
        self.delivery_zone_id: int | None = None

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "origin": WWW,
            "referer": WWW + "/",
            "user-agent": UA,
        }

    def _xsrf(self) -> str | None:
        morsel = self._s.cookie_jar.filter_cookies(URL(WWW)).get("XSRF-TOKEN")
        return morsel.value if morsel else None

    async def _www(
        self, method: str, path: str, *, json_body: Any = None,
        xsrf: bool = False, retry: bool = True,
    ) -> Any:
        headers = self._headers()
        if xsrf and (tok := self._xsrf()):
            headers["x-xsrf-token"] = tok
        async with self._s.request(method, WWW + path, json=json_body, headers=headers) as r:
            text = await r.text()
            status = r.status
        if status in (401, 403) and retry:
            await self.login()
            return await self._www(method, path, json_body=json_body, xsrf=xsrf, retry=False)
        if status >= 400:
            raise NemligError(f"{method} {path}: HTTP {status}: {text[:300]}")
        return json.loads(text) if text.strip() else None

    # ------------------------------------------------------------ auth
    async def login(self) -> None:
        async with self._s.get(WWW + "/", headers={"user-agent": UA}) as r:
            await r.read()
        body = {
            "AppInstalled": False,
            "CheckForExistingProducts": True,
            "DoMerge": True,
            "SaveExistingBasket": False,
            "username": self._user,
            "password": self._pass,
        }
        async with self._s.post(f"{WWW}/webapi/login", json=body, headers=self._headers()) as r:
            text = await r.text()
            status = r.status
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        if status != 200:
            msg = data.get("ErrorMessage") if isinstance(data, dict) else None
            raise NemligAuthError(msg or f"Login fejlede: HTTP {status}")
        if isinstance(data, dict):
            self.timeslot_utc = data.get("TimeslotUtc") or self.timeslot_utc
            self.delivery_zone_id = data.get("DeliveryZoneId") or self.delivery_zone_id
        self._token = None

    async def _bearer(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_exp - 30:
            return self._token
        data = await self._www("GET", "/webapi/Token")
        tok = data["access_token"]
        self._token = tok
        self._token_exp = _jwt_exp(tok) or time.time() + 240
        return tok

    # ------------------------------------------------------------ basket
    async def get_basket(self) -> dict[str, Any]:
        basket = await self._www("GET", "/webapi/basket/GetBasket") or {}
        if ts := _find_key(basket, "TimeslotUtc"):
            self.timeslot_utc = ts
        if zone := _find_key(basket, "DeliveryZoneId"):
            self.delivery_zone_id = zone
        return basket

    async def basket_quantity(self, product_id: str) -> int:
        basket = await self.get_basket()
        for line in basket.get("Lines") or []:
            if line_product_id(line) == str(product_id):
                return line_quantity(line)
        return 0

    async def add_to_basket(self, product_id: str, add: int = 1) -> tuple[int, int]:
        """Lægger `add` stk. oveni det, der ligger i kurven. Returnerer (før, efter)."""
        before = await self.basket_quantity(product_id)
        after = max(0, before + add)
        body = {
            "ProductId": str(product_id),
            "quantity": after,
            "AffectPartialQuantity": False,
            "disableQuantityValidation": False,
        }
        await self._www("POST", "/webapi/basket/AddToBasket", json_body=body, xsrf=True)
        return before, after

    # ------------------------------------------------------------ search
    async def search(self, query: str, take: int = 20) -> list[Product]:
        if not (self.timeslot_utc and self.delivery_zone_id):
            await self.get_basket()
        params = {
            "query": query,
            "take": take,
            "skip": 0,
            "timeslotUtc": self.timeslot_utc,
            "deliveryZoneId": self.delivery_zone_id,
        }
        for attempt in (0, 1):
            headers = self._headers() | {
                "authorization": f"Bearer {await self._bearer(force=attempt == 1)}"
            }
            async with self._s.get(
                f"{API}/searchgateway/api/search", params=params, headers=headers
            ) as r:
                status = r.status
                data = await r.json(content_type=None) if status == 200 else None
            if status == 401 and attempt == 0:
                continue
            if status != 200:
                raise NemligError(f"Søgning fejlede: HTTP {status}")
            break
        items = ((data or {}).get("Products") or {}).get("Products") or []
        return [
            Product.from_search(p)
            for p in items
            if p.get("Id") and p.get("TemplateName", "productlistitem") == "productlistitem"
        ]


async def lookup_ean(session: aiohttp.ClientSession, ean: str) -> dict[str, Any] | None:
    """Slår en stregkode op i Open Food Facts."""
    params = {"fields": "product_name,product_name_da,brands,quantity,categories"}
    async with session.get(
        OFF_URL.format(ean=ean), params=params, headers={"user-agent": OFF_UA}
    ) as r:
        if r.status != 200:
            return None
        data = await r.json(content_type=None)
    return data.get("product") if data.get("status") == 1 else None


# ---------------------------------------------------------------- helpers

def _jwt_exp(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, ValueError, KeyError):
        return None


def _find_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        for v in obj.values():
            if (found := _find_key(v, key)) is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            if (found := _find_key(v, key)) is not None:
                return found
    return None


def line_product_id(line: dict[str, Any]) -> str:
    """Produkt-id på en kurvlinje. Feltnavnet er endnu ikke verificeret."""
    return str(line.get("ProductId") or line.get("ProductNumber") or line.get("Id") or "")


def line_quantity(line: dict[str, Any]) -> int:
    """Antal på en kurvlinje. Feltnavnet er endnu ikke verificeret."""
    for k in ("Quantity", "quantity", "Amount", "Count"):
        if isinstance(line.get(k), (int, float)):
            return int(line[k])
    return 0
