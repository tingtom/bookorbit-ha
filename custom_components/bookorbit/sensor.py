"""Sensor platform for BookOrbit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BookOrbitStats
from .const import DOMAIN
from .coordinator import BookOrbitCoordinator


@dataclass(frozen=True, kw_only=True)
class BookOrbitSensorDescription(SensorEntityDescription):
    """Describes a BookOrbit sensor, including how to read its value."""

    value_fn: Callable[[BookOrbitStats], StateType]


def _minutes(seconds: int) -> float:
    return round(seconds / 60, 1)


def _goal_progress(stats: BookOrbitStats) -> float | None:
    if not stats.goal_books:
        return None
    return round(min(stats.goal_completed / stats.goal_books, 1) * 100, 1)


DESCRIPTIONS: tuple[BookOrbitSensorDescription, ...] = (
    # Reading activity
    BookOrbitSensorDescription(
        key="today_reading",
        name="Reading today",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:book-open-page-variant",
        value_fn=lambda s: _minutes(s.today_seconds),
    ),
    BookOrbitSensorDescription(
        key="week_reading",
        name="Reading last 7 days",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:book-open-page-variant",
        value_fn=lambda s: _minutes(s.week_seconds),
    ),
    BookOrbitSensorDescription(
        key="previous_week_reading",
        name="Reading previous 7 days",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:book-open-page-variant",
        value_fn=lambda s: _minutes(s.previous_week_seconds),
    ),
    BookOrbitSensorDescription(
        key="current_streak",
        name="Current reading streak",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda s: s.current_streak,
    ),
    BookOrbitSensorDescription(
        key="longest_streak",
        name="Longest reading streak",
        native_unit_of_measurement=UnitOfTime.DAYS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda s: s.longest_streak,
    ),
    # Reading status
    BookOrbitSensorDescription(
        key="books_in_progress",
        name="Books in progress",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:book-multiple",
        value_fn=lambda s: s.in_progress_books,
    ),
    BookOrbitSensorDescription(
        key="books_started",
        name="Books started",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:book-open",
        value_fn=lambda s: s.started_books,
    ),
    BookOrbitSensorDescription(
        key="books_completed",
        name="Books completed",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:book-check",
        value_fn=lambda s: s.completed_books,
    ),
    BookOrbitSensorDescription(
        key="books_completed_ytd",
        name="Books finished this year",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-check",
        value_fn=lambda s: s.completed_books_ytd,
    ),
    BookOrbitSensorDescription(
        key="mean_progress",
        name="Mean reading progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:chart-bell-curve",
        value_fn=lambda s: s.mean_progress_percent,
    ),
    # Reading goal
    BookOrbitSensorDescription(
        key="reading_goal",
        name="Reading goal",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:target",
        value_fn=lambda s: s.goal_books,
    ),
    BookOrbitSensorDescription(
        key="reading_goal_progress",
        name="Reading goal progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:target",
        value_fn=_goal_progress,
    ),
    # Library
    BookOrbitSensorDescription(
        key="library_books",
        name="Library books",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bookshelf",
        value_fn=lambda s: s.library_books,
    ),
    BookOrbitSensorDescription(
        key="library_authors",
        name="Library authors",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-edit",
        value_fn=lambda s: s.library_authors,
    ),
    BookOrbitSensorDescription(
        key="library_series",
        name="Library series",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:format-list-numbered",
        value_fn=lambda s: s.library_series,
    ),
    BookOrbitSensorDescription(
        key="library_storage",
        name="Library storage",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:harddisk",
        value_fn=lambda s: s.storage_bytes,
    ),
    BookOrbitSensorDescription(
        key="books_added_year",
        name="Books added this year",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:plus-box",
        value_fn=lambda s: s.books_added_year,
    ),
    # Currently reading (text sensor)
    BookOrbitSensorDescription(
        key="currently_reading",
        name="Currently reading",
        state_class=None,
        icon="mdi:book-open-variant",
        value_fn=lambda s: s.current_book_title,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BookOrbit sensors from a config entry."""
    coordinator: BookOrbitCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        BookOrbitSensor(coordinator, description) for description in DESCRIPTIONS
    )


class BookOrbitSensor(CoordinatorEntity[BookOrbitCoordinator], SensorEntity):
    """A sensor backed by the BookOrbit statistics coordinator."""

    entity_description: BookOrbitSensorDescription

    def __init__(
        self,
        coordinator: BookOrbitCoordinator,
        description: BookOrbitSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.client.host}-{description.key}"
        self._attr_name = description.name
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client.host)},
            name="BookOrbit",
            manufacturer="BookOrbit",
            model="Self-hosted reading platform",
            configuration_url=coordinator.client.host,
        )

    @property
    def native_value(self) -> StateType:
        """Return the sensor value from the last statistics snapshot."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for the goal and currently-reading sensors."""
        if self.coordinator.data is None:
            return None
        stats = self.coordinator.data

        if self.entity_description.key == "currently_reading":
            return {
                "authors": stats.current_book_authors,
                "progress": stats.current_book_progress,
                "books_count": len(stats.current_books),
                "books": stats.current_books,
            }

        if self.entity_description.key == "reading_goal":
            attributes: dict[str, Any] = {
                "year": stats.goal_year,
                "completed": stats.goal_completed,
                "status": stats.goal_status,
            }
            if stats.goal_projected is not None:
                attributes["projected"] = stats.goal_projected
            return attributes

        return None
