"""Support for Flipper Zero Remote Control."""
import logging
import asyncio
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
import time
from .flipper_ir import FlipperIR

from .const import *

from homeassistant.const import (
    CONF_NAME,
    CONF_PORT,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components.persistent_notification import async_create
from homeassistant.components.remote import (
    ATTR_COMMAND_TYPE,
    ATTR_TIMEOUT,
    ATTR_ALTERNATIVE,
    ATTR_COMMAND,
    ATTR_DEVICE,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    ATTR_HOLD_SECS,
    PLATFORM_SCHEMA,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.helpers.storage import Store

from .rc_encoder import rc_auto_encode, rc_auto_decode
from .parsers import parse_subghz_command, parse_subghz_file_command

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
            vol.Optional(CONF_NAME, default=DEFAULT_FRIENDLY_NAME): cv.string,
            vol.Required(CONF_PORT): cv.string,
    }
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Flipper Zero Remote Control entry."""
    await async_setup_platform(hass, entry.data, async_add_entities, entry.entry_id)


async def async_setup_platform(hass, config, async_add_entities, entry_id=None):
    """Set up platform."""
    if config is None:
        _LOGGER.error("Configuration is empty")
        return
    
    name = config.get(CONF_NAME, DEFAULT_FRIENDLY_NAME)
    port = config.get(CONF_PORT)
    device_info_storage = Store(hass, DEVICE_INFO_STORAGE_VERSION, f"{DEVICE_INFO_STORAGE}_{port}")
    device_info = await device_info_storage.async_load() or {}
    codes_storage = Store(hass, CODE_STORAGE_VERSION, CODE_STORAGE_CODES)
    codes = await codes_storage.async_load() or {}

    _LOGGER.debug("Setting up Flipper Zero Remote Control: name=%s, port=%s", name, port)

    remote = FlipperRCEntity(name, port, device_info_storage, device_info, codes_storage, codes, entry_id)

    if entry_id is not None:
        hass.data.setdefault(DOMAIN, {}).setdefault("remote_entities", {})[entry_id] = remote

    async_add_entities([remote])


class FlipperRCEntity(RemoteEntity):
    def __init__(self, name, port, device_info_storage, device_info, codes_storage, codes, entry_id=None):
        self._name = name
        self._port = port
        self._entry_id = entry_id
        self._device_info_storage = device_info_storage
        self._device_info = device_info
        self._last_device_info_update = 0
        self._codes_storage = codes_storage
        self._codes = codes
        self._available = False
        self._last_error = None
        self._last_operation = None
        self._device = FlipperIR(self._port)
        self._device.set_on_connection_lost(self._on_connection_lost)

    def _on_connection_lost(self):
        _LOGGER.warning("Connection lost to Flipper device %s", self._port)
        self._available = False
        self.schedule_update_ha_state()

    @property
    def available(self):
        return self._available

    @property
    def state(self):
        return 'online' if self._available else 'offline'

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return f"{DOMAIN}_{self._port}"

    @property
    def port(self):
        return self._port

    @property
    def should_poll(self):
        return True

    @property
    def device_info(self):
        return DeviceInfo(
            name=self._name,
            manufacturer="Flipper Devices Inc.",
            identifiers={(DOMAIN, self._port)},
            connections={(DOMAIN, self._device_info.get("hardware.name", ""))},
            model=self._device_info.get("hardware.model", "Flipper Zero"),
            serial_number=self._device_info.get("hardware.name", ""),
            hw_version=self._device_info.get("hardware.ver", ""),
            sw_version=self._device_info.get("firmware.version", ""),
        )
    
    @property
    def extra_state_attributes(self):
        attrs = dict(self._device_info)
        if self._last_operation is not None:
            attrs["last_operation"] = self._last_operation
        if self._last_error is not None:
            attrs["last_error"] = self._last_error
        return attrs

    @property
    def supported_features(self):
        return RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND

    async def async_added_to_hass(self):
        await self.async_update()
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self):
        _LOGGER.debug("Removing device from Home Assistant...")
        if self._entry_id is not None and self.hass is not None:
            remote_entities = self.hass.data.get(DOMAIN, {}).get("remote_entities", {})
            if remote_entities.get(self._entry_id) is self:
                del remote_entities[self._entry_id]
        if self._device:
            self._device.close()
            _LOGGER.debug("Device deinitialized.")

    async def async_update(self):
        """Update the device."""
        # Limit the update frequency to every 30 seconds
        if time.time() - self._last_device_info_update < 30:
            return
        self._last_device_info_update = time.time()
        try:
            device_info = await self._device.get_device_info()
            if self._device_info != device_info:
                _LOGGER.info("Device info changed: %s", device_info)
                self._device_info = device_info
                await self._device_info_storage.async_save(self._device_info)
            self._available = True
        except (TimeoutError, ConnectionError, OSError) as e:
            _LOGGER.warning("Failed to update Flipper device info: %s", e)
            self._available = False
        except Exception as e:
            _LOGGER.error("Unexpected error updating device info: %s", e, exc_info=True)
            self._available = False

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        raise HomeAssistantError("Turning on is not supported for this device.")

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        raise HomeAssistantError("Turning off is not supported for this device.")

    async def async_list_subghz_files(self, root):
        """Public API for listing Sub-GHz files on Flipper storage."""
        return await self._device.list_subghz_files(root)

    async def async_send_subghz_from_file(self, path, repeat=1, antenna=0):
        """Public API for replaying Sub-GHz capture files from storage."""
        _LOGGER.info("async_send_subghz_from_file called: path=%s, repeat=%d, antenna=%d", path, repeat, antenna)
        self._last_operation = f"Sending Sub-GHz file: {path}"
        self._last_error = None
        try:
            await self._device.send_subghz_from_file(path, repeat=repeat, antenna=antenna)
            _LOGGER.info("async_send_subghz_from_file succeeded for %s", path)
        except Exception as e:
            self._last_error = str(e)
            _LOGGER.error("async_send_subghz_from_file failed for %s: %s", path, e)
            raise HomeAssistantError(f"Failed to send Sub-GHz file '{path}' from Flipper Zero: {e}. "
                                     "Check that the Flipper is connected, the file exists on the SD card, "
                                     "and the Sub-GHz radio is not busy.")

    async def async_send_command(self, command, **kwargs):
        """Send a list of commands to a device."""
        device = kwargs.get(ATTR_DEVICE, None)
        repeat = kwargs.get(ATTR_NUM_REPEATS, 1)
        repeat_delay = kwargs.get(ATTR_DELAY_SECS, 0)
        hold = kwargs.get(ATTR_HOLD_SECS, 0)

        if hold != 0:
            raise NotImplementedError("Hold time is not supported.")

        _LOGGER.info("async_send_command called: commands=%s, device=%s, repeat=%d", command, device, repeat)
        self._last_error = None

        try:
            for n in range(repeat):
                for cmd in command:
                    if device:
                        if device not in self._codes:
                            raise KeyError(f"Device '{device}' not found in the codes storage.")
                        if cmd not in self._codes[device]:
                            raise KeyError(f"Command '{cmd}' not found in the codes storage for device '{device}'.")
                        code = self._codes[device][cmd]
                        self._last_operation = f"Sending IR command '{cmd}' for device '{device}'"
                        _LOGGER.info("Sending IR command '%s' for device '%s', code: %s", cmd, device, code)
                    else:
                        code = cmd
                        self._last_operation = f"Sending command: {code}"
                        _LOGGER.info("Sending command, code: '%s'", code)

                    if isinstance(code, str) and code.startswith("subghz-file:"):
                        tx = parse_subghz_file_command(code)
                        self._last_operation = f"Sending Sub-GHz file: {tx['path']}"
                        _LOGGER.info("Sub-GHz file command parsed: %s", tx)
                        await self._device.send_subghz_from_file(
                            path=tx["path"],
                            repeat=tx["repeat"],
                            antenna=tx["antenna"],
                        )
                    elif isinstance(code, str) and code.startswith("subghz:"):
                        tx = parse_subghz_command(code)
                        self._last_operation = f"Sending Sub-GHz: key=0x{tx['key']:06X}, freq={tx['frequency']}"
                        _LOGGER.info("Sub-GHz command parsed: %s", tx)
                        await self._device.send_subghz(
                            key=tx["key"],
                            frequency=tx["frequency"],
                            te=tx["te"],
                            repeat=tx["repeat"],
                            antenna=tx["antenna"],
                        )
                    else:
                        pulses = rc_auto_encode(code)
                        self._last_operation = f"Sending IR signal ({len(pulses)} pulses)"
                        _LOGGER.info("Encoded IR command: %s pulses", len(pulses))
                        await self._device.send_ir(pulses)
                    if n < repeat - 1 and repeat_delay > 0:
                        await asyncio.sleep(repeat_delay)
            if not self._available:
                self._available = True
                self.schedule_update_ha_state()
            _LOGGER.info("async_send_command completed successfully")
        except HomeAssistantError:
            # Re-raise HomeAssistantError as-is (already user-friendly)
            raise
        except TimeoutError as e:
            self._last_error = str(e)
            _LOGGER.error("Timeout sending command: %s", e)
            raise HomeAssistantError(
                f"Command timed out: {e}. "
                "The Flipper Zero may be busy or unresponsive. "
                "Try again in a moment, or check the device connection."
            ) from e
        except (ValueError, KeyError) as e:
            self._last_error = str(e)
            _LOGGER.error("Invalid command parameters: %s", e)
            raise HomeAssistantError(f"Invalid command: {e}") from e
        except ConnectionError as e:
            self._last_error = str(e)
            self._available = False
            self.schedule_update_ha_state()
            _LOGGER.error("Connection lost while sending command: %s", e)
            raise HomeAssistantError(
                f"Connection to Flipper Zero lost: {e}. "
                "Please check the USB connection and try again."
            ) from e
        except Exception as e:
            self._last_error = str(e)
            _LOGGER.error("Failed to send command, exception %s: %s", type(e).__name__, e, exc_info=True)
            raise HomeAssistantError(
                f"Failed to send command to Flipper Zero: {e}. "
                "Check device connectivity and try again."
            ) from e

    async def async_learn_command(self, **kwargs):
        """Learn a command to a device, or just show the received command code."""
        device = kwargs.get(ATTR_DEVICE, None)
        commands = kwargs.get(ATTR_COMMAND, [])
        command_type = kwargs.get(ATTR_COMMAND_TYPE, "ir")
        alternative = kwargs.get(ATTR_ALTERNATIVE, None)
        timeout = kwargs.get(ATTR_TIMEOUT, 10)

        if len(commands) != 1:
            raise ValueError("You need to specify exactly one command to learn.")

        command = commands[0]
        notification_id = f"{DOMAIN}_learn_command_{self._port}_{device}_{command}"
        
        try:
            if not command: raise ValueError("You need to specify a command name to learn.")
            if command_type != "ir":
                if command_type == "subghz":
                    raise NotImplementedError(
                        "Sub-GHz learning is not supported yet. "
                        "Use remote.send_command with a subghz:... code string."
                    )
                raise NotImplementedError(f'Unknown command type "{command_type}", only "ir" is supported.')
            if alternative != None: raise ValueError('"Alternative" option is not supported.')
            if self._device.busy:
                raise HomeAssistantError("Device is busy, please wait and try again.")
            async_create(
                self.hass,
                f'Press the "<b>{command}</b>" button.',
                title=NOTIFICATION_TITLE,
                notification_id=notification_id,
            )
            
            _LOGGER.debug(f"Waiting for button press...")
            pulses = await self._device.receive_ir(timeout)
            _LOGGER.debug("Button pressed: %s", pulses)
            if len(pulses) < 4:
                raise ValueError("This IR code is too short and seems to be invalid. Please try to learn the command again.")
            decoded = rc_auto_decode(pulses)
            _LOGGER.debug("Button decoded: %s", decoded)
            decoded_raw = rc_auto_decode(pulses, force_raw=True)

            direct_code_example = f'<pre>service: remote.send_command\ntarget:\n  entity_id: {self.entity_id}\ndata:\n  command: {decoded}</pre>'
            direct_code_example_raw = f'If code above is not working, you can try to use the raw code:\n<pre>service: remote.send_command\ntarget:\n  entity_id: {self.entity_id}\ndata:\n  command: {decoded_raw}</pre>But <a href="https://github.com/ClusterM/flipper_rc/issues">create a bug report</a> in such case, please.'
            
            if device:
                self._codes.setdefault(device, {}).update({command: decoded})
                await self._codes_storage.async_save(self._codes)
                self.schedule_update_ha_state() # Update device attributes
                msg = f'Successfully learned command "<b>{command}</b>" for device "<b>{device}</b>", code:\r\n<pre>{decoded}</pre>' + \
                    (f"Raw code:<pre>{decoded_raw}</pre>" if not decoded.startswith("raw:") else "") + \
                    "\n\nNow you can use this device identifier and command name in your automations and scripts with the 'remote.send_command' service. Example:" + \
                    f'<pre>service: remote.send_command\ntarget:\n  entity_id: {self.entity_id}\ndata:\n  device: {device}\n  command: {command}</pre>' + \
                    "\n\nOr you can use the button code directly in your automations and scripts with the 'remote.send_command' service. Example:" + \
                    direct_code_example + \
                    (f"\n\n{direct_code_example_raw}" if not decoded.startswith("raw:") else "")
            else:
                msg = f'Successfully received command "{command}", code:\r\n<pre>{decoded}</pre>' + \
                    (f"Raw code:<pre>{decoded_raw}</pre>" if not decoded.startswith("raw:") else "") + \
                    "\n\nNow you can use this code in your automations and scripts with the 'remote.send_command' service. Example:" + \
                    direct_code_example + \
                    (f"\n\n{direct_code_example_raw}" if not decoded.startswith("raw:") else "")
                
            if decoded.startswith("raw:"):
                msg += "\r\n\r\n<b>Warning</b>: this command is learned in raw format, e.g. it can't be decoded using known protocol decoders. It's better to try to learn the command again but it's ok if you keep seeing this message."

            async_create(
                self.hass,
                msg,
                title=NOTIFICATION_TITLE,
                notification_id=notification_id,
            )
            
            if not self._available:
                self._available = True
                self.schedule_update_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to learn command, exception %s: %s", type(e), e, exc_info=True)
            async_create(
                self.hass,
                f'Cannot learn command "{command}": {e}',
                title=NOTIFICATION_TITLE,
                notification_id=notification_id,
            )
            raise HomeAssistantError(str(e))

    async def async_delete_command(self, **kwargs):
        """Delete a command from a device."""
        device = kwargs.get(ATTR_DEVICE, None)
        commands = kwargs.get(ATTR_COMMAND, [])
        
        if not device:
            raise HomeAssistantError("You need to specify a device.")

        if device not in self._codes:
            raise HomeAssistantError(f"Device '{device}' not found in the codes storage.")

        deleted = False
        for command in commands:
            if command in self._codes.get(device, {}):
                del self._codes[device][command]
                deleted = True
                async_create(
                    self.hass,
                    f'Successfully deleted command "{command}" for device "{device}".',
                    title=NOTIFICATION_TITLE
                )
        if not deleted:
            raise HomeAssistantError(f'Command "{command}" for device "{device}" not found.')

        # Remove device if no commands left
        if device in self._codes and not self._codes[device]:
            del self._codes[device]

        await self._codes_storage.async_save(self._codes)
