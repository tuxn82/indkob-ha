"""Indkøbslisten: varer, antal og lærte koblinger til butiksprodukter."""
from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .matching import normalize

NEEDS_ACTION = "needs_action"
COMPLETED = "completed"

_QTY_RE = re.compile(r"^\s*(\d{1,3})\s*[x×*]\s*(.+)$", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"\[(\d{3,})\]")


@dataclass
class Item:
    uid: str
    name: str
    quantity: int = 1
    status: str = NEEDS_ACTION
    barcode: str | None = None
    off: dict[str, Any] | None = None       # Open Food Facts-data fra scanning
    product_id: str | None = None           # nemlig-produkt
    product_name: str | None = None
    note: str = ""

    # -- visning i HA's to-do-liste
    @property
    def summary(self) -> str:
        return f"{self.quantity} × {self.name}" if self.quantity > 1 else self.name

    @property
    def description(self) -> str | None:
        lines = []
        if self.product_id:
            lines.append(f"nemlig: {self.product_name or ''} [{self.product_id}]".replace(":  [", ": ["))
        if self.note:
            lines.append(self.note)
        return "\n".join(lines) or None

    @staticmethod
    def parse_summary(summary: str) -> tuple[int, str]:
        if m := _QTY_RE.match(summary or ""):
            return max(1, int(m.group(1))), m.group(2).strip()
        return 1, (summary or "").strip()


@dataclass
class ShoppingList:
    hass: HomeAssistant
    entry_id: str
    items: list[Item] = field(default_factory=list)
    learned: dict[str, dict[str, str]] = field(default_factory=dict)
    pending: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _listeners: list[Callable[[], None]] = field(default_factory=list)
    _store: Store | None = None

    async def async_load(self) -> None:
        self._store = Store(self.hass, STORAGE_VERSION, f"{STORAGE_KEY}_{self.entry_id}")
        data = await self._store.async_load() or {}
        self.items = [Item(**i) for i in data.get("items", [])]
        self.learned = data.get("learned", {})

    @callback
    def _changed(self) -> None:
        assert self._store
        self._store.async_delay_save(
            lambda: {"items": [asdict(i) for i in self.items], "learned": self.learned}, 1
        )
        for cb in list(self._listeners):
            cb()

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    # -- opslag
    def get(self, uid: str) -> Item | None:
        return next((i for i in self.items if i.uid == uid), None)

    def find(self, ref: str) -> Item | None:
        """Find en åben vare på uid eller navn."""
        if item := self.get(ref):
            return item
        key = normalize(ref)
        return next(
            (i for i in self.items if i.status == NEEDS_ACTION and normalize(i.name) == key),
            None,
        )

    def open_items(self) -> list[Item]:
        return [i for i in self.items if i.status == NEEDS_ACTION]

    # -- ændringer
    @callback
    def add(
        self, name: str, quantity: int = 1, *, barcode: str | None = None,
        off: dict[str, Any] | None = None, note: str = "",
    ) -> Item:
        """Tilføjer en vare, eller tæller op hvis den allerede står på listen."""
        product = self.learned_for(barcode=barcode, name=name)
        for item in self.open_items():
            same = (
                (barcode and item.barcode == barcode)
                or (product and item.product_id == product["product_id"])
                or normalize(item.name) == normalize(name)
            )
            if same:
                item.quantity += quantity
                self._changed()
                return item
        item = Item(
            uid=uuid.uuid4().hex, name=name, quantity=quantity, barcode=barcode,
            off=off, note=note,
            product_id=product["product_id"] if product else None,
            product_name=product["name"] if product else None,
        )
        self.items.append(item)
        self._changed()
        return item

    @callback
    def update_from_todo(
        self, uid: str, summary: str, status: str, description: str | None
    ) -> None:
        item = self.get(uid)
        if not item:
            return
        item.quantity, item.name = Item.parse_summary(summary)
        item.status = status
        # Første linje "nemlig: ... [id]" styrer produktet; resten er en note
        lines = (description or "").splitlines()
        if lines and lines[0].lower().startswith("nemlig"):
            m = _PRODUCT_RE.search(lines[0])
            if m and m.group(1) != item.product_id:
                self.set_product(item, m.group(1), None, learn=True, notify=False)
            elif not m:
                item.product_id = item.product_name = None
            lines = lines[1:]
        elif item.product_id and description is not None:
            # Beskrivelsen er ryddet eller omskrevet uden nemlig-linje: glem matchet
            item.product_id = item.product_name = None
        item.note = "\n".join(lines).strip()
        self._changed()

    @callback
    def set_product(
        self, item: Item, product_id: str, name: str | None, *,
        learn: bool = True, notify: bool = True,
    ) -> None:
        same = item.product_id == str(product_id)
        item.product_id = str(product_id)
        item.product_name = name or (item.product_name if same else None)
        if learn:
            entry = {"product_id": str(product_id), "name": name or str(product_id)}
            if item.barcode:
                self.learned[f"ean:{item.barcode}"] = entry
            self.learned[f"txt:{normalize(item.name)}"] = entry
        self.pending.pop(item.uid, None)
        if notify:
            self._changed()

    @callback
    def set_status(self, item: Item, status: str) -> None:
        item.status = status
        self._changed()

    @callback
    def delete(self, uids: list[str]) -> None:
        self.items = [i for i in self.items if i.uid not in uids]
        for uid in uids:
            self.pending.pop(uid, None)
        self._changed()

    @callback
    def move(self, uid: str, previous_uid: str | None) -> None:
        item = self.get(uid)
        if not item:
            return
        self.items.remove(item)
        idx = 0
        if previous_uid and (prev := self.get(previous_uid)):
            idx = self.items.index(prev) + 1
        self.items.insert(idx, item)
        self._changed()

    # -- lærte koblinger
    def learned_for(self, *, barcode: str | None = None, name: str | None = None) -> dict[str, str] | None:
        if barcode and (hit := self.learned.get(f"ean:{barcode}")):
            return hit
        if name and (hit := self.learned.get(f"txt:{normalize(name)}")):
            return hit
        return None

    @callback
    def forget(self, ref: str) -> bool:
        removed = False
        for key in (f"ean:{ref.strip()}", f"txt:{normalize(ref)}"):
            removed |= self.learned.pop(key, None) is not None
        if removed:
            self._changed()
        return removed
