"""Tests for the CA4 humidifier setup with the update grace period."""

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from miio import DeviceException
from miio.integrations.humidifier.zhimi.airhumidifier_miot import OperationMode
from miio.miioprotocol import MiIOProtocol
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.xiaomi_miio import UPDATE_INTERVAL, miio_patch, resilience
from custom_components.xiaomi_miio.const import (
    CONF_FLOW_TYPE,
    DOMAIN,
    MODEL_AIRHUMIDIFIER_CA4,
)
from homeassistant.const import (
    CONF_DEVICE,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_TOKEN,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

ENTITY_ID = "humidifier.test_ca4"
DISCOVERY_FAILURE = DeviceException("Unable to discover the device ca4.invalid")


@pytest.fixture
def mock_ca4(monkeypatch: pytest.MonkeyPatch) -> Generator[MagicMock]:
    """Mock the CA4 device and limit setup to the humidifier platform."""
    monkeypatch.setattr(resilience, "DISCOVERY_RETRY_DELAY_SEC", 0)
    device = MagicMock()
    device.ip = "ca4.invalid"
    device.status.return_value = SimpleNamespace(
        is_on=True, mode=OperationMode.Auto, target_humidity=50, humidity=40
    )
    with (
        patch(
            "custom_components.xiaomi_miio.get_platforms",
            return_value=[Platform.HUMIDIFIER],
        ),
        patch("custom_components.xiaomi_miio.AirHumidifierMiot", return_value=device),
    ):
        yield device


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123456",
        title="test_ca4",
        data={
            CONF_FLOW_TYPE: CONF_DEVICE,
            CONF_HOST: "ca4.invalid",
            CONF_TOKEN: "12345678901234567890123456789012",
            CONF_MODEL: MODEL_AIRHUMIDIFIER_CA4,
            CONF_MAC: "ab:cd:ef:gh:ij:kl",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_installs_protocol_patch(
    hass: HomeAssistant, mock_ca4: MagicMock
) -> None:
    """Setting up the integration installs the miIO patch."""
    await _setup(hass)

    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert getattr(MiIOProtocol.send, miio_patch._PATCH_MARKER, False)


async def test_single_discovery_failure_is_invisible(
    hass: HomeAssistant, mock_ca4: MagicMock
) -> None:
    """A discovery failure that succeeds on retry keeps the entity available."""
    await _setup(hass)
    good = mock_ca4.status.return_value
    mock_ca4.status.side_effect = [DISCOVERY_FAILURE, good]

    async_fire_time_changed(hass, dt_util.utcnow() + UPDATE_INTERVAL)
    await hass.async_block_till_done()

    assert mock_ca4.status.call_count == 3
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_unavailable_after_three_failed_cycles(
    hass: HomeAssistant, mock_ca4: MagicMock
) -> None:
    """The entity keeps its state for two failed cycles, then goes unavailable."""
    await _setup(hass)
    mock_ca4.status.side_effect = DISCOVERY_FAILURE
    now = dt_util.utcnow()

    for cycle in (1, 2):
        now += UPDATE_INTERVAL
        async_fire_time_changed(hass, now)
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY_ID).state == STATE_ON, cycle

    now += UPDATE_INTERVAL
    async_fire_time_changed(hass, now)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    mock_ca4.status.side_effect = None
    now += UPDATE_INTERVAL
    async_fire_time_changed(hass, now)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON
