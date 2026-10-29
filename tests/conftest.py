"""Fixtures for the xiaomi_miio CA4 fix tests."""

from collections.abc import Generator
from unittest.mock import patch

from miio.miioprotocol import MiIOProtocol
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Load the integration from custom_components instead of core."""


@pytest.fixture(autouse=True)
def restore_miio_send() -> Generator[None]:
    """Undo the process-wide MiIOProtocol.send patch after each test."""
    with patch.object(MiIOProtocol, "send", MiIOProtocol.send):
        yield
