"""The BookOrbit integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BookOrbitAuthError, BookOrbitCannotConnectError, BookOrbitClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import BookOrbitCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BookOrbit from a config entry."""
    client = BookOrbitClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await client.async_login()
    except BookOrbitAuthError as err:
        raise ConfigEntryAuthFailed(f"BookOrbit rejected the configured login: {err}") from err
    except BookOrbitCannotConnectError as err:
        raise ConfigEntryNotReady(f"Cannot reach BookOrbit at {entry.data[CONF_HOST]}: {err}") from err

    coordinator = BookOrbitCoordinator(
        hass,
        client,
        scan_interval_minutes=entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
