"""Shared test fixtures for the BookOrbit integration tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow this repository's custom integration to be loaded in tests."""
    yield
