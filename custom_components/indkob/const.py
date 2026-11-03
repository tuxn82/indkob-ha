"""Konstanter for Indkøb-integrationen."""
from datetime import timedelta

DOMAIN = "indkob"
VERSION = "0.2.3"
CARD_BASE_URL = "/indkob"
CARD_FILES = ("indkob-scanner-card.js", "indkob-list-card.js")
UPDATE_INTERVAL = timedelta(minutes=10)

STORAGE_KEY = f"{DOMAIN}.list"
STORAGE_VERSION = 1

EVENT_ITEM_ADDED = "indkob_item_added"
EVENT_SENT = "indkob_sent_to_nemlig"

SERVICE_ADD_BY_BARCODE = "add_by_barcode"
SERVICE_SEND_TO_NEMLIG = "send_to_nemlig"
SERVICE_RESOLVE_ITEM = "resolve_item"
SERVICE_FORGET_MATCH = "forget_match"
SERVICE_SEARCH = "search"

ATTR_BARCODE = "barcode"
ATTR_QUANTITY = "quantity"
ATTR_ITEM = "item"
ATTR_PRODUCT_ID = "product_id"
ATTR_KEY = "key"
ATTR_DRY_RUN = "dry_run"
ATTR_QUERY = "query"
ATTR_LIMIT = "limit"

NOTIFICATION_ID = f"{DOMAIN}_unresolved"

CONF_AUTO_PICK = "auto_pick"
DEFAULT_AUTO_PICK = True
