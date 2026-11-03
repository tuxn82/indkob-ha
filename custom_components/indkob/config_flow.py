"""Config flow: login med nemlig.com-konto."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .nemlig_api import NemligAuthError, NemligClient, NemligError
from .const import CONF_AUTO_PICK, DEFAULT_AUTO_PICK, DOMAIN

SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


class IndkobConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IndkobOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            client = NemligClient(
                async_create_clientsession(self.hass), username, user_input[CONF_PASSWORD]
            )
            try:
                await client.login()
            except NemligAuthError:
                errors["base"] = "invalid_auth"
            except (NemligError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"nemlig: {username}",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)


class IndkobOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_AUTO_PICK, DEFAULT_AUTO_PICK)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_AUTO_PICK, default=current): bool}),
        )
