"""Core tests run without Home Assistant."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """Override the HA fixture, the engine needs no hass."""
    return
