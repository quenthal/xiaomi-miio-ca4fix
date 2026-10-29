"""Tolerate isolated polling failures of Xiaomi Miio devices.

A single failed poll would otherwise mark the entities unavailable until the
next successful poll, one update interval later. The wrapper below retries a
failed device discovery once and keeps the last known state for a few
consecutive failures before the failure is passed on to the coordinator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
from typing import Any

from construct.core import ConstError
from miio import DeviceException

from homeassistant.helpers.update_coordinator import UpdateFailed

_LOGGER = logging.getLogger(__name__)

DISCOVERY_RETRY_DELAY_SEC = 0.25
MAX_CONSECUTIVE_UPDATE_FAILURES = 3

# Communication failures only, so programming errors are not hidden.
TRANSIENT_UPDATE_EXCEPTIONS = (
    UpdateFailed,
    TimeoutError,
    OSError,
    ConstError,
)


def _is_discovery_failure(error: BaseException) -> bool:
    """Return True if the update failed because the handshake got no reply."""
    cause = error.__cause__ if isinstance(error, UpdateFailed) else error
    return isinstance(cause, DeviceException) and (
        "Unable to discover the device" in str(cause)
    )


def with_update_grace(
    update: Callable[[], Coroutine[Any, Any, Any]], device: Any
) -> Callable[[], Coroutine[Any, Any, Any]]:
    """Wrap a coordinator update method with a discovery retry and grace."""
    device_ip = getattr(device, "ip", "unknown")
    last_good_state: Any = None
    consecutive_failures = 0

    async def _fetch_with_discovery_retry() -> Any:
        """Fetch once, with one extra try after a discovery failure."""
        try:
            return await update()
        except UpdateFailed as ex:
            if not _is_discovery_failure(ex):
                raise

            _LOGGER.debug(
                "Temporary Xiaomi Miio discovery failure for %s; "
                "retrying status once in %.2f seconds: %s",
                device_ip,
                DISCOVERY_RETRY_DELAY_SEC,
                ex,
            )

        await asyncio.sleep(DISCOVERY_RETRY_DELAY_SEC)
        return await update()

    async def async_update() -> Any:
        """Fetch state while tolerating isolated communication failures."""
        nonlocal last_good_state, consecutive_failures

        try:
            state = await _fetch_with_discovery_retry()
        except TRANSIENT_UPDATE_EXCEPTIONS as ex:
            consecutive_failures = min(
                consecutive_failures + 1, MAX_CONSECUTIVE_UPDATE_FAILURES
            )

            if last_good_state is None:
                # Nothing to fall back to before the first successful update.
                _LOGGER.debug(
                    "Xiaomi Miio update failed for %s before any successful update: %s",
                    device_ip,
                    ex,
                )
            elif consecutive_failures < MAX_CONSECUTIVE_UPDATE_FAILURES:
                _LOGGER.warning(
                    "Xiaomi Miio update failure %s/%s for %s; "
                    "keeping last known state: %s",
                    consecutive_failures,
                    MAX_CONSECUTIVE_UPDATE_FAILURES,
                    device_ip,
                    ex,
                )
                return last_good_state
            else:
                _LOGGER.error(
                    "Xiaomi Miio update failure %s/%s for %s; "
                    "device will be marked unavailable: %s",
                    consecutive_failures,
                    MAX_CONSECUTIVE_UPDATE_FAILURES,
                    device_ip,
                    ex,
                )

            if isinstance(ex, UpdateFailed):
                raise
            raise UpdateFailed(ex) from ex

        if consecutive_failures and last_good_state is not None:
            _LOGGER.info(
                "Xiaomi Miio device %s recovered after %s failed update cycle(s)",
                device_ip,
                consecutive_failures,
            )

        consecutive_failures = 0
        last_good_state = state
        return state

    return async_update
