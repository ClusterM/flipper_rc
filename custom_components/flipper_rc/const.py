"""Constants for the Flipper Zero Remote Control integration."""

DOMAIN = "flipper_rc"

NOTIFICATION_TITLE = "Flipper Zero Remote Control"

DEFAULT_FRIENDLY_NAME = "Flipper Zero Remote Control"
DEFAULT_PORT_LINUX = "/dev/ttyACM0"
DEFAULT_PORT_WINDOWS = "COM1"

CODE_STORAGE_VERSION = 1
CODE_STORAGE_CODES = f"{DOMAIN}_codes"

DEVICE_INFO_STORAGE_VERSION = 1
DEVICE_INFO_STORAGE = f"{DOMAIN}_device_info"
