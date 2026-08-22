"""Constants for the Nespresso integration."""

from datetime import timedelta

DOMAIN = "nespresso"
NESPRESSO_SERVICE_UUID = "06aa1940-f22a-11e3-9daa-0002a5d5c51b"

SERVICE_COFFEE = "coffee"
SERVICE_CAPS = "caps"

ATTR_BREW_TEMPERATURE = "brew_temp"
ATTR_BREW_TYPE = "brew_type"
ATTR_COFFEE_ML = "coffee_ml"
ATTR_WATER_ML = "water_ml"
ATTR_CAPS = "caps"

DEFAULT_BREW_TEMPERATURE = "medium"
DEFAULT_BREW_TYPE = "lungo"

SCAN_INTERVAL = timedelta(seconds=60)

# Keep this list outside the entity platform so config-entry migration can run
# before the sensor platform is loaded.
SENSOR_KEYS: tuple[str, ...] = (
    "state",
    "water_is_empty",
    "descaling_needed",
    "capsule_mechanism_jammed",
    "water_fresh",
    "descaling_counter",
    "caps_number",
    "slider",
    "water_hardness",
)
