"""Config flow for the BookOrbit integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BookOrbitAuthError, BookOrbitCannotConnectError, BookOrbitClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1440)
        ),
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


def _normalize_host(host: str) -> str:
    """Add a scheme if the user left it out and strip trailing slashes."""
    host = host.strip()
    if not host:
        return host
    if "://" not in host:
        host = f"http://{host}"
    return host.rstrip("/")


async def _validate_connection(
    hass: Any, host: str, username: str, password: str
) -> BookOrbitClient:
    """Log in and fetch one round of stats, raising on failure."""
    client = BookOrbitClient(async_get_clientsession(hass), host, username, password)
    await client.async_login()
    await client.async_fetch_stats()
    return client


class BookOrbitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the BookOrbit config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for connection details and validate them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalize_host(user_input["host"])
            try:
                await _validate_connection(
                    self.hass, host, user_input["username"], user_input["password"]
                )
            except BookOrbitAuthError:
                errors["base"] = "invalid_auth"
            except BookOrbitCannotConnectError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating BookOrbit connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()
                data = {
                    **user_input,
                    "host": host,
                }
                return self.async_create_entry(
                    title=f"BookOrbit ({urlparse(host).netloc or host})",
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start re-authentication when stored credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate new credentials for an existing entry."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None and entry is not None:
            host = entry.data["host"]
            try:
                await _validate_connection(
                    self.hass, host, user_input["username"], user_input["password"]
                )
            except BookOrbitAuthError:
                errors["base"] = "invalid_auth"
            except BookOrbitCannotConnectError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error re-validating BookOrbit connection")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, **user_input},
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                REAUTH_SCHEMA, user_input or entry.data if entry else user_input
            ),
            errors=errors,
            description_placeholders=(
                {"host": entry.data["host"]} if entry is not None else {}
            ),
        )
