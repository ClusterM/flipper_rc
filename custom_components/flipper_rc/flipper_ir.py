import asyncio
import logging
import time
from posixpath import normpath
import re

_LOGGER = logging.getLogger(__name__)


def _is_supported_subghz_path(path):
    return isinstance(path, str) and path.startswith("/ext/")

class FlipperIR:
    def __init__(self, port, default_timeout=10):
        """
        Create a FlipperIR object.

        Args:
            port (str): Serial port to connect to (e.g., 'COM3' or '/dev/ttyACM0').
            default_timeout (int or float, default is 10): Default timeout for waiting for IR signal in seconds.
        """
        
        self.port = port
        self.default_timeout = default_timeout
        self._transport = None
        self._protocol = None
        self._lock = asyncio.Lock()
        self._on_connection_lost = None

    async def async_close(self):
        """Safely close the connection"""
        self.close()

    async def open(self):
        """
        Open the connection to Flipper Zero.
        """
        async with self._lock:
            if self.connected:
                _LOGGER.debug("Serial port already opened")
                return
            loop = asyncio.get_running_loop()
            self._transport, self._protocol = await serial_asyncio.create_serial_connection(
                loop, lambda: FlipperProtocol(), self.port, baudrate=115200  # baudrate is ignored for VCP
            )
            self._protocol.set_on_connection_lost(self.close)
            # Waiting for connection
            # Timeout - 3 seconds
            _LOGGER.debug(f"Connecting to Flipper Zero on {self.port}...")
            start_time = time.time()
            while not self._protocol.connected:
                await asyncio.sleep(0.1)
                if self._protocol.connected:
                    break
                if time.time() - start_time > 3:
                    self.close()
                    raise TimeoutError("Timeout while waiting for Flipper Zero to connect")
            _LOGGER.debug(f"Serial port {self.port} opened")
            try:
                await self._protocol.wait_for_prompt(timeout=10)
            except asyncio.TimeoutError as e:
                _LOGGER.warning("Initial prompt wait timed out, attempting recovery")
                self._send_ctrl_c()
                try:
                    await self._protocol.wait_for_prompt(timeout=5)
                except asyncio.TimeoutError:
                    self.close()
                    raise TimeoutError("Timeout while waiting for Flipper Zero prompt") from e
            except asyncio.CancelledError:
                self.close()
                raise
            _LOGGER.debug("Flipper Zero is ready")

    def close(self):
        """
        Close the connection to Flipper Zero.
        """
        if self._transport:
            self._transport.close()
            self._transport = None
            self._protocol = None
            _LOGGER.debug("Serial port closed")
            if self._on_connection_lost:
                self._on_connection_lost()

    def set_on_connection_lost(self, callback):
        """
        Set a callback to be called when the connection is lost.
        """
        self._on_connection_lost = callback

    @property
    def connected(self):
        """
        Check if the connection to Flipper Zero is established.

        Returns:
            bool: True if connected, False otherwise.
        """
        if self._transport is None:
            return False
        # Detect dead connections: transport exists but is closed or broken
        if self._transport.is_closing():
            return False
        if self._protocol is None or not self._protocol.connected:
            return False
        return True
    
    @property
    def busy(self):
        """
        Check if the connection is busy.
        Returns:
            bool: True if busy, False otherwise.
        """
        return self._lock.locked()

    async def ensure_open(self):
        """Ensure the serial connection is open, detecting dead connections and reconnecting."""
        if not self.connected:
            _LOGGER.info("Connection not established (port %s), opening...", self.port)
            await self.open()
            _LOGGER.info("Connection to Flipper Zero on %s established successfully", self.port)
        else:
            _LOGGER.debug("Connection to Flipper Zero on %s already open", self.port)

    def _validate_cli_response(self, lines, expected_prefixes, command_name):
        """Validate response: reject errors, require tx indicators for subghz, accept prefix."""
        non_empty = [l.strip() for l in lines if isinstance(l, str) and l.strip()]

        # 1. Reject if any error indicator found
        for line in non_empty:
            low = line.lower()
            if any(ind in low for ind in ("error", "failed", "invalid", "unknown",
                                          "file not found", "cannot", "refused", "denied",
                                          "not supported", "no such")):
                raise ValueError(f"{command_name} failed: {line!r}")

        # 2. Subghz tx commands require transmission confirmation
        low_name = command_name.lower()
        if "subghz" in low_name and "tx" in low_name:
            for line in non_empty:
                if any(ind in line.lower() for ind in ("transmitting", "frequency",
                        "transmission", "sending", "done", "success", "complete")):
                    return
            raise ValueError(
                f"{command_name} did not confirm transmission. "
                f"Response: {'; '.join(non_empty)}. Check firmware/command syntax."
            )

        # 3. Accept if expected prefix found (non-tx commands)
        for line in non_empty:
            if any(line.startswith(p) for p in expected_prefixes):
                return

        # 4. Tolerant fallback for non-tx commands
        _LOGGER.debug("No expected echo for %s; accepting (no errors). Lines: %s",
                      command_name, [str(l) for l in lines])

    def _send_ctrl_c(self):
        """Send Ctrl-C (0x03) to break the Flipper out of its current operation."""
        if self._transport and not self._transport.is_closing():
            self._transport.write(b'\x03')
            _LOGGER.debug("Sent Ctrl-C to Flipper Zero to break current operation")

    async def recover_from_timeout(self):
        """Send Ctrl-C and drain buffer to recover from a stuck Flipper."""
        _LOGGER.warning("Recovery: sending Ctrl-C and draining buffer")
        self._send_ctrl_c()
        await asyncio.sleep(0.2)
        if self._protocol:
            try:
                while self._protocol.lines_available > 0:
                    try:
                        line = await self._protocol.readline(timeout=0.5)
                        _LOGGER.debug("Drained during recovery: %s", line)
                    except TimeoutError:
                        break
                if self._protocol.buffer:
                    _LOGGER.debug("Drained partial buffer: %s", self._protocol.buffer)
                    self._protocol.buffer = b''
            except (RuntimeError, ConnectionError) as e:
                _LOGGER.warning("Error during recovery drain: %s", e)
        await asyncio.sleep(0.3)

    async def command(self, cmd, timeout=None):
        """
        Send a command to Flipper Zero and wait for the response.

        Args:
            cmd (str): Command to send.
            timeout (int or float, optional): Timeout for waiting for response in seconds.
                                               If not specified, uses default_timeout.

        Returns:
            list: List of lines received from Flipper Zero.            
        """
        if not isinstance(cmd, str):
            raise ValueError("CLI command must be a string")
        if "\n" in cmd or "\r" in cmd or "\x00" in cmd:
            raise ValueError("CLI command contains forbidden control characters")

        _LOGGER.debug("Sending command: %s", cmd.strip())
        await self.ensure_open()

        async with self._lock:
            if timeout is None:
                timeout = self.default_timeout
            try:
                await self._protocol.wait_for_prompt()
            except TimeoutError as e:
                _LOGGER.warning("Prompt wait failed, recovering: %s", e)
                await self.recover_from_timeout()
                await self._protocol.wait_for_prompt(timeout=5)
            if self._transport and not self._transport.is_closing():
                self._transport.write((cmd.strip() + "\r\n").encode())
            else:
                raise ConnectionError("Serial transport closed after recovery")
            await asyncio.sleep(0.1)
            try:
                lines = await self._protocol.wait_for_prompt(timeout=timeout)
                _LOGGER.debug("Command %s completed: %d lines", cmd.strip(), len(lines))
            except asyncio.TimeoutError as e:
                _LOGGER.warning("Timeout for '%s', recovering", cmd.strip())
                await self.recover_from_timeout()
                try:
                    lines = await self._protocol.wait_for_prompt(timeout=5)
                    _LOGGER.debug("Recovered from timeout for '%s': %d lines", cmd.strip(), len(lines))
                except TimeoutError as e2:
                    raise TimeoutError(f"Timeout waiting for response to '{cmd.strip()}'") from e
            except asyncio.CancelledError:
                self.close()
                raise
            return lines

    async def receive_ir(self, timeout=None):
        """
        Listen for IR signals from Flipper Zero.

        Args:
            timeout (int or float, optional): Timeout for waiting for IR signal in seconds.
                                              If not specified, uses default_timeout.

        Returns:
            List[int]: Received signal as a list of pulse and space lengths in microseconds.
        """
        await self.ensure_open()

        async with self._lock:
            if timeout is None:
                timeout = self.default_timeout
            await self._protocol.wait_for_prompt()
            cmd = b'ir rx raw\r\n'
            self._transport.write(cmd)
            await asyncio.sleep(0.1)
            start_time = time.time()
            sample_pending = False

            while True:
                try:
                    line = await self._protocol.readline(timeout=timeout)
                except asyncio.TimeoutError:
                    if time.time() - start_time > timeout:
                        self._send_ctrl_c()
                        await self._protocol.wait_for_prompt()
                        raise TimeoutError("Timeout reached while waiting for IR signal")
                    continue
                except asyncio.CancelledError:
                    self.close()
                    raise
                if line.startswith("RAW"):
                    sample_pending = True
                    continue
                if sample_pending:
                    samples = [int(x) for x in line.split()]
                    self._send_ctrl_c()
                    await self._protocol.wait_for_prompt()
                    return samples

    async def send_ir(self, samples, frequency=38000, duty_cycle=50):
        """
        Send IR signal to Flipper Zero.

        Args:
            frequency (int): Frequency in Hz.
            duty_cycle (int): Duty cycle in % (e.g., 33).
            samples (list): List of pulse and space lengths in microseconds.
        """
        samples_str = ' '.join(str(x) for x in samples)
        cmd = f"ir tx RAW F:{frequency} DC:{duty_cycle} {samples_str}"        
        lines = await self.command(cmd)
        self._validate_cli_response(lines, [">: ir tx RAW", ">: ir tx raw"], "ir tx")

    async def send_subghz(self, key, frequency, te=350, repeat=1, antenna=0):
        """Send Sub-GHz key with Flipper CLI subghz tx command."""
        if not (0 <= int(key) <= 0xFFFFFF):
            raise ValueError("Sub-GHz key must be in range 0x000000-0xFFFFFF")
        if int(frequency) <= 0:
            raise ValueError("Sub-GHz frequency must be positive")
        if int(antenna) not in (0, 1):
            raise ValueError("Sub-GHz antenna must be 0 or 1")
        if int(te) <= 0:
            raise ValueError("Sub-GHz te must be positive")
        if int(repeat) <= 0:
            raise ValueError("Sub-GHz repeat must be positive")

        key_int = int(key)
        freq_int = int(frequency)
        te_int = int(te)
        repeat_int = int(repeat)
        antenna_int = int(antenna)

        cmd = f"subghz tx {key_int:06X} {freq_int} {te_int} {repeat_int} {antenna_int}"
        lines = await self.command(cmd)
        self._validate_cli_response(lines, [">: subghz tx"], "subghz tx")

    async def send_subghz_from_file(self, path, repeat=1, antenna=0):
        """Send Sub-GHz transmission from saved Flipper SD card file."""
        if not _is_supported_subghz_path(path):
            raise ValueError('Sub-GHz file path must start with "/ext/"')
        if "\n" in path or "\r" in path or "\x00" in path:
            raise ValueError("Sub-GHz file path contains forbidden control characters")
        if int(repeat) <= 0:
            raise ValueError("Sub-GHz repeat must be positive")
        if int(antenna) not in (0, 1):
            raise ValueError("Sub-GHz antenna must be 0 or 1")

        cmd = f"subghz tx_from_file {path} {int(repeat)} {int(antenna)}"
        lines = await self.command(cmd)
        self._validate_cli_response(lines, [">: subghz tx_from_file"], "subghz tx_from_file")

    async def _storage_list(self, path):
        """List one storage directory and return absolute dir/file paths."""
        lines = await self.command(f"storage list {path}")
        dirs = []
        files = []
        for line in lines:
            if not line or line.startswith(">: "):
                continue
            item = line.strip()
            if not item or item in (".", ".."):
                continue

            entry_type = None
            name = item
            if item.startswith("[D] "):
                entry_type = "dir"
                name = item[4:].strip()
            elif item.startswith("[F] "):
                entry_type = "file"
                name = item[4:].strip()

            if not name:
                continue

            full_path = normpath(name if name.startswith("/") else f"{path.rstrip('/')}/{name}")

            # Tolerant fallback when type prefix is missing in output.
            if entry_type == "dir" or (entry_type is None and item.endswith("/")):
                dirs.append(full_path.rstrip("/"))
            elif entry_type == "file" or (entry_type is None and full_path.endswith(".sub")):
                files.append(full_path)

        return dirs, files

    async def _storage_tree_sub_files(self, root):
        """Extract .sub file paths from `storage tree` output."""
        lines = await self.command(f"storage tree {root}")
        found = set()
        for line in lines:
            if not line or line.startswith(">: "):
                continue

            lower_line = line.lower()

            # Absolute path in output.
            for root_token in ("/ext/",):
                if root_token in line and ".sub" in lower_line:
                    start = line.find(root_token)
                    end = lower_line.find(".sub", start)
                    if start >= 0 and end > start:
                        found.add(normpath(line[start:end + 4].strip()))

            for match in re.findall(r"/ext/[^\s]*\.sub", line, flags=re.IGNORECASE):
                found.add(normpath(match.strip()))

            # Relative filename fallback in output tree line.
            if ".sub" in lower_line and "/ext/" not in line:
                # Strip tree drawing characters and keep a best-effort filename.
                stripped = line.strip().lstrip("|`-+> ")
                if stripped.lower().endswith(".sub"):
                    found.add(normpath(f"{root.rstrip('/')}/{stripped}"))

        return sorted(found)

    async def list_subghz_files(self, root="/ext/subghz"):
        """Recursively list Sub-GHz .sub files on Flipper storage."""
        try:
            tree_files = await self._storage_tree_sub_files(root)
            tree_files = [p for p in tree_files if _is_supported_subghz_path(p) and p.lower().endswith(".sub")]
            if tree_files:
                return sorted(set(tree_files))
        except Exception as e:
            _LOGGER.debug("Cannot read storage tree for %s: %s", root, e)

        discovered = []
        queue = [root.rstrip("/")]
        visited = set()

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            try:
                dirs, files = await self._storage_list(current)
            except Exception as e:
                _LOGGER.debug("Cannot list storage path %s: %s", current, e)
                continue

            for file_path in files:
                if _is_supported_subghz_path(file_path) and file_path.lower().endswith(".sub"):
                    discovered.append(file_path)
            for dir_path in dirs:
                if _is_supported_subghz_path(dir_path) and dir_path not in visited:
                    queue.append(dir_path)

        return sorted(set(discovered))
    
    async def get_device_info(self):
        """
        Get device information from Flipper Zero.

        Returns:
            dict: Device information as a dictionary.
        """
        _LOGGER.debug("Getting device info")
        lines = await self.command("info device")
        info = {}
        for line in lines:
            if line.startswith(">: "):
                continue
            if ':' in line:
                key, value = line.split(':', 1)
                info[key.strip()] = value.strip()
        _LOGGER.debug(f"Received info: {info}")
        return info

    async def get_uptime(self):
        """
        Get the uptime of the Flipper Zero.

        Returns:
            str: Uptime as a string.
        """
        _LOGGER.debug("Getting uptime")
        await self.ensure_open()
        lines = await self.command("uptime")
        uptime = lines[-1].split(' ', 1)[1].strip()
        _LOGGER.debug(f"Received uptime: {uptime}")
        return uptime        

class FlipperProtocol(asyncio.Protocol):
    def __init__(self):
        self.buffer = b''
        self.lines = []
        self._loop = asyncio.get_running_loop()
        self._line_futures = []
        self._on_connection_lost = None
        self._connected = False
        self._readline_lock = asyncio.Lock()

    @property
    def lines_available(self):
        """
        Returns the number of lines available in the buffer.
        """
        return len(self.lines)

    def connection_made(self, transport):
        self._connected = True

    def data_received(self, data):
        """Handle data received from the serial port."""
        _LOGGER.debug("Data received from Flipper (%d bytes): %s", len(data), data)
        self.buffer += data
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            line_str = line.strip().decode(errors="ignore")
            _LOGGER.debug("Parsed line from Flipper: %s", line_str)
            self.lines.append(line_str)
            if self._line_futures:
                future = self._line_futures.pop(0)
                if not future.done():
                    future.set_result(self.lines.pop(0))
    
    def set_on_connection_lost(self, callback):
        """
        Set a callback to be called when the connection is lost.
        """
        self._on_connection_lost = callback

    def connection_lost(self, exc):
        _LOGGER.debug("Connection lost with Flipper Zero, reason: %s", exc)
        self._connected = False
        for future in self._line_futures:
            if not future.done():
                future.set_exception(ConnectionError("Serial connection lost"))
        self._line_futures.clear()
        self.buffer = b''
        self.lines.clear()
        if self._on_connection_lost:
            self._on_connection_lost()

    async def readline(self, timeout=10):
        """
        Read a line from the Flipper Zero.
        Args:
            timeout (int or float, optional): Timeout for reading a line in seconds, default is 10.
        Returns:
            str: The line read from the Flipper Zero.
        """
                                               
        async with self._readline_lock:
            # If line is already available, return immediately
            if self.lines:
                return self.lines.pop(0)
            # Wait for data
            future = self._loop.create_future()
            self._line_futures.append(future)
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as e:
                # On timeout, remove future from pending list
                if not future.done():
                    self._line_futures.remove(future)
                raise TimeoutError("Timeout while waiting for Flipper Zero response") from e
            except asyncio.CancelledError:
                raise
 
    async def wait_for_prompt(self, timeout=3):
        """
        Wait for the Flipper Zero prompt to appear.

        Args:
            timeout (int or float, optional): Timeout for waiting for the prompt in seconds, default is 3.
        Returns:
            list: List of lines received before the prompt.

        Raises:
            TimeoutError: If the prompt is not found within the timeout period.
        """
        _LOGGER.debug("Waiting for Flipper Zero prompt (timeout=%ss)...", timeout)
        plines = []
        start_time = time.time()

        while True:
            # Drain all available lines. Use remaining timeout so readline waits
            # long enough for slow responses (e.g., subghz transmission completion).
            remaining = max(0.1, timeout - (time.time() - start_time))
            while self.lines_available > 0:
                try:
                    line = await self.readline(timeout=remaining)
                    plines.append(line)
                except TimeoutError:
                    break

            # Check for prompt using multiple strategies:
            # 1. Check remaining buffer for partial prompt data
            # 2. Check collected lines for prompt (race-condition resistant)
            prompt_found = self._check_prompt_in_lines(plines) or self.has_prompt

            if prompt_found:
                _LOGGER.debug("Flipper Zero prompt found after %.2fs, collected %d lines",
                              time.time() - start_time, len(plines))
                return plines

            elapsed = time.time() - start_time
            if elapsed > timeout:
                _LOGGER.warning("Timeout (%.1fs) waiting for Flipper Zero prompt. "
                                "Buffer: %s, Lines collected: %d, Last lines: %s",
                                timeout, self.buffer, len(plines), plines[-3:] if plines else [])
                raise TimeoutError(
                    f"Timeout while waiting for Flipper Zero prompt after {timeout:.1f}s. "
                    f"Collected {len(plines)} lines. Remaining buffer: {self.buffer!r}"
                )

            await asyncio.sleep(0.1)

    def _check_prompt_in_lines(self, lines):
        """
        Check if the prompt marker (': ') appears at the end of any collected line.

        This is a race-condition-resistant check: when data_received splits on '\n',
        the prompt '>: ' may end up as the last line in self.lines rather than in
        self.buffer. By checking all collected lines, we avoid missing the prompt.
        """
        prompt_markers = [b'>: ', b' >:', b'>:\r']
        for line in lines:
            line_bytes = line.encode() if isinstance(line, str) else line
            for marker in prompt_markers:
                if line_bytes.endswith(marker):
                    _LOGGER.debug("Prompt found in collected line: %s", line)
                    return True
        return False

    # def reset(self):
    #     self.buffer = b''
    #     self.lines.clear()
    #     for fut in self._line_futures:
    #         if not fut.done():
    #             fut.set_exception(asyncio.CancelledError())
    #     self._line_futures.clear()
        
    @property
    def connected(self):
        """
        Check if the connection to Flipper Zero is established.
        Returns:
            bool: True if connected, False otherwise.
        """
        return self._connected
    
    @property
    def has_prompt(self):
        """
        Check if the prompt is present in the remaining buffer.

        Note: This only checks the unprocessed buffer (data not yet split into lines).
        For robust prompt detection, also use _check_prompt_in_lines() to scan
        already-collected lines, as the prompt may appear there due to race conditions
        between data_received() and wait_for_prompt().

        Returns:
            bool: True if the prompt is present in the buffer, False otherwise.
        """
        return self.buffer.endswith(b'>: ')


if __name__ == "__main__":

    async def main():
        import sys
        logging.basicConfig(level=logging.DEBUG)
        port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyACM0_'
        ir = FlipperIR(port)

        try:
            await ir.open()
            info = await ir.get_device_info()
            print(f"Device info: {info}")
            uptime = await ir.get_uptime()
            print(f"Uptime: {uptime}")
            print("Sending IR signal...")
            await ir.send_ir(frequency=38000, duty_cycle=50, samples=[9010, 4495, 559, 555, 588, 526, 556, 559, 564, 550, 563, 553, 560, 555, 558, 557, 556, 559, 564, 1669, 608, 1635, 611, 1632, 583, 1660, 586, 529, 584, 1659, 587, 1656, 590, 1653, 614, 1630, 616, 1627, 589, 526, 607, 507, 616, 499, 583, 532, 611, 503, 610, 506, 586, 528, 615, 499, 614, 1630, 616, 1626, 589, 1654, 612, 1631, 615, 1628, 587, 1656, 611])
            print("Signal sent!")

            print("Ready to receive signals. Press Ctrl+C to exit.")
            signals = await ir.receive_ir(timeout=10)
            print(f"Received {len(signals)} signals:")
            print(signals)
        except asyncio.exceptions.CancelledError:
            pass
        except KeyboardInterrupt:
            print("Receiver stopped")
        except Exception as e:
            print(f"Error {e.__class__.__name__}: {e}")
        finally:
            ir.close()

    asyncio.run(main())
