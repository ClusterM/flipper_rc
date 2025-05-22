import sys
import asyncio
import serial_asyncio
import logging
import time

_LOGGER = logging.getLogger(__name__)

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

    def __del__(self):
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
                loop, lambda: FlipperProtocol(), self.port, baudrate=115200 # boudrate is ignored for VCP
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
                await self._protocol.wait_for_prompt()
            except asyncio.TimeoutError as e:
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
        return self._transport is not None
    
    @property
    def busy(self):
        """
        Check if the connection is busy.
        Returns:
            bool: True if busy, False otherwise.
        """
        return self._lock.locked()

    async def ensure_open(self):
        if not self.connected:
            await self.open()

    def _send_ctrl_c(self):
        if self._transport:
            self._transport.write(b'\x03')

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
        _LOGGER.debug(f"Sending command: {cmd.strip()}")
        await self.ensure_open()

        async with self._lock:
            if timeout is None:
                timeout = self.default_timeout
            await self._protocol.wait_for_prompt()
            self._transport.write((cmd.strip() + "\r\n").encode())
            await asyncio.sleep(0.1)
            try:
                lines = await self._protocol.wait_for_prompt(timeout=timeout)
            except asyncio.TimeoutError as e:
                raise TimeoutError("Timeout reached while waiting for Flipper Zero response") from e
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
        if len(lines) >= 2 and not lines[-2].startswith(">: ir tx RAW"):
            raise ValueError(f"Unexpected response: {lines[-2]!r}")
    
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
        self.buffer += data
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            line_str = line.strip().decode(errors="ignore")
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
            # Если уже есть готовая строка — сразу отдаём
            if self.lines:
                return self.lines.pop(0)
            # Ждём!
            future = self._loop.create_future()
            self._line_futures.append(future)
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as e:
                # Если таймаут, то надо убрать future из списка ожидания
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
        """

        plines = []
        start_time = time.time()
        while self.lines_available or not self.has_prompt:
            while self.lines_available > 0:
                line = await self.readline(timeout=timeout)
                plines.append(line)
            if self.has_prompt:
                break
            await asyncio.sleep(0.1)
            if time.time() - start_time > timeout:
                raise TimeoutError("Timeout while waiting for Flipper Zero prompt")
        return plines

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
        Check if the prompt is present in the buffer.
        Returns:
            bool: True if the prompt is present, False otherwise.
        """
        return self.buffer.endswith(b'>: ')


# Пример использования:
if __name__ == "__main__":
    
    async def main():
        logging.basicConfig(level=logging.DEBUG)
        port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyACM0_'
        ir = FlipperIR(port)

        try:
            await ir.open()
            info = await ir.get_device_info()
            print(f"Информация о устройстве: {info}")
            uptime = await ir.get_uptime()
            print(f"Uptime: {uptime}")
            print("🌸 Отправляю сигнал...")
            await ir.send_ir(frequency=38000, duty_cycle=50, samples=[9010, 4495, 559, 555, 588, 526, 556, 559, 564, 550, 563, 553, 560, 555, 558, 557, 556, 559, 564, 1669, 608, 1635, 611, 1632, 583, 1660, 586, 529, 584, 1659, 587, 1656, 590, 1653, 614, 1630, 616, 1627, 589, 526, 607, 507, 616, 499, 583, 532, 611, 503, 610, 506, 586, 528, 615, 499, 614, 1630, 616, 1626, 589, 1654, 612, 1631, 615, 1628, 587, 1656, 611])
            print("🌸 Сигнал отправлен!")
            
            print("🌸 Готова принимать сигналы! Нажми Ctrl+C для выхода.")
            signals = await ir.receive_ir(timeout=10)
            print(f"Получено {len(signals)} сигналов:")
            print(signals)
        except asyncio.exceptions.CancelledError:
            pass
        except KeyboardInterrupt:
            print("Приёмчик остановлен~")
        except Exception as e:
            print(f"Ошибка {e.__class__.__name__}: {e}")
        finally:
            ir.close()
            pass

    asyncio.run(main())
