"""Tests for the BookOrbit config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.bookorbit.api import (
    BookOrbitAuthError,
    BookOrbitCannotConnectError,
    BookOrbitStats,
)
from custom_components.bookorbit.const import DOMAIN

HOST = "http://192.168.1.50:3000"


def _patch_login(side_effect=None):
    return patch(
        "custom_components.bookorbit.api.BookOrbitClient.async_login",
        new_callable=AsyncMock,
        side_effect=side_effect,
    )


def _patch_stats(return_value=None, side_effect=None):
    return patch(
        "custom_components.bookorbit.api.BookOrbitClient.async_fetch_stats",
        new_callable=AsyncMock,
        return_value=return_value,
        side_effect=side_effect,
    )


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test the full user step: valid credentials create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with _patch_login(), _patch_stats(return_value=BookOrbitStats()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "hunter2"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "BookOrbit (192.168.1.50:3000)"
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_USERNAME] == "reader"
    assert result["data"]["scan_interval"] == 5


async def test_user_flow_normalizes_host(hass: HomeAssistant) -> None:
    """A host without a scheme gets http:// prepended."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with _patch_login(), _patch_stats(return_value=BookOrbitStats()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.1.50:3000/",
                CONF_USERNAME: "reader",
                CONF_PASSWORD: "hunter2",
                "scan_interval": 10,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "http://192.168.1.50:3000"
    assert result["data"]["scan_interval"] == 10


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Bad credentials are reported as invalid_auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with _patch_login(side_effect=BookOrbitAuthError("rejected")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Server unreachable is reported as cannot_connect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with _patch_login(side_effect=BookOrbitCannotConnectError("down")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "hunter2"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """Unexpected exceptions are reported as unknown, not a crash."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with _patch_login(side_effect=ValueError("boom")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "hunter2"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_host_is_rejected(hass: HomeAssistant) -> None:
    """The same server can only be configured once."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOST.lower(),
        data={CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "hunter2"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with _patch_login(), _patch_stats(return_value=BookOrbitStats()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: HOST, CONF_USERNAME: "reader", CONF_PASSWORD: "hunter2"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(hass: HomeAssistant) -> None:
    """Re-authentication replaces stored credentials and reloads the entry."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOST.lower(),
        data={
            CONF_HOST: HOST,
            CONF_USERNAME: "reader",
            CONF_PASSWORD: "old-password",
            "scan_interval": 5,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with _patch_login(), _patch_stats(return_value=BookOrbitStats()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "reader", CONF_PASSWORD: "new-password"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
