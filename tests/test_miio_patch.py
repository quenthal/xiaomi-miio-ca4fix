"""Tests for the malformed miIO reply retry."""

from typing import Any
from unittest.mock import MagicMock

from construct.core import ConstError
from miio import DeviceException
from miio.miioprotocol import MiIOProtocol
import pytest

from custom_components.xiaomi_miio import miio_patch


def _malformed_payload_error() -> TypeError:
    """Return the TypeError python-miio raises for an undecryptable payload."""
    payload: Any = b"\x00\x01"
    try:
        payload["id"]
    except TypeError as err:
        return err
    raise AssertionError("indexing bytes with a str did not raise")


@pytest.fixture
def fake_send(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace MiIOProtocol.send with a mock that has the 0.5.12 signature."""
    mock = MagicMock(return_value=["ok"])

    def send(
        self: MiIOProtocol,
        command: str,
        parameters: Any = None,
        retry_count: int = 3,
        *,
        extra_parameters: Any = None,
    ) -> Any:
        return mock(command, parameters, retry_count)

    monkeypatch.setattr(MiIOProtocol, "send", send)
    miio_patch.install_patch()
    return mock


def _protocol() -> MiIOProtocol:
    return MiIOProtocol("ca4.invalid", "0" * 32)


def test_read_retried_once_after_const_error(fake_send: MagicMock) -> None:
    """A malformed reply to a read command is retried once."""
    fake_send.side_effect = [ConstError("bad header"), ["ok"]]

    assert _protocol().send("get_properties", []) == ["ok"]
    assert fake_send.call_count == 2


def test_read_retried_after_real_payload_type_error(fake_send: MagicMock) -> None:
    """The TypeError from indexing a raw payload is recognised."""
    fake_send.side_effect = [_malformed_payload_error(), ["ok"]]

    assert _protocol().send("get_prop", []) == ["ok"]
    assert fake_send.call_count == 2


def test_repeated_malformed_reply_becomes_device_exception(
    fake_send: MagicMock,
) -> None:
    """Two malformed replies in a row raise DeviceException."""
    fake_send.side_effect = [ConstError("bad"), ConstError("still bad")]

    with pytest.raises(DeviceException) as exc_info:
        _protocol().send("get_properties", [])

    assert isinstance(exc_info.value.__cause__, ConstError)
    assert fake_send.call_count == 2


@pytest.mark.parametrize("command", ["set_properties", "action", "miIO.info"])
def test_non_read_commands_never_retried(fake_send: MagicMock, command: str) -> None:
    """Writes and other non-get commands are sent exactly once."""
    fake_send.side_effect = ConstError("bad")

    with pytest.raises(ConstError):
        _protocol().send(command, [])

    assert fake_send.call_count == 1


def test_unrelated_type_error_not_retried(fake_send: MagicMock) -> None:
    """Programming errors are not mistaken for malformed replies."""
    fake_send.side_effect = TypeError("unsupported operand")

    with pytest.raises(TypeError, match="unsupported operand"):
        _protocol().send("get_properties", [])

    assert fake_send.call_count == 1


def test_command_given_as_keyword(fake_send: MagicMock) -> None:
    """The command is found when passed as a keyword argument."""
    fake_send.side_effect = [ConstError("bad"), ["ok"]]

    assert _protocol().send(command="get_properties") == ["ok"]
    assert fake_send.call_count == 2


def test_install_is_idempotent(fake_send: MagicMock) -> None:
    """Installing twice does not wrap send twice."""
    patched = MiIOProtocol.send
    miio_patch.install_patch()

    assert MiIOProtocol.send is patched


def test_unexpected_signature_skips_patch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A changed python-miio send signature leaves send untouched."""

    def send(self: MiIOProtocol, command: str) -> Any:
        return None

    monkeypatch.setattr(MiIOProtocol, "send", send)
    miio_patch.install_patch()

    assert MiIOProtocol.send is send
    assert "patch not installed" in caplog.text


def test_real_send_signature_is_supported() -> None:
    """The installed python-miio version matches the expected signature."""
    miio_patch.install_patch()

    assert getattr(MiIOProtocol.send, miio_patch._PATCH_MARKER, False)
