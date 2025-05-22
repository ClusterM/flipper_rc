"""Config flow for the Flipper Zero Remote Control integration."""

import logging
import voluptuous as vol
import os
import asyncio
from homeassistant.helpers.storage import Store
from .flipper_ir import FlipperIR

from .const import *

from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_NAME,
    CONF_PORT,
)

_LOGGER = logging.getLogger(__name__)

class FlipperZeroRCConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        # Default config
        self.config = {
            CONF_NAME: DEFAULT_FRIENDLY_NAME,
            CONF_PORT: DEFAULT_PORT_LINUX if os.name != 'nt' else DEFAULT_PORT_WINDOWS
        }
        self.auto_detected = False
        if os.path.exists("/dev/serial/by-id"):
            # Check for the first serial device
            for device in os.listdir("/dev/serial/by-id"):
                if "_Flipper_" in device:
                    self.config[CONF_PORT] = os.path.join("/dev/serial/by-id", device)
                    self.auto_detected = True
                    break

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        return await self.async_step_port()
    
    async def async_step_port(self, user_input=None):
        """Handle the port step."""
        errors = {}
        if user_input is not None:
            self.config[CONF_PORT] = user_input[CONF_PORT]
            try:
                if unique_id in self._async_current_ids():
                    return self.async_abort(reason="already_configured")
                # Test the connection
                device = FlipperIR(self.config[CONF_PORT])
                await device.open()
                # read the device info
                device_info = await device.get_device_info()
                unique_id = f"{DOMAIN}_{self.config[CONF_PORT]}"
                # Store the device info
                store = Store(self.hass, DEVICE_INFO_STORAGE_VERSION, f"{DEVICE_INFO_STORAGE}_{self.config[CONF_PORT]}")
                await store.async_save(device_info)
                await self.async_set_unique_id(unique_id)
                return self.async_create_entry(title=self.config[CONF_NAME], data=self.config)
            except OSError as e:
                if e.errno == 1 or e.errno == 13:
                    errors["base"] = "port_access_denied"
                elif e.errno == 2:
                    errors["base"] = "port_not_found"
                elif e.errno == 5:
                    errors["base"] = "port_io_error"
                else:
                    errors["base"] = "port_unknown_error"
            except asyncio.TimeoutError:
                errors["base"] = "port_timeout"
            except Exception as e:
                errors["base"] = "unkown"
                _LOGGER.error("Unknown error: %s", e, exc_info=True)
            return await self.async_step_config()
        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=self.config[CONF_PORT]): cv.string,
                vol.Required(CONF_NAME, default=self.config[CONF_NAME]): cv.string,
            }
        )
        step_name = "port"
        if self.auto_detected:
            step_name = "port_auto_detected"
        elif os.name == "nt":
            step_name = "port_windows"
        elif os.name == "posix":
            step_name = "port_linux"
        return self.async_show_form(
            step_id=step_name,
            errors=errors,
            data_schema=schema
        )
        
    async def async_step_port_auto_detected(self, user_input=None):
        """Handle the port step."""
        return await self.async_step_port(user_input)
    async def async_step_port_windows(self, user_input=None):
        """Handle the port step."""
        return await self.async_step_port(user_input)
    async def async_step_port_linux(self, user_input=None):
        """Handle the port step."""
        return await self.async_step_port(user_input)
