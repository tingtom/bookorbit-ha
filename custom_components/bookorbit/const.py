"""Constants for the BookOrbit integration."""

DOMAIN = "bookorbit"

API_PREFIX = "/api/v1"

# Default polling interval in minutes.
DEFAULT_SCAN_INTERVAL = 5

# Shown to BookOrbit as the device label of this API session.
AUTH_DEVICE_LABEL = "Home Assistant"

# Reuse an access token until it is this close to expiring.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

# Dashboard widgets requested in one batch call.
WIDGET_BATCH = ["reading-goal", "currently-reading", "library-overview"]
