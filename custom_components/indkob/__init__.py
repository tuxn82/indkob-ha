"""Indkøb: delt indkøbsliste i Home Assistant med nemlig.com som første butik (uofficiel)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiohttp

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CARD_BASE_URL, CARD_FILES, DOMAIN, VERSION
from .coordinator import NemligCoordinator
from .nemlig_api import NemligAuthError, NemligClient, NemligError
from .services import async_setup_services
from .shopping_list import ShoppingList

PLATFORMS = [Platform.TODO, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class IndkobData:
    entry: ConfigEntry
    client: NemligClient
    session: aiohttp.ClientSession
    coordinator: NemligCoordinator
    shopping_list: ShoppingList


type IndkobConfigEntry = ConfigEntry[IndkobData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    # Kortene serveres af integrationen og indlæses automatisk i frontend
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths([
        StaticPathConfig(f"{CARD_BASE_URL}/{name}", str(www / name), cache_headers=True)
        for name in CARD_FILES
    ])
    for name in CARD_FILES:
        add_extra_js_url(hass, f"{CARD_BASE_URL}/{name}?v={VERSION}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IndkobConfigEntry) -> bool:
    # Egen session = egen cookie-jar til nemlig
    session = async_create_clientsession(hass)
    client = NemligClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    try:
        await client.login()
    except NemligAuthError as err:
        raise ConfigEntryError(f"Login til nemlig fejlede: {err}") from err
    except (NemligError, aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Kunne ikke kontakte nemlig: {err}") from err

    coordinator = NemligCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    shopping_list = ShoppingList(hass, entry.entry_id)
    await shopping_list.async_load()

    entry.runtime_data = IndkobData(entry, client, session, coordinator, shopping_list)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IndkobConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
