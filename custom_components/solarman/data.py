from __future__ import annotations

from logging import getLogger

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import split_entity_id, callback
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntry

from .common import slugify
from .coordinator import Coordinator

type SolarmanConfigEntry = ConfigEntry[Coordinator]

_LOGGER = getLogger(__name__)

@callback
def migrate_unique_ids(config_entry: SolarmanConfigEntry, registry: EntityRegistry, entity_entry: RegistryEntry):
    entity_name = entity_entry.original_name if entity_entry.has_entity_name or not entity_entry.original_name else entity_entry.original_name.replace(config_entry.runtime_data.device.config.name, '').strip()
    if entity_entry.unique_id != (unique_id := slugify(config_entry.entry_id, entity_name, split_entity_id(entity_entry.entity_id)[0])):
        if conflict_entity_id := registry.async_get_entity_id(entity_entry.domain, entity_entry.platform, unique_id):
            _LOGGER.debug(f"Unique id '{unique_id}' is already in use by '{conflict_entity_id}'")
            return None
        _LOGGER.debug(f"Migrating unique_id for {entity_entry.entity_id} entity from '{entity_entry.unique_id}' to '{unique_id}]'")
        return { "new_unique_id": entity_entry.unique_id.replace(entity_entry.unique_id, unique_id) }
    return None
