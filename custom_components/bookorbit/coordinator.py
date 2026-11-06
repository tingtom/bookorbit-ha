"""Data update coordinator for BookOrbit."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BookOrbitAuthError,
    BookOrbitCannotConnectError,
    BookOrbitClient,
    BookOrbitStats,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class BookOrbitCoordinator(DataUpdateCoordinator[BookOrbitStats]):
    """Polls BookOrbit for reading and library statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: BookOrbitClient,
        scan_interval_minutes: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self.client = client

    async def _async_update_data(self) -> BookOrbitStats:
        try:
            return await self.client.async_fetch_stats()
        except BookOrbitAuthError as err:
            raise ConfigEntryAuthFailed(f"BookOrbit authentication failed: {err}") from err
        except BookOrbitCannotConnectError as err:
            raise UpdateFailed(f"Could not update BookOrbit statistics: {err}") from err
