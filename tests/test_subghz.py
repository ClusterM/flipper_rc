"""Tests for FlipperIR Sub-GHz functionality."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import importlib.util


# Load flipper_ir module directly
_flipper_path = Path(__file__).resolve().parents[1] / "custom_components" / "flipper_rc" / "flipper_ir.py"
_spec = importlib.util.spec_from_file_location("flipper_ir", _flipper_path)
_module = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(_module)

FlipperIR = _module.FlipperIR
_is_supported_subghz_path = _module._is_supported_subghz_path


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_protocol():
    """Create a mock FlipperProtocol."""
    protocol = AsyncMock()
    protocol.connected = True
    protocol.lines_available = 0
    protocol.buffer = b''
    protocol.has_prompt = False
    protocol.wait_for_prompt = AsyncMock(return_value=[])
    protocol.readline = AsyncMock()
    return protocol


@pytest.fixture
def mock_transport():
    """Create a mock transport."""
    transport = MagicMock()
    transport.is_closing = MagicMock(return_value=False)
    transport.write = MagicMock()
    return transport


class TestIsSupportedSubghzPath:
    """Tests for _is_supported_subghz_path helper."""

    def test_valid_ext_path(self):
        assert _is_supported_subghz_path("/ext/subghz/test.sub") is True

    def test_valid_ext_root(self):
        assert _is_supported_subghz_path("/ext/") is True

    def test_invalid_int_path(self):
        assert _is_supported_subghz_path("/int/subghz/test.sub") is False

    def test_invalid_no_slash(self):
        assert _is_supported_subghz_path("ext/subghz/test.sub") is False

    def test_non_string_returns_false(self):
        assert _is_supported_subghz_path(123) is False
        assert _is_supported_subghz_path(None) is False


class TestSendSubghzValidation:
    """Tests for send_subghz parameter validation."""

    @pytest.mark.asyncio
    async def test_valid_parameters(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        mock_protocol.wait_for_prompt.return_value = [
            ">: subghz tx 123456 433920000 350 1 0",
            "Transmitting...",
            ">: "
        ]

        await ir.send_subghz(key=0x123456, frequency=433920000, te=350, repeat=1, antenna=0)
        assert mock_transport.write.called

    @pytest.mark.asyncio
    async def test_rejects_negative_key(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="key must be in range"):
            await ir.send_subghz(key=-1, frequency=433920000)

    @pytest.mark.asyncio
    async def test_rejects_key_over_max(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="key must be in range"):
            await ir.send_subghz(key=0x1000000, frequency=433920000)

    @pytest.mark.asyncio
    async def test_rejects_zero_frequency(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="frequency must be positive"):
            await ir.send_subghz(key=0x123456, frequency=0)

    @pytest.mark.asyncio
    async def test_rejects_negative_frequency(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="frequency must be positive"):
            await ir.send_subghz(key=0x123456, frequency=-100)

    @pytest.mark.asyncio
    async def test_rejects_invalid_antenna(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="antenna must be 0 or 1"):
            await ir.send_subghz(key=0x123456, frequency=433920000, antenna=2)

    @pytest.mark.asyncio
    async def test_rejects_zero_te(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="te must be positive"):
            await ir.send_subghz(key=0x123456, frequency=433920000, te=0)

    @pytest.mark.asyncio
    async def test_rejects_zero_repeat(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="repeat must be positive"):
            await ir.send_subghz(key=0x123456, frequency=433920000, repeat=0)


class TestSendSubghzFromFileValidation:
    """Tests for send_subghz_from_file parameter validation."""

    @pytest.mark.asyncio
    async def test_valid_parameters(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        mock_protocol.wait_for_prompt.return_value = [
            ">: subghz tx_from_file /ext/subghz/test.sub 1 0",
            "Frequency=433920000",
            ">: "
        ]

        await ir.send_subghz_from_file(path="/ext/subghz/test.sub", repeat=1, antenna=0)
        assert mock_transport.write.called

    @pytest.mark.asyncio
    async def test_rejects_non_ext_path(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match='must start with "/ext/"'):
            await ir.send_subghz_from_file(path="/int/subghz/test.sub")

    @pytest.mark.asyncio
    async def test_rejects_path_with_newline(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="forbidden control characters"):
            await ir.send_subghz_from_file(path="/ext/subghz/test\n.sub")

    @pytest.mark.asyncio
    async def test_rejects_path_with_null(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="forbidden control characters"):
            await ir.send_subghz_from_file(path="/ext/subghz/test\x00.sub")

    @pytest.mark.asyncio
    async def test_rejects_zero_repeat(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="repeat must be positive"):
            await ir.send_subghz_from_file(path="/ext/subghz/test.sub", repeat=0)

    @pytest.mark.asyncio
    async def test_rejects_invalid_antenna(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        with pytest.raises(ValueError, match="antenna must be 0 or 1"):
            await ir.send_subghz_from_file(path="/ext/subghz/test.sub", antenna=2)


class TestValidateCliResponse:
    """Tests for _validate_cli_response validation logic."""

    def test_accepts_valid_subghz_tx_with_frequency(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [">: subghz tx 123456 433920000", "Frequency=433920000", ">: "]
        # Should not raise
        ir._validate_cli_response(lines, [">: subghz tx"], "subghz tx")

    def test_accepts_valid_subghz_tx_with_transmitting(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [">: subghz tx 123456 433920000", "Transmitting...", ">: "]
        ir._validate_cli_response(lines, [">: subghz tx"], "subghz tx")

    def test_rejects_subghz_tx_without_indicator(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [">: subghz tx 123456 433920000", ">: "]
        with pytest.raises(ValueError, match="did not confirm transmission"):
            ir._validate_cli_response(lines, [">: subghz tx"], "subghz tx")

    def test_rejects_subghz_tx_with_error(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [">: subghz tx 123456 433920000", "Error: invalid key", ">: "]
        with pytest.raises(ValueError, match="failed"):
            ir._validate_cli_response(lines, [">: subghz tx"], "subghz tx")

    def test_accepts_non_tx_with_prefix(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [">: info device", "Some info", ">: "]
        # Should not raise
        ir._validate_cli_response(lines, [">: info device"], "info device")

    def test_accepts_non_tx_without_prefix(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = ["Some response", ">: "]
        # Should not raise (tolerant fallback)
        ir._validate_cli_response(lines, [">: expected"], "command")

    def test_rejects_any_command_with_error(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = ["Error: something failed", ">: "]
        with pytest.raises(ValueError, match="failed"):
            ir._validate_cli_response(lines, [">: cmd"], "cmd")

    def test_handles_empty_lines(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = ["", "   ", ">: "]
        ir._validate_cli_response(lines, [">: cmd"], "cmd")

    def test_subghz_tx_from_file_with_frequency_indicator(self):
        ir = FlipperIR("/dev/ttyACM0")
        lines = [
            ">: subghz tx_from_file /ext/subghz/test.sub 1 0",
            "Listening at /ext/subghz/test.sub. Frequency=434176948, Protocol=RAW",
            ">: "
        ]
        ir._validate_cli_response(lines, [">: subghz tx_from_file"], "subghz tx_from_file")


class TestSendCtrlC:
    """Tests for _send_ctrl_c method."""

    def test_sends_ctrl_c_when_connected(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        mock_transport.is_closing.return_value = False

        ir._send_ctrl_c()
        mock_transport.write.assert_called_with(b'\x03')

    def test_noop_when_no_transport(self, mock_protocol):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = None

        # Should not raise
        ir._send_ctrl_c()

    def test_noop_when_transport_closing(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        mock_transport.is_closing.return_value = True

        ir._send_ctrl_c()
        mock_transport.write.assert_not_called()


class TestCommandBuilding:
    """Tests for command string generation."""

    @pytest.mark.asyncio
    async def test_subghz_tx_command_format(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        mock_protocol.wait_for_prompt.return_value = [
            ">: subghz tx 123456 433920000 350 1 0",
            "Transmitting...",
            ">: "
        ]

        await ir.send_subghz(key=0x123456, frequency=433920000, te=350, repeat=1, antenna=0)

        # Verify the command was sent correctly
        write_calls = mock_transport.write.call_args_list
        assert len(write_calls) > 0
        cmd_sent = write_calls[0][0][0].decode()
        assert "subghz tx 123456 433920000 350 1 0" in cmd_sent

    @pytest.mark.asyncio
    async def test_subghz_tx_from_file_command_format(self, mock_protocol, mock_transport):
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        mock_protocol.wait_for_prompt.return_value = [
            ">: subghz tx_from_file /ext/subghz/test.sub 2 1",
            "Frequency=433920000",
            ">: "
        ]

        await ir.send_subghz_from_file(path="/ext/subghz/test.sub", repeat=2, antenna=1)

        # Verify the command was sent correctly
        write_calls = mock_transport.write.call_args_list
        assert len(write_calls) > 0
        cmd_sent = write_calls[0][0][0].decode()
        assert "subghz tx_from_file /ext/subghz/test.sub 2 1" in cmd_sent

    @pytest.mark.asyncio
    async def test_subghz_tx_key_zero_padded(self, mock_protocol, mock_transport):
        """Verify key is zero-padded to 6 hex digits."""
        ir = FlipperIR("/dev/ttyACM0")
        ir._protocol = mock_protocol
        ir._transport = mock_transport
        ir._connected = True

        mock_protocol.wait_for_prompt.return_value = [
            ">: subghz tx 001234 433920000 350 1 0",
            "Transmitting...",
            ">: "
        ]

        await ir.send_subghz(key=0x1234, frequency=433920000, te=350, repeat=1, antenna=0)

        write_calls = mock_transport.write.call_args_list
        cmd_sent = write_calls[0][0][0].decode()
        assert "001234" in cmd_sent  # Zero-padded
