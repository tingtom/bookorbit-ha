"""Tests for setting up the BookOrbit integration and its sensors."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bookorbit.api import (
    BookOrbitAuthError,
    BookOrbitCannotConnectError,
    BookOrbitStats,
)
from custom_components.bookorbit.const import DOMAIN

HOST = "http://192.168.1.50:3000"

ENTRY_DATA = {
    "host": HOST,
    "username": "reader",
    "password": "hunter2",
    "scan_interval": 5,
}

STATS = BookOrbitStats(
    tracked_books=96,
    started_books=60,
    in_progress_books=5,
    completed_books=44,
    mean_progress_percent=63.42,
    today_seconds=1860,       # 31 min
    week_seconds=12600,       # 210 min
    previous_week_seconds=9000,  # 150 min
    current_streak=12,
    longest_streak=31,
    completed_books_ytd=17,
    goal_books=24,
    goal_completed=17,
    goal_year=2026,
    goal_status="behind",
    goal_projected=21,
    library_books=412,
    library_authors=187,
    library_series=42,
    storage_bytes=5_368_709_120,
    books_added_year=23,
    current_book_title="Dune",
    current_book_authors=["Frank Herbert"],
    current_book_progress=42.5,
    current_books=[
        {"title": "Dune", "authors": ["Frank Herbert"], "progress": 42.5}
    ],
)


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


async def _setup_entry(hass: HomeAssistant, stats: BookOrbitStats = STATS) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=f"BookOrbit ({HOST})", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    with _patch_login(), _patch_stats(return_value=stats):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{HOST}-{key}")
    assert entity_id is not None, f"no entity registered for {key}"
    return entity_id


async def test_setup_creates_all_sensors(hass: HomeAssistant) -> None:
    """Setup succeeds and every sensor reports the fetched statistics."""
    entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    sensor_entries = [
        item
        for item in registry.entities.values()
        if item.config_entry_id == entry.entry_id
    ]
    assert len(sensor_entries) == 18

    # Entity ids are namespaced with the device name thanks to has_entity_name.
    assert _entity_id(hass, "today_reading") == "sensor.bookorbit_reading_today"
    assert _entity_id(hass, "currently_reading") == "sensor.bookorbit_currently_reading"

    # Activity sensors (minutes are derived from seconds).
    state = hass.states.get(_entity_id(hass, "today_reading"))
    assert state is not None and state.state == "31.0"
    assert hass.states.get(_entity_id(hass, "week_reading")).state == "210.0"
    assert hass.states.get(_entity_id(hass, "previous_week_reading")).state == "150.0"
    assert hass.states.get(_entity_id(hass, "current_streak")).state == "12"
    assert hass.states.get(_entity_id(hass, "longest_streak")).state == "31"

    # Reading status.
    assert hass.states.get(_entity_id(hass, "books_in_progress")).state == "5"
    assert hass.states.get(_entity_id(hass, "books_started")).state == "60"
    assert hass.states.get(_entity_id(hass, "books_completed")).state == "44"
    assert hass.states.get(_entity_id(hass, "books_completed_ytd")).state == "17"
    assert hass.states.get(_entity_id(hass, "mean_progress")).state == "63.42"

    # Goal.
    goal = hass.states.get(_entity_id(hass, "reading_goal"))
    assert goal.state == "24"
    assert goal.attributes["year"] == 2026
    assert goal.attributes["completed"] == 17
    assert goal.attributes["status"] == "behind"
    assert goal.attributes["projected"] == 21
    assert hass.states.get(_entity_id(hass, "reading_goal_progress")).state == "70.8"

    # Library.
    assert hass.states.get(_entity_id(hass, "library_books")).state == "412"
    assert hass.states.get(_entity_id(hass, "library_authors")).state == "187"
    assert hass.states.get(_entity_id(hass, "library_series")).state == "42"
    assert hass.states.get(_entity_id(hass, "library_storage")).state == "5368709120"
    assert hass.states.get(_entity_id(hass, "books_added_year")).state == "23"

    # Currently reading, with attributes.
    current = hass.states.get(_entity_id(hass, "currently_reading"))
    assert current.state == "Dune"
    assert current.attributes["authors"] == ["Frank Herbert"]
    assert current.attributes["progress"] == 42.5
    assert current.attributes["books_count"] == 1

    # All sensors belong to one BookOrbit device.
    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)
    devices = [
        device
        for device in device_registry.devices.values()
        if device.identifiers and next(iter(device.identifiers))[0] == DOMAIN
    ]
    assert len(devices) == 1
    assert devices[0].configuration_url == HOST


async def test_goal_without_goal_set_is_unknown(hass: HomeAssistant) -> None:
    """No yearly goal configured -> goal sensors are unknown, not zero."""
    stats = BookOrbitStats(goal_books=None, goal_completed=0, goal_year=2026)
    entry = await _setup_entry(hass, stats=stats)
    assert entry.state is ConfigEntryState.LOADED

    goal = hass.states.get(_entity_id(hass, "reading_goal"))
    assert goal.state == "unknown"
    progress = hass.states.get(_entity_id(hass, "reading_goal_progress"))
    assert progress.state == "unknown"


async def test_no_currently_reading_is_unknown(hass: HomeAssistant) -> None:
    """Nothing in progress -> currently reading is unknown, not empty string."""
    entry = await _setup_entry(hass, stats=BookOrbitStats())
    assert entry.state is ConfigEntryState.LOADED

    current = hass.states.get(_entity_id(hass, "currently_reading"))
    assert current.state == "unknown"


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Unloading removes the sensors again."""
    entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    with _patch_login(), _patch_stats(return_value=STATS):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Entities are either gone or marked unavailable after unload.
    state = hass.states.get(_entity_id(hass, "today_reading"))
    assert state is None or state.state == "unavailable"


async def test_auth_failure_during_setup_starts_reauth(hass: HomeAssistant) -> None:
    """If BookOrbit rejects the stored login, a reauth flow is started."""
    entry = MockConfigEntry(domain=DOMAIN, title=f"BookOrbit ({HOST})", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with _patch_login(side_effect=BookOrbitAuthError("rejected")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR

    reauth_flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == "reauth"
        and flow["context"].get("entry_id") == entry.entry_id
    ]
    assert len(reauth_flows) == 1


async def test_connect_failure_during_setup_schedules_retry(hass: HomeAssistant) -> None:
    """An unreachable server at setup time -> ConfigEntryNotReady (retry)."""
    entry = MockConfigEntry(domain=DOMAIN, title=f"BookOrbit ({HOST})", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with _patch_login(side_effect=BookOrbitCannotConnectError("down")):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
