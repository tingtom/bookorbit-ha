# BookOrbit for Home Assistant

A [HACS](https://hacs.xyz) custom integration that brings your self-hosted
[BookOrbit](https://bookorbit.app) reading statistics into Home Assistant.

It polls your BookOrbit server and exposes reading and library stats as
sensors, grouped under a single `BookOrbit` device.

## Installation

### HACS (recommended)

1. HACS → **⋮** (menu) → **Custom repositories**
2. Repository: `https://github.com/tingtom/bookorbit-ha`, category **Integration**
3. Install **BookOrbit** and restart Home Assistant

### Manual

Copy `custom_components/bookorbit/` into the `custom_components/` folder of
your Home Assistant configuration directory and restart Home Assistant.

## Configuration

**Settings → Devices & services → + Add integration → BookOrbit**

| Field | Description |
|---|---|
| Host URL | The address you open in a browser, e.g. `http://192.168.1.50:3000` |
| Username | Your BookOrbit username (not the email address) |
| Password | Your BookOrbit password |
| Scan interval | Poll interval in minutes (default: 5) |

> **Note:** the account must be able to log in with username/password.
> OIDC-only accounts (Authentik/Keycloak without local passwords) cannot be
> used, because the integration authenticates through BookOrbit's login API.

## Sensors

### Reading activity

| Sensor | Unit | Description |
|---|---|---|
| Reading today | min | Minutes read/listened today |
| Reading last 7 days | min | Minutes in the last 7 days |
| Reading previous 7 days | min | Minutes in the 7 days before that |
| Current reading streak | d | Consecutive days with reading activity |
| Longest reading streak | d | Your all-time best streak |

### Reading status

| Sensor | Description |
|---|---|
| Books in progress | Books with status reading/on hold/rereading |
| Books started | Books you have begun (any non-unread status) |
| Books completed | Books with status *read* |
| Books finished this year | Completions in the current year |
| Mean reading progress | Average progress across tracked books (%) |

### Reading goal

| Sensor | Description |
|---|---|
| Reading goal | Your yearly book goal (unknown if none is set) |
| Reading goal progress | Progress towards the goal (%) |

The goal sensor has attributes for `year`, `completed`, `status`
(`ahead` / `on_pace` / `behind`) and `projected`.

### Library

| Sensor | Unit | Description |
|---|---|---|
| Library books | — | Total books in the library |
| Library authors | — | Distinct authors |
| Library series | — | Distinct series |
| Library storage | bytes | Total size on disk (shown as GB/TB) |
| Books added this year | — | Books imported this year |

### Currently reading

| Sensor | Description |
|---|---|
| Currently reading | Title of the book you are currently reading |

Attributes: `authors`, `progress` (%), `books_count` and the full `books`
list when more than one book is in progress. The state is *unknown* when
nothing is in progress.

## Automations & dashboards

Example: notify when a reading streak is extended:

```yaml
automation:
  - alias: "BookOrbit streak milestone"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bookorbit_current_reading_streak
        above: 30
    action:
      - service: notify.mobile_app
        data:
          message: "BookOrbit: {{ trigger.to_state.state }} day reading streak!"
```

## How it works

* Authenticates with `POST /api/v1/auth/login` using the *native* client flow,
  which returns a refresh token in the body, and silently refreshes the
  access token (15 min TTL) between polls.
* Fetches statistics with three requests per poll:
  `POST /dashboard/widgets/batch`, `GET /user-statistics/summary` and
  `GET /user-statistics/activity-overview`.
* Polls locally over your network — no cloud involved.

## Caveats

* BookOrbit's API is **not** a stable public interface (their README says
  so). This integration is pinned to the API shape of BookOrbit **v3.x** and
  may need updates when BookOrbit changes its endpoints.
* Requires BookOrbit reachable over HTTP(S) from Home Assistant.
* Credentials are stored in Home Assistant's config entry file
  (`.storage/core.config_entries`), as is standard for integrations.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check custom_components tests conftest.py
.venv/bin/pytest -q
```

The test suite covers the API client against a fake BookOrbit server
(login/refresh/401 handling, response parsing), the config flow
(validation errors, duplicates, re-auth) and sensor setup
(all 18 entities, attributes, unload, failure paths).

## License

MIT
