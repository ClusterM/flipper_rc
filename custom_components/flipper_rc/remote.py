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

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
            vol.Optional(CONF_NAME, default=DEFAULT_FRIENDLY_NAME): cv.string,
            vol.Required(CONF_PORT): cv.string,
    }
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Flipper Zero Remote Control entry."""
    await async_setup_platform(hass, entry.data, async_add_entities)


async def async_setup_platform(hass, config, async_add_entities):
    """Set up platform."""
    if config == None:
        _LOGGER.error("Configuration is empty")
        return
    
    name = config.get(CONF_NAME, DEFAULT_FRIENDLY_NAME)
    port = config.get(CONF_PORT)
    device_info_storage = Store(hass, DEVICE_INFO_STORAGE_VERSION, f"{DEVICE_INFO_STORAGE}_{port}")
    device_info = await device_info_storage.async_load() or {}
    codes_storage = Store(hass, CODE_STORAGE_VERSION, CODE_STORAGE_CODES)
    codes = await codes_storage.async_load() or {}

    _LOGGER.debug("Setting up Flipper Zero Remote Control: name=%s, port=%s", name, port)

    remote = FlipperRCEntity(name, port, device_info_storage, device_info, codes_storage, codes)

    async_add_entities([remote])


class FlipperRCEntity(RemoteEntity):
    def __init__(self, name, port, device_info_storage, device_info, codes_storage, codes):
        self._name = name
        self._port = port
        self._device_info_storage = device_info_storage
        self._device_info = device_info
        self._last_device_info_update = 0
        self._codes_storage = codes_storage
        self._codes = codes
        self._available = False
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
        return self._device_info

    @property
    def supported_features(self):
        return RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND

    async def async_will_remove_from_hass(self):
        _LOGGER.debug("Removing device from Home Assistant...")
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
            # compare with the previous device info
            if self._device_info != device_info:
                _LOGGER.info("Device info changed: %s", device_info)
                self._device_info = device_info
                await self._device_info_storage.async_save(self._device_info)
            self._available = True
        except Exception as e:
            _LOGGER.error("Failed to update Flipper device info, exception %s: %s", type(e), e, exc_info=True)
            self._available = False

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        raise HomeAssistantError("Turning on is not supported for this device.")

    async def async_turn_off(self, **kwargs):
        """Turn the device off."""
        raise HomeAssistantError("Turning off is not supported for this device.")

    async def async_send_command(self, command, **kwargs):
        """Send a list of commands to a device."""
        device = kwargs.get(ATTR_DEVICE, None)
        repeat = kwargs.get(ATTR_NUM_REPEATS, 1)
        repeat_delay = kwargs.get(ATTR_DELAY_SECS, 0)
        hold = kwargs.get(ATTR_HOLD_SECS, 0)
        
        if hold != 0:
            raise NotImplementedError("Hold time is not supported.")
        
        try:
            for n in range(repeat):
                for cmd in command:
                    if device:
                        if not device in self._codes:
                            raise KeyError(f"Device '{device}' not found in the codes storage.")
                        if not cmd in self._codes[device]:
                            raise KeyError(f"Command '{cmd}' not found in the codes storage for device '{device}'.")
                        code = self._codes[device][cmd]
                        _LOGGER.debug("Sending command '%s' for device '%s', code: %s", cmd, device, code)
                    else:
                        code = cmd
                        _LOGGER.debug("Sending command, code: '%s'", code)
                    pulses = rc_auto_encode(code)
                    _LOGGER.debug("Command pulses: %s", pulses)
                    await self._device.send_ir(pulses)
                    if n < repeat - 1 and repeat_delay > 0:
                        await asyncio.sleep(repeat_delay)
            if not self._available:
                self._available = True
                self.schedule_update_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to send command, exception %s: %s", type(e), e, exc_info=True)
            raise HomeAssistantError(str(e))

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
            if command_type != "ir": raise NotImplementedError(f'Unknown command type "{command_type}", only "ir" is supported.')
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

        if not device in self._codes:
            raise HomeAssistantError(f"Device '{device}' not found in the codes storage.")

        deleted = False
        for command in commands:
            if device in self._codes and command in self._codes[device]:
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
