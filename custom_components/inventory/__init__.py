"""Inventory component for Home Assistant."""

import logging
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from typing import Optional

_LOGGER = logging.getLogger(__name__)

DOMAIN = "inventory"
DEFAULT_CATEGORY = "Uncategorized"


async def async_setup(hass: HomeAssistant, config: ConfigType):
    component = EntityComponent(_LOGGER, DOMAIN, hass)

    """Set up the inventory platform."""

    def _generate_unique_id(name: str, category: Optional[str]) -> str:
        """Generate a unique ID for an inventory item based on its name and category."""
        return slugify(f"{category}_{name}") if category else slugify(name)

    def _entity_exists(unique_id: str) -> bool:
        """Check if the entity with the given unique ID already exists in the entities."""
        return unique_id in hass.data[DOMAIN]["entities"]

    def _get_entity_by_entity_id(entity_id: str) -> InventoryItem | None:
        return next(iter([e for e in hass.data[DOMAIN]["entities"].values() if e.entity_id == entity_id]), None)

    async def _update_stored_item(entity: InventoryItem) -> None:
        # Update the stored item data in the JSON file (Store)
        item_data = next(item for item in hass.data[DOMAIN]["items"] if item['unique_id'] == entity.unique_id)
        item_data["quantity"] = entity.state  # Update the quantity in the stored data
        await hass.data[DOMAIN]["store"].async_save(hass.data[DOMAIN]["items"])

    # Set up Store to store the inventory data
    store = Store(hass, 1, f"{DOMAIN}.json")

    # Load saved items from Store (JSON file)
    saved_items = await store.async_load() or []

    # Initialize internal storage in hass.data
    hass.data[DOMAIN] = {
        "store": store,
        "items": saved_items,
        "entities": {}  # key = unique_id, value = InventoryItem
    }

    # Restore saved entities and create corresponding InventoryItem objects
    entities = []
    for item in saved_items:
        entity = InventoryItem(**item, hass=hass)
        hass.data[DOMAIN]["entities"][entity.unique_id] = entity
        entities.append(entity)

    # Add restored entities to Home Assistant
    await component.async_add_entities(entities)

    async def handle_add(call: ServiceCall):
        """Handle adding items to an inventory."""
        name = call.data.get("name")
        quantity = call.data.get("quantity", 1)
        unit = call.data.get("unit")
        category = call.data.get("category", DEFAULT_CATEGORY)

        unique_id = _generate_unique_id(name, category)

        if _entity_exists(unique_id):
            raise ValueError(f"Item '{name}' in category '{category}' already exists")
        else:
            # Create a new InventoryItem and add it to Home Assistant
            entity = InventoryItem(unique_id, name, category, quantity, unit, hass)
            hass.data[DOMAIN]["entities"][unique_id] = entity
            await component.async_add_entities([entity])

            # Save item data in the store (JSON file)
            item_data = {"unique_id": unique_id, "name": name, "category": category, "quantity": quantity, "unit": unit}
            hass.data[DOMAIN]["items"].append(item_data)
            await store.async_save(hass.data[DOMAIN]["items"])

    async def handle_remove(call: ServiceCall):
        """Handle removing items from an inventory."""
        entity_id = call.data.get("entity_id")

        # Look up the entity by unique_id
        entity = _get_entity_by_entity_id(entity_id)
        if not entity:
            raise ValueError(f"Item '{entity.name}' in category '{entity.category}' does not exist")

        # Remove the entity from Home Assistant
        hass.states.async_remove(entity.entity_id)
        hass.data[DOMAIN]["entities"].pop(entity.unique_id, None)

        # Remove the item data from the store (JSON file)
        hass.data[DOMAIN]["items"] = [
            item for item in hass.data[DOMAIN]["items"]
            if _generate_unique_id(item["name"], item["category"]) != entity.unique_id
        ]
        await store.async_save(hass.data[DOMAIN]["items"])

    async def increase_quantity(call: ServiceCall):
        """Increase the quantity of an item."""
        entity_id = call.data.get("entity_id")
        quantity = call.data.get("quantity")
        entity = _get_entity_by_entity_id(entity_id)
        await entity.increase(quantity)
        await _update_stored_item(entity)

    async def decrease_quantity(call: ServiceCall):
        """Decrease the quantity of an item."""
        entity_id = call.data.get("entity_id")
        quantity = call.data.get("quantity")
        entity = _get_entity_by_entity_id(entity_id)
        await entity.decrease(quantity)
        await _update_stored_item(entity)

    # Register services
    hass.services.async_register(DOMAIN, "add_item", handle_add)
    hass.services.async_register(DOMAIN, "remove_item", handle_remove)
    hass.services.async_register(DOMAIN, "increase_quantity", increase_quantity)
    hass.services.async_register(DOMAIN, "decrease_quantity", decrease_quantity)

    return True


class InventoryItem(RestoreEntity):

    def __init__(self, unique_id, name, category, quantity, unit, hass):
        if unique_id is not None:
            self._unique_id = slugify(unique_id)
        else:
            self._unique_id = slugify(f"{category}_{name}" if category else f"{name}")

        self._state = quantity
        self._name = name
        self._category = category
        self._unit = unit
        self.hass = hass

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def state(self):
        return self._state

    @property
    def should_poll(self):
        return False

    @property
    def extra_state_attributes(self):
        return {
            'category': self._category
        }

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def hidden(self):
        return self._state is None

    async def increase(self, quantity):
        await self.set_state(self._state + quantity)

    async def decrease(self, quantity):
        if quantity > self._state:
            raise ValueError(f"Not enough quantity to decrease for '{self.name}'")
        else:
            await self.set_state(self._state - quantity)

    async def set_state(self, new_state):
        self._state = new_state
        self.async_write_ha_state()

    @property
    def category(self):
        return self._category
