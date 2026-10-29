"""Tests for the discovery retry and update grace period."""

from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from construct.core import ConstError
from miio import DeviceException
import pytest

from custom_components.xiaomi_miio import resilience
from homeassistant.helpers.update_coordinator import UpdateFailed

DEVICE = SimpleNamespace(ip="ca4.invalid")


def _update_failed(message: str) -> UpdateFailed:
    """Build UpdateFailed the way _async_update_data_default raises it."""
    try:
        raise UpdateFailed(message) from DeviceException(message)
    except UpdateFailed as err:
        return err


DISCOVERY_FAILURE = "Unable to discover the device ca4.invalid"


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real discovery retry delay."""
    monkeypatch.setattr(resilience, "DISCOVERY_RETRY_DELAY_SEC", 0)


def _wrap(update: AsyncMock) -> Callable[[], Coroutine[Any, Any, Any]]:
    return resilience.with_update_grace(update, DEVICE)


async def test_success_passes_state_through() -> None:
    """A successful update returns the device state."""
    update = AsyncMock(return_value="state")

    assert await _wrap(update)() == "state"
    assert update.await_count == 1


async def test_discovery_failure_retried_once() -> None:
    """A discovery failure is retried and does not count as a failure."""
    update = AsyncMock(
        side_effect=[
            "first",
            _update_failed(DISCOVERY_FAILURE),
            "second",
            UpdateFailed("other"),
        ]
    )
    wrapped = _wrap(update)

    assert await wrapped() == "first"
    assert await wrapped() == "second"
    # The next failure is the first one in the grace period.
    assert await wrapped() == "second"
    assert update.await_count == 4


async def test_other_failures_not_retried_immediately() -> None:
    """Only discovery failures get the immediate retry."""
    update = AsyncMock(side_effect=["state", _update_failed("No response")])
    wrapped = _wrap(update)

    await wrapped()
    assert await wrapped() == "state"
    assert update.await_count == 2


async def test_grace_then_unavailable() -> None:
    """Two failures keep the last state, the third raises UpdateFailed."""
    failure = _update_failed(DISCOVERY_FAILURE)
    update = AsyncMock(side_effect=["good"] + [failure] * 6)
    wrapped = _wrap(update)

    assert await wrapped() == "good"
    assert await wrapped() == "good"
    assert await wrapped() == "good"
    with pytest.raises(UpdateFailed):
        await wrapped()
    # Each failed cycle used the discovery retry.
    assert update.await_count == 7


async def test_failures_stay_unavailable_until_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After the grace period every failure raises until the device recovers."""
    update = AsyncMock(
        side_effect=["good"] + [UpdateFailed("down")] * 4 + ["back", UpdateFailed("x")]
    )
    wrapped = _wrap(update)

    await wrapped()
    await wrapped()
    await wrapped()
    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await wrapped()

    assert await wrapped() == "back"
    assert "recovered after 3 failed update cycle(s)" in caplog.text
    # The counter was reset, so the next failure is graced again.
    assert await wrapped() == "back"


async def test_no_grace_before_first_success() -> None:
    """Without a previous good state the failure is raised at once."""
    update = AsyncMock(side_effect=UpdateFailed("down"))

    with pytest.raises(UpdateFailed):
        await _wrap(update)()


@pytest.mark.parametrize("error", [TimeoutError(), OSError("net"), ConstError("x")])
async def test_raw_transient_errors_graced_and_wrapped(error: Exception) -> None:
    """Raw communication errors are graced and finally raised as UpdateFailed."""
    update = AsyncMock(side_effect=["good", error, error, error])
    wrapped = _wrap(update)

    await wrapped()
    assert await wrapped() == "good"
    assert await wrapped() == "good"
    with pytest.raises(UpdateFailed) as exc_info:
        await wrapped()
    assert exc_info.value.__cause__ is error


async def test_programming_errors_not_hidden() -> None:
    """Unexpected exceptions propagate without grace."""
    update = AsyncMock(side_effect=["good", KeyError("bug")])
    wrapped = _wrap(update)

    await wrapped()
    with pytest.raises(KeyError):
        await wrapped()
