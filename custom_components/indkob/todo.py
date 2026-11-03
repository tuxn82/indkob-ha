"""Indkøbslisten som HA to-do-entitet."""
from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IndkobConfigEntry
from .const import DOMAIN
from .shopping_list import COMPLETED, NEEDS_ACTION, Item, ShoppingList


async def async_setup_entry(
    hass: HomeAssistant, entry: IndkobConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ShoppingListEntity(entry, entry.runtime_data.shopping_list)])


def _status(s: TodoItemStatus | None) -> str:
    return COMPLETED if s == TodoItemStatus.COMPLETED else NEEDS_ACTION


class ShoppingListEntity(TodoListEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, entry: IndkobConfigEntry, shopping_list: ShoppingList) -> None:
        self._list = shopping_list
        self._attr_unique_id = f"{entry.entry_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Indkøb",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._list.add_listener(self.async_write_ha_state))

    @property
    def todo_items(self) -> list[TodoItem]:
        return [self._to_todo(i) for i in self._list.items]

    @staticmethod
    def _to_todo(item: Item) -> TodoItem:
        return TodoItem(
            uid=item.uid,
            summary=item.summary,
            status=TodoItemStatus.COMPLETED if item.status == COMPLETED else TodoItemStatus.NEEDS_ACTION,
            description=item.description,
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        qty, name = Item.parse_summary(item.summary or "")
        if not name:
            return
        self._list.add(name, qty, note=item.description or "")

    async def async_update_todo_item(self, item: TodoItem) -> None:
        self._list.update_from_todo(
            item.uid or "", item.summary or "", _status(item.status), item.description
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._list.delete(uids)

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        self._list.move(uid, previous_uid)
