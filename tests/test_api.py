"""Functional test for the BookOrbit HA integration API client (no HA needed)."""

"""Tests for the BookOrbit API client (runs against a fake BookOrbit server)."""

import asyncio
import importlib
import sys
import types
from datetime import UTC, datetime, timedelta

# Load api.py as part of a stub package: the real package __init__ imports
# homeassistant, which is not installed in this test environment.
_PKG = types.ModuleType("bookorbit")
_PKG.__path__ = ["/root/projects/bookorbit-ha/custom_components/bookorbit"]
sys.modules["bookorbit"] = _PKG
bookorbit_api = importlib.import_module("bookorbit.api")

import aiohttp
from aiohttp import web

BookOrbitAuthError = bookorbit_api.BookOrbitAuthError
BookOrbitCannotConnectError = bookorbit_api.BookOrbitCannotConnectError
BookOrbitClient = bookorbit_api.BookOrbitClient
BookOrbitStats = bookorbit_api.BookOrbitStats

# Realistic payloads shaped like the BookOrbit v3 API.
WIDGETS = {
    "items": [
        {
            "type": "reading-goal",
            "data": {"goalBooks": 24, "completedBooks": 17, "year": 2026},
            "failed": False,
        },
        {
            "type": "currently-reading",
            "data": {
                "books": [
                    {
                        "bookId": 1,
                        "title": "Dune",
                        "authors": ["Frank Herbert"],
                        "progress": 42.5,
                        "hasCover": True,
                        "fileId": 10,
                        "fileFormat": "epub",
                        "readFileId": 10,
                        "readFileFormat": "epub",
                        "readAlongFileId": None,
                        "hasAudio": False,
                    },
                    {
                        "bookId": 2,
                        "title": "Neuromancer",
                        "authors": ["William Gibson"],
                        "progress": 10.0,
                        "hasCover": True,
                        "fileId": 11,
                        "fileFormat": "epub",
                        "readFileId": 11,
                        "readFileFormat": "epub",
                        "readAlongFileId": None,
                        "hasAudio": False,
                    },
                ]
            },
            "failed": False,
        },
        {
            "type": "library-overview",
            "data": {
                "totalBooks": 412,
                "totalAuthors": 187,
                "totalSeries": 42,
                "totalStorageBytes": 5_368_709_120,
                "booksAddedThisYear": 23,
            },
            "failed": False,
        },
    ]
}

USER_SUMMARY = {
    "trackedBooks": 96,
    "startedBooks": 60,
    "inProgressBooks": 5,
    "completedBooks": 44,
    "meanProgressPercent": 63.42,
}

ACTIVITY = {
    "generatedAt": "2026-11-06T12:00:00.000Z",
    "timezone": "Europe/London",
    "libraryIds": [],
    "achievementsEnabled": True,
    "snapshot": {
        "today": {"totalSeconds": 1860, "readingSeconds": 1500, "listeningSeconds": 360},
        "lastSevenDays": {"totalSeconds": 12600, "readingSeconds": 9000, "listeningSeconds": 3600},
        "previousSevenDays": {"totalSeconds": 9000, "readingSeconds": 9000, "listeningSeconds": 0},
        "currentStreak": 12,
        "longestStreak": 31,
        "completedBooksYtd": 17,
    },
    "goal": {
        "year": 2026,
        "goalBooks": 24,
        "completedBooks": 17,
        "projectedBooks": 21,
        "status": "behind",
        "points": [],
    },
}


class FakeBookOrbit:
    """Simulates the BookOrbit auth + stats endpoints.

    Like real BookOrbit, already-issued access tokens keep working until they
    expire (JWTs are stateless), and any issued refresh token can be rotated.
    """

    def __init__(self, fail_first_access_with_401=False, break_login=False):
        self.logins = 0
        self.refreshes = 0
        self.fail_first_access_with_401 = fail_first_access_with_401
        self.break_login = break_login
        self.valid_access_tokens = set()
        self.valid_refresh_tokens = set()
        self._consumed_401 = False
        self._token_seq = 0

    def _new_access_token(self):
        self._token_seq += 1
        token = f"access-{self._token_seq}"
        self.valid_access_tokens.add(token)
        return token

    async def login(self, request):
        self.logins += 1
        if self.break_login:
            return web.Response(status=500, text="boom")
        body = await request.json()
        assert body["clientKind"] == "native", body
        assert body["username"] == "reader" and body["password"] == "hunter2", body
        refresh = "r" * 63 + str(len(self.valid_refresh_tokens))
        self.valid_refresh_tokens.add(refresh)
        return web.json_response(
            {
                "accessToken": self._new_access_token(),
                "accessTokenExpiresAt": (
                    datetime.now(UTC) + timedelta(minutes=15)
                ).isoformat(),
                "refreshToken": refresh,
                "refreshTokenExpiresAt": (
                    datetime.now(UTC) + timedelta(days=30)
                ).isoformat(),
                "sessionId": 7,
            }
        )

    async def refresh(self, request):
        self.refreshes += 1
        body = await request.json()
        assert body["refreshToken"] in self.valid_refresh_tokens, body
        # Token rotation: the presented refresh token is retired.
        self.valid_refresh_tokens.discard(body["refreshToken"])
        refresh = "r" * 63 + str(len(self.valid_refresh_tokens))
        self.valid_refresh_tokens.add(refresh)
        return web.json_response(
            {
                "accessToken": self._new_access_token(),
                "accessTokenExpiresAt": (
                    datetime.now(UTC) + timedelta(minutes=15)
                ).isoformat(),
                "refreshToken": refresh,
                "refreshTokenExpiresAt": (
                    datetime.now(UTC) + timedelta(days=30)
                ).isoformat(),
                "sessionId": 7,
            }
        )

    async def stats(self, request):
        if self.fail_first_access_with_401 and not self._consumed_401:
            self._consumed_401 = True
            return web.Response(status=401, text="expired")
        auth = request.headers.get("Authorization", "")
        if auth.removeprefix("Bearer ") not in self.valid_access_tokens:
            return web.Response(status=401, text="bad token")
        if request.path.endswith("/summary"):
            return web.json_response(USER_SUMMARY)
        if request.path.endswith("/activity-overview"):
            return web.json_response(ACTIVITY)
        return web.json_response(WIDGETS)


def make_app(fake):
    app = web.Application()
    app.router.add_post("/api/v1/auth/login", fake.login)
    app.router.add_post("/api/v1/auth/refresh", fake.refresh)
    app.router.add_post("/api/v1/dashboard/widgets/batch", fake.stats)
    app.router.add_get("/api/v1/user-statistics/summary", fake.stats)
    app.router.add_get("/api/v1/user-statistics/activity-overview", fake.stats)
    return app


async def run_case(name, fake, expect_fail=False, expect_refreshes=None):
    runner = web.AppRunner(make_app(fake))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        async with aiohttp.ClientSession() as session:
            client = BookOrbitClient(
                session, f"http://127.0.0.1:{port}", "reader", "hunter2"
            )
            if expect_fail:
                try:
                    await client.async_fetch_stats()
                except (BookOrbitAuthError, BookOrbitCannotConnectError) as err:
                    print(f"[{name}] OK, raised {type(err).__name__}: {str(err)[:80]}")
                    return
                raise AssertionError(f"[{name}] expected failure, got success")

            stats = await client.async_fetch_stats()
            assert isinstance(stats, BookOrbitStats)
            # Spot-check every data source.
            assert stats.in_progress_books == 5, stats
            assert stats.mean_progress_percent == 63.42, stats
            assert stats.today_seconds == 1860
            assert stats.week_seconds == 12600
            assert stats.previous_week_seconds == 9000
            assert stats.current_streak == 12 and stats.longest_streak == 31
            assert stats.completed_books_ytd == 17
            assert stats.goal_books == 24 and stats.goal_status == "behind"
            assert stats.goal_projected == 21 and stats.goal_year == 2026
            assert stats.library_books == 412
            assert stats.storage_bytes == 5_368_709_120
            assert stats.books_added_year == 23
            assert stats.current_book_title == "Dune"
            assert stats.current_book_authors == ["Frank Herbert"]
            assert stats.current_book_progress == 42.5
            assert len(stats.current_books) == 2
            if expect_refreshes is not None:
                assert fake.refreshes == expect_refreshes, (
                    f"expected {expect_refreshes} refreshes, got {fake.refreshes}"
                )

            # Second fetch should reuse the token (no extra login/refresh).
            logins_before, refreshes_before = fake.logins, fake.refreshes
            await client.async_fetch_stats()
            assert fake.logins == logins_before, "unexpected re-login"
            assert fake.refreshes == refreshes_before, "unexpected refresh"
            print(f"[{name}] OK ({fake.logins} login, {fake.refreshes} refresh)")
    finally:
        await runner.cleanup()


async def _main():
    # Case 1: happy path.
    await run_case("happy path", FakeBookOrbit())

    # Case 2: expired access token -> 401 -> silent refresh -> retry.
    # Exactly one refresh must happen for the whole parallel burst.
    await run_case(
        "401 then refresh",
        FakeBookOrbit(fail_first_access_with_401=True),
        expect_refreshes=1,
    )

    # Case 3: server down / 500 on login.
    await run_case("login 500", FakeBookOrbit(break_login=True), expect_fail=True)

    print("ALL TESTS PASSED")



def test_client(socket_enabled):
    """Run the full client scenario suite."""
    asyncio.run(_main())


def test_parse_datetime_formats():
    """BookOrbit sends JS-style ISO timestamps; all variants must parse."""

    # Z-suffixed (JavaScript toISOString) - the format the real API returns.
    z_parsed = bookorbit_api._parse_datetime("2026-11-06T12:00:00.000Z")
    assert z_parsed is not None
    assert z_parsed.utcoffset() is not None

    # Explicit offset and naive variants.
    assert bookorbit_api._parse_datetime("2026-11-06T12:00:00+00:00") is not None
    naive = bookorbit_api._parse_datetime("2026-11-06T12:00:00")
    assert naive is not None and naive.tzinfo == UTC

    # Garbage and non-strings must not blow up the parser.
    assert bookorbit_api._parse_datetime("not-a-date") is None
    assert bookorbit_api._parse_datetime(None) is None
    assert bookorbit_api._parse_datetime(12345) is None
