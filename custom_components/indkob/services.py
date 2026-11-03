"""Services for Indkøb-integrationen."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_BARCODE, ATTR_DRY_RUN, ATTR_ITEM, ATTR_KEY, ATTR_LIMIT, ATTR_PRODUCT_ID,
    ATTR_QUANTITY, ATTR_QUERY, CONF_AUTO_PICK, DEFAULT_AUTO_PICK, DOMAIN, EVENT_ITEM_ADDED, EVENT_SENT, NOTIFICATION_ID,
    SERVICE_ADD_BY_BARCODE, SERVICE_FORGET_MATCH, SERVICE_RESOLVE_ITEM, SERVICE_SEARCH,
    SERVICE_SEND_TO_NEMLIG,
)
from .matching import (
    BARCODE_THRESHOLD, TEXT_THRESHOLD, build_query, display_name, is_confident, is_relevant, rank,
    text_as_off,
)
from .nemlig_api import NemligError, lookup_ean
from .shopping_list import COMPLETED, Item

if TYPE_CHECKING:
    from . import IndkobData

_LOGGER = logging.getLogger(__name__)
_ERRORS = (NemligError, aiohttp.ClientError, TimeoutError)
_QTY = vol.All(vol.Coerce(int), vol.Range(min=1, max=99))

ADD_BY_BARCODE_SCHEMA = vol.Schema({
    vol.Required(ATTR_BARCODE): cv.string,
    vol.Optional(ATTR_QUANTITY, default=1): _QTY,
})
SEND_SCHEMA = vol.Schema({vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean})
RESOLVE_SCHEMA = vol.Schema({
    vol.Required(ATTR_ITEM): cv.string,
    vol.Required(ATTR_PRODUCT_ID): cv.string,
})
FORGET_SCHEMA = vol.Schema({vol.Required(ATTR_KEY): cv.string})
SEARCH_SCHEMA = vol.Schema({
    vol.Required(ATTR_QUERY): cv.string,
    vol.Optional(ATTR_LIMIT, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
})


def _get_data(hass: HomeAssistant) -> IndkobData:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise ServiceValidationError("Indkøb-integrationen er ikke sat op eller ikke indlæst")


async def _match(data: IndkobData, item: Item) -> tuple[list[dict[str, Any]], bool]:
    """Søger på nemlig og rangerer. Returnerer (kandidater, sikkert match)."""
    if item.off:
        off, threshold, query = item.off, BARCODE_THRESHOLD, build_query(item.off)
    else:
        off, threshold, query = text_as_off(item.name), TEXT_THRESHOLD, item.name
    products = await data.client.search(query)
    if not products and item.off and item.off.get("product_name_da"):
        products = await data.client.search(item.off["product_name_da"])
    ranked = rank(off, products)[:5]
    candidates = [
        p.to_dict() | {"score": round(s, 1), "relevant": is_relevant(query, p)} for s, p in ranked
    ]
    return candidates, is_confident(ranked, threshold)


def _pick(data: IndkobData, cands: list[dict[str, Any]], confident: bool) -> tuple[dict[str, Any] | None, bool]:
    """Vælger et produkt. Returnerer (kandidat, skal_læres).

    Sikre match læres som faste koblinger. Med auto-valg slået til tages det
    bedste resultat også, men det læres ikke, så et forkert gæt ikke låses fast.
    """
    if not cands:
        return None, False
    if confident:
        return cands[0], True
    auto = data.entry.options.get(CONF_AUTO_PICK, DEFAULT_AUTO_PICK)
    if auto and cands[0].get("relevant"):
        return cands[0], False
    return None, False


def _label(c: dict[str, Any]) -> str:
    return f"{c['name']} – {c['description']}"


def _update_notification(hass: HomeAssistant, data: IndkobData) -> None:
    sl = data.shopping_list
    pending = [(sl.get(uid), c) for uid, c in sl.pending.items() if sl.get(uid)]
    if not pending:
        persistent_notification.async_dismiss(hass, NOTIFICATION_ID)
        return
    parts = []
    for item, cands in pending:
        lines = [f"**{item.summary}**"]
        lines += [
            f"{i}. {_label(c)} ({c['price']} kr) `[{c['product_id']}]`"
            for i, c in enumerate(cands, 1)
        ] or ["Ingen forslag fundet."]
        parts.append("\n".join(lines))
    persistent_notification.async_create(
        hass,
        "\n\n".join(parts)
        + "\n\nVælg ved at åbne varen på indkøbslisten og skrive `nemlig: [produkt-id]` "
        "i beskrivelsen, eller kald `indkob.resolve_item`. Valget huskes. "
        "Kør derefter **Send til nemlig** igen.",
        title="Indkøb: vælg varer",
        notification_id=NOTIFICATION_ID,
    )


async def _add_by_barcode(
    hass: HomeAssistant, data: IndkobData, ean: str, qty: int
) -> dict[str, Any]:
    sl = data.shopping_list
    known = sl.learned_for(barcode=ean)
    known_name = (known or {}).get("item_name")
    off = None if known_name else await lookup_ean(data.session, ean)
    if known_name:
        name = known_name
    elif off:
        name = display_name(off)
    else:
        name = f"Ukendt vare ({ean})"

    item = sl.add(name, qty, barcode=ean, off=off)

    # Match med det samme, så beskrivelsen viser varen. En fejl her må ikke
    # forhindre, at varen kommer på listen.
    if not item.product_id and off:
        try:
            cands, confident = await _match(data, item)
        except _ERRORS as err:
            _LOGGER.debug("Match ved scanning fejlede: %s", err)
        else:
            choice, learn = _pick(data, cands, confident)
            if choice:
                sl.set_product(item, choice["product_id"], _label(choice), learn=learn)

    result = {
        "barcode": ean, "uid": item.uid, "name": item.name, "quantity": item.quantity,
        "known": bool(known), "found_in_off": bool(off),
        "product_id": item.product_id, "product_name": item.product_name,
    }
    hass.bus.async_fire(EVENT_ITEM_ADDED, result)
    return result


async def _send_to_nemlig(
    hass: HomeAssistant, data: IndkobData, dry_run: bool
) -> dict[str, Any]:
    sl = data.shopping_list
    added: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for item in sl.open_items():
        if not item.product_id and (hit := sl.learned_for(barcode=item.barcode, name=item.name)):
            sl.set_product(item, hit["product_id"], hit["name"], learn=False)
        if not item.product_id:
            try:
                cands, confident = await _match(data, item)
            except _ERRORS as err:
                errors.append({"name": item.name, "error": str(err)})
                continue
            choice, learn = _pick(data, cands, confident)
            if choice:
                sl.set_product(item, choice["product_id"], _label(choice), learn=learn)
            else:
                sl.pending[item.uid] = cands
                unresolved.append({"uid": item.uid, "name": item.name, "candidates": cands})
                continue

        entry = {
            "uid": item.uid, "name": item.name, "quantity": item.quantity,
            "product_id": item.product_id, "product_name": item.product_name,
        }
        if dry_run:
            added.append(entry)
            continue
        try:
            before, after = await data.client.add_to_basket(item.product_id, item.quantity)
        except _ERRORS as err:
            errors.append(entry | {"error": str(err)})
            continue
        sl.set_status(item, COMPLETED)
        added.append(entry | {"basket_before": before, "basket_after": after})

    _update_notification(hass, data)
    if not dry_run:
        await data.coordinator.async_request_refresh()
    hass.bus.async_fire(EVENT_SENT, {
        "dry_run": dry_run, "added": len(added),
        "unresolved": len(unresolved), "errors": len(errors),
    })
    return {"dry_run": dry_run, "added": added, "unresolved": unresolved, "errors": errors}


def async_setup_services(hass: HomeAssistant) -> None:
    async def add_by_barcode(call: ServiceCall) -> ServiceResponse:
        data = _get_data(hass)
        ean = str(call.data[ATTR_BARCODE]).strip()
        try:
            result = await _add_by_barcode(hass, data, ean, call.data[ATTR_QUANTITY])
        except _ERRORS as err:
            raise HomeAssistantError(f"Indkøb: {err}") from err
        return result if call.return_response else None

    async def send_to_nemlig(call: ServiceCall) -> ServiceResponse:
        result = await _send_to_nemlig(hass, _get_data(hass), call.data[ATTR_DRY_RUN])
        return result if call.return_response else None

    async def resolve_item(call: ServiceCall) -> None:
        data = _get_data(hass)
        sl = data.shopping_list
        item = sl.find(call.data[ATTR_ITEM])
        if not item:
            raise ServiceValidationError(f"Varen '{call.data[ATTR_ITEM]}' findes ikke på listen")
        pid = str(call.data[ATTR_PRODUCT_ID]).strip()
        cand = next((c for c in sl.pending.get(item.uid, []) if c["product_id"] == pid), None)
        sl.set_product(item, pid, _label(cand) if cand else None)
        _update_notification(hass, data)

    async def forget_match(call: ServiceCall) -> None:
        if not _get_data(hass).shopping_list.forget(call.data[ATTR_KEY]):
            raise ServiceValidationError(f"Ingen husket kobling for '{call.data[ATTR_KEY]}'")

    async def search(call: ServiceCall) -> ServiceResponse:
        data = _get_data(hass)
        try:
            products = await data.client.search(call.data[ATTR_QUERY], take=call.data[ATTR_LIMIT])
        except _ERRORS as err:
            raise HomeAssistantError(f"Indkøb: {err}") from err
        return {"products": [p.to_dict() for p in products]}

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_BY_BARCODE, add_by_barcode,
        schema=ADD_BY_BARCODE_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_TO_NEMLIG, send_to_nemlig,
        schema=SEND_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_RESOLVE_ITEM, resolve_item, schema=RESOLVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FORGET_MATCH, forget_match, schema=FORGET_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, search,
        schema=SEARCH_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
