"""Asynchronous API client for BookOrbit.

BookOrbit's HTTP API is not a formally stable integration surface (see its
README), so this client follows the same contract as the official apps:

* ``POST /api/v1/auth/login`` with ``clientKind: "native"`` returns the
  refresh token in the response body (the web flow only gets cookies).
* ``POST /api/v1/auth/refresh`` rotates a native refresh token.
* Everything else uses ``Authorization: Bearer <accessToken>``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    API_PREFIX,
    AUTH_DEVICE_LABEL,
    TOKEN_EXPIRY_MARGIN_SECONDS,
    WIDGET_BATCH,
)

_LOGGER = logging.getLogger(__name__)

AUTH_TIMEOUT = aiohttp.ClientTimeout(total=20)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class BookOrbitAuthError(Exception):
    """Raised when BookOrbit rejects our credentials or tokens."""


class BookOrbitCannotConnectError(Exception):
    """Raised when the BookOrbit server cannot be reached or errors out."""


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(slots=True)
class BookOrbitStats:
    """Snapshot of the BookOrbit numbers exposed to Home Assistant."""

    # User statistics summary
    tracked_books: int = 0
    started_books: int = 0
    in_progress_books: int = 0
    completed_books: int = 0
    mean_progress_percent: float = 0.0

    # Activity overview
    today_seconds: int = 0
    week_seconds: int = 0
    previous_week_seconds: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    completed_books_ytd: int = 0
    goal_books: int | None = None
    goal_completed: int = 0
    goal_year: int | None = None
    goal_status: str | None = None
    goal_projected: int | None = None

    # Library overview widget
    library_books: int = 0
    library_authors: int = 0
    library_series: int = 0
    storage_bytes: int = 0
    books_added_year: int = 0

    # Currently reading widget
    current_book_title: str | None = None
    current_book_authors: list[str] = field(default_factory=list)
    current_book_progress: float | None = None
    current_books: list[dict[str, Any]] = field(default_factory=list)


class BookOrbitClient:
    """Thin async client for a single BookOrbit user account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self.host = host.rstrip("/")
        self._username = username
        self._password = password

        self._access_token: str | None = None
        self._access_expires_at: datetime | None = None
        self._refresh_token: str | None = None
        self._refresh_expires_at: datetime | None = None
        self._token_lock = asyncio.Lock()

    @property
    def _api(self) -> str:
        return f"{self.host}{API_PREFIX}"

    # ------------------------------------------------------------------ auth

    def _clear_tokens(self) -> None:
        self._access_token = None
        self._access_expires_at = None
        self._refresh_token = None
        self._refresh_expires_at = None

    def _access_valid(self) -> bool:
        if not self._access_token:
            return False
        if self._access_expires_at is None:
            # No expiry reported: trust it until the server says 401.
            return True
        now = datetime.now(UTC)
        return now < self._access_expires_at - timedelta(seconds=TOKEN_EXPIRY_MARGIN_SECONDS)

    def _refresh_usable(self) -> bool:
        if not self._refresh_token:
            return False
        if self._refresh_expires_at is None:
            return True
        return datetime.now(UTC) < self._refresh_expires_at

    async def async_login(self) -> None:
        """Authenticate from scratch (also used as a fallback for refresh)."""
        await self._async_ensure_token(force=True)

    async def _async_ensure_token(
        self, *, force: bool = False, failed_token: str | None = None
    ) -> None:
        """Make sure a usable access token is present, refreshing as needed.

        ``failed_token`` is the token that just received a 401: if a sibling
        request already rotated it, no second refresh is performed.
        """
        async with self._token_lock:
            if failed_token is not None and self._access_token not in (None, failed_token):
                # Someone else already replaced the rejected token.
                return
            if not force and self._access_valid():
                return
            if self._refresh_usable():
                try:
                    await self._async_request_tokens(
                        "/auth/refresh", {"refreshToken": self._refresh_token}
                    )
                    return
                except BookOrbitAuthError:
                    _LOGGER.debug("BookOrbit refresh token rejected, falling back to login")
                    self._clear_tokens()
            await self._async_request_tokens(
                "/auth/login",
                {
                    "username": self._username,
                    "password": self._password,
                    "clientKind": "native",
                    "deviceLabel": AUTH_DEVICE_LABEL,
                },
            )

    async def _async_request_tokens(self, path: str, payload: dict[str, Any]) -> None:
        try:
            async with self._session.post(
                f"{self._api}{path}", json=payload, timeout=AUTH_TIMEOUT
            ) as resp:
                if resp.status in (400, 401, 403):
                    body = await resp.text()
                    raise BookOrbitAuthError(
                        f"BookOrbit rejected {path} ({resp.status}): {body[:200]}"
                    )
                if resp.status >= 400:
                    raise BookOrbitCannotConnectError(
                        f"BookOrbit {path} returned HTTP {resp.status}"
                    )
                data = await resp.json()
        except BookOrbitAuthError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise BookOrbitCannotConnectError(f"BookOrbit {path} failed: {err}") from err

        access_token = data.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise BookOrbitAuthError(f"BookOrbit {path} returned no access token")

        self._access_token = access_token
        self._access_expires_at = _parse_datetime(data.get("accessTokenExpiresAt"))

        refresh_token = data.get("refreshToken")
        if isinstance(refresh_token, str) and refresh_token:
            self._refresh_token = refresh_token
            self._refresh_expires_at = _parse_datetime(data.get("refreshTokenExpiresAt"))

    # --------------------------------------------------------------- requests

    async def _async_request(self, method: str, path: str, *, json: Any = None) -> Any:
        """Perform an authenticated request, re-authenticating once on 401."""
        await self._async_ensure_token()
        url = f"{self._api}{path}"

        for attempt in range(2):
            headers = {}
            used_token = self._access_token
            if used_token:
                headers["Authorization"] = f"Bearer {used_token}"
            try:
                async with self._session.request(
                    method, url, json=json, headers=headers, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status == 401:
                        if attempt == 0:
                            _LOGGER.debug("BookOrbit returned 401 for %s, re-authenticating", path)
                            await self._async_ensure_token(force=True, failed_token=used_token)
                            continue
                        raise BookOrbitAuthError(f"BookOrbit still rejects us on {path} (401)")
                    if resp.status >= 400:
                        body = await resp.text()
                        raise BookOrbitCannotConnectError(
                            f"{method} {path} -> HTTP {resp.status}: {body[:200]}"
                        )
                    return await resp.json()
            except BookOrbitAuthError:
                raise
            except (TimeoutError, aiohttp.ClientError) as err:
                raise BookOrbitCannotConnectError(f"{method} {path} failed: {err}") from err

        raise BookOrbitCannotConnectError(f"{method} {path} failed after retry")

    # ------------------------------------------------------------------ stats

    async def async_fetch_stats(self) -> BookOrbitStats:
        """Fetch all stats in three requests (one of them batched)."""
        widgets_resp, summary_resp, activity_resp = await asyncio.gather(
            self._async_request(
                "POST", "/dashboard/widgets/batch", json={"widgets": WIDGET_BATCH}
            ),
            self._async_request("GET", "/user-statistics/summary"),
            self._async_request("GET", "/user-statistics/activity-overview"),
        )
        return self._parse_stats(widgets_resp, summary_resp, activity_resp)

    @staticmethod
    def _parse_stats(
        widgets_resp: Any, summary_resp: Any, activity_resp: Any
    ) -> BookOrbitStats:
        widgets: dict[str, Any] = {}
        for item in _as_dict(widgets_resp).get("items") or []:
            item_dict = _as_dict(item)
            if item_dict.get("failed") or not item_dict.get("data"):
                continue
            widgets[str(item_dict.get("type"))] = _as_dict(item_dict["data"])

        summary = _as_dict(summary_resp)
        snapshot = _as_dict(_as_dict(activity_resp).get("snapshot"))
        activity_goal = _as_dict(_as_dict(activity_resp).get("goal"))
        goal_widget = _as_dict(widgets.get("reading-goal"))
        library = _as_dict(widgets.get("library-overview"))
        currently_reading = _as_dict(widgets.get("currently-reading"))

        goal_books = activity_goal.get("goalBooks")
        if goal_books is None:
            goal_books = goal_widget.get("goalBooks")

        books: list[dict[str, Any]] = [
            book for book in (currently_reading.get("books") or []) if isinstance(book, dict)
        ]
        first_book = books[0] if books else None

        stats = BookOrbitStats(
            tracked_books=_as_int(summary.get("trackedBooks")),
            started_books=_as_int(summary.get("startedBooks")),
            in_progress_books=_as_int(summary.get("inProgressBooks")),
            completed_books=_as_int(summary.get("completedBooks")),
            mean_progress_percent=_as_float(summary.get("meanProgressPercent")),
            today_seconds=_as_int(_as_dict(snapshot.get("today")).get("totalSeconds")),
            week_seconds=_as_int(_as_dict(snapshot.get("lastSevenDays")).get("totalSeconds")),
            previous_week_seconds=_as_int(
                _as_dict(snapshot.get("previousSevenDays")).get("totalSeconds")
            ),
            current_streak=_as_int(snapshot.get("currentStreak")),
            longest_streak=_as_int(snapshot.get("longestStreak")),
            completed_books_ytd=_as_int(snapshot.get("completedBooksYtd")),
            goal_books=_as_int(goal_books) if goal_books is not None else None,
            goal_completed=_as_int(
                activity_goal.get("completedBooks"), _as_int(goal_widget.get("completedBooks"))
            ),
            goal_year=(
                _as_int(activity_goal.get("year"), _as_int(goal_widget.get("year")))
                or None
            ),
            goal_status=activity_goal.get("status"),
            goal_projected=(
                _as_int(activity_goal.get("projectedBooks"))
                if activity_goal.get("projectedBooks") is not None
                else None
            ),
            library_books=_as_int(library.get("totalBooks")),
            library_authors=_as_int(library.get("totalAuthors")),
            library_series=_as_int(library.get("totalSeries")),
            storage_bytes=_as_int(library.get("totalStorageBytes")),
            books_added_year=_as_int(library.get("booksAddedThisYear")),
            current_book_title=first_book.get("title") if first_book else None,
            current_book_authors=list(first_book.get("authors") or []) if first_book else [],
            current_book_progress=(
                _as_float(first_book.get("progress")) if first_book else None
            ),
            current_books=[
                {
                    "title": book.get("title"),
                    "authors": book.get("authors") or [],
                    "progress": book.get("progress"),
                }
                for book in books
            ],
        )
        return stats
