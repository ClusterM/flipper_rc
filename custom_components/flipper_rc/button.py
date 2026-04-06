"""Button platform for Flipper Zero Sub-GHz saved files."""

import asyncio
import logging
import os

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Allow up to 5 seconds for the remote entity to be registered in hass.data
# during config entry setup before giving up on creating button entities.
REMOTE_ENTITY_READY_MAX_RETRIES = 25
REMOTE_ENTITY_READY_RETRY_DELAY_SECONDS = 0.2


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Sub-GHz file trigger buttons for a config entry."""
    _LOGGER.info("Setting up Sub-GHz buttons for entry %s", entry.entry_id)
    remote_entity = None
    for _ in range(REMOTE_ENTITY_READY_MAX_RETRIES):
        remote_entity = hass.data.get(DOMAIN, {}).get("remote_entities", {}).get(entry.entry_id)
        if remote_entity is not None:
            break
        await asyncio.sleep(REMOTE_ENTITY_READY_RETRY_DELAY_SECONDS)

    if remote_entity is None:
        _LOGGER.warning("Cannot create Sub-GHz buttons: remote entity not ready for entry %s", entry.entry_id)
        return

    # Recreate button set on each startup/reload to avoid duplicate stale entries.
    registry = er.async_get(hass)
    existing = [
        reg_entry
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id)
        if reg_entry.domain == "button"
    ]
    for reg_entry in existing:
        registry.async_remove(reg_entry.entity_id)
    if existing:
        _LOGGER.info("Removed %d existing Sub-GHz button entities before refresh", len(existing))

    files = []
    search_roots = [
        "/ext/subghz",
        "/ext/subghz/Saved",
        "/ext/subghz_playlist",
        "/ext/apps_data/subghz",
        "/ext",
    ]

    for root in search_roots:
        try:
            discovered = await remote_entity.async_list_subghz_files(root)
        except Exception as e:
            _LOGGER.debug("Cannot discover Sub-GHz files in %s on %s: %s", root, remote_entity.port, e)
            continue
        if discovered:
            _LOGGER.info("Discovered %d Sub-GHz files in %s for %s", len(discovered), root, remote_entity.port)
            files.extend(discovered)

    files = sorted(set(files))

    if not files:
        _LOGGER.warning("No Sub-GHz .sub files found in known roots on %s", remote_entity.port)
        return

    _LOGGER.info("Discovered %d Sub-GHz files for %s", len(files), remote_entity.port)

    entities = [
        FlipperSubGhzFileButton(remote_entity, path)
        for path in files
    ]
    async_add_entities(entities)


class FlipperSubGhzFileButton(ButtonEntity):
    """Button to replay one saved Sub-GHz file from Flipper storage."""

    def __init__(self, remote_entity, file_path):
        self._remote_entity = remote_entity
        self._port = remote_entity.port
        self._file_path = file_path

        base_name = os.path.splitext(os.path.basename(file_path))[0] or "subghz"
        self._attr_name = f"Sub-GHz {base_name}"
        self._attr_unique_id = f"{DOMAIN}_{self._port}_subghz_{slugify(file_path)}"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._port)},
        )

    @property
    def extra_state_attributes(self):
        return {
            "file_path": self._file_path,
            "command": f"subghz-file:path={self._file_path},repeat=1,antenna=0",
        }

    async def async_press(self):
        """Replay file when button is pressed."""
        _LOGGER.info("Sending Sub-GHz saved file: %s", self._file_path)
        try:
            await self._remote_entity.async_send_subghz_from_file(self._file_path, repeat=1, antenna=0)
        except Exception as e:
            _LOGGER.error("Failed to send Sub-GHz saved file %s: %s", self._file_path, e, exc_info=True)
            raise
