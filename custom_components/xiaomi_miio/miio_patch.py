"""Protocol-level protection against malformed Xiaomi miIO UDP replies."""

from __future__ import annotations

from functools import wraps
import inspect
import logging
from typing import Any

from construct.core import ConstError
from miio import DeviceException
from miio.miioprotocol import MiIOProtocol

_LOGGER = logging.getLogger(__name__)

_PATCH_MARKER = "_ha_xiaomi_miio_malformed_reply_retry"

# Parameters of MiIOProtocol.send() in python-miio 0.5.12, which this patch
# was written against. The patch is skipped if the signature changes.
_EXPECTED_SEND_PARAMETERS = (
    "self",
    "command",
    "parameters",
    "retry_count",
    "extra_parameters",
)


def _get_command(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    """Extract the miIO command from a MiIOProtocol.send() call."""
    if args:
        command = args[0]
    else:
        command = kwargs.get("command")

    return command if isinstance(command, str) else None


def _is_safe_read_command(command: str | None) -> bool:
    """Return True only for commands that are safe to repeat."""
    if command is None:
        return False

    return command == "get_properties" or command.startswith("get_")


def _is_malformed_reply_error(error: BaseException) -> bool:
    """Identify the two malformed-reply errors observed with the humidifier."""
    if isinstance(error, ConstError):
        return True

    return isinstance(error, TypeError) and (
        "byte indices must be integers or slices, not str" in str(error)
    )


def install_patch() -> None:
    """Install the malformed-response retry once."""
    current_send = MiIOProtocol.send

    if getattr(current_send, _PATCH_MARKER, False):
        return

    parameters = tuple(inspect.signature(current_send).parameters)
    if parameters != _EXPECTED_SEND_PARAMETERS:
        _LOGGER.warning(
            "Unexpected MiIOProtocol.send signature %s; "
            "malformed-response retry patch not installed",
            parameters,
        )
        return

    original_send = current_send

    @wraps(original_send)
    def patched_send(
        self: MiIOProtocol,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        command = _get_command(args, kwargs)

        # Never automatically repeat writes such as set_properties.
        if not _is_safe_read_command(command):
            return original_send(self, *args, **kwargs)

        try:
            return original_send(self, *args, **kwargs)
        except (ConstError, TypeError) as error:
            if not _is_malformed_reply_error(error):
                raise

            _LOGGER.debug(
                "Malformed miIO response for read command %r; retrying once: %s",
                command,
                error,
            )

        try:
            return original_send(self, *args, **kwargs)
        except (ConstError, TypeError) as retry_error:
            if not _is_malformed_reply_error(retry_error):
                raise

            # Convert a repeated malformed response into a communication
            # exception so the coordinator grace logic can handle it.
            raise DeviceException(
                f"Malformed miIO response after retry for command {command!r}"
            ) from retry_error

    setattr(patched_send, _PATCH_MARKER, True)
    MiIOProtocol.send = patched_send  # type: ignore[method-assign]

    _LOGGER.debug("Installed Xiaomi miIO malformed-response retry patch")
