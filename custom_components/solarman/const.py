from datetime import timedelta as td

DOMAIN = "solarman"
PLATFORMS: list[str] = ["sensor"]
SENSOR_PREFIX = "Solarman"

LOOKUP_DIRECTORY = "inverter_definitions"

CONF_INVERTER_DISCOVERY = "inverter_discovery"
CONF_INVERTER_HOST = "inverter_host"
CONF_INVERTER_PORT = "inverter_port"
CONF_INVERTER_SERIAL = "inverter_serial"
CONF_INVERTER_MB_SLAVE_ID = "inverter_mb_slave_id"
CONF_LOOKUP_FILE = "lookup_file"
CONF_BATTERY_NOMINAL_VOLTAGE = "battery_nominal_voltage"
CONF_BATTERY_LIFE_CYCLE_RATING = "battery_life_cycle_rating"
CONF_DISABLE_TEMPLATING = "disable_templating"

DEFAULT_NAME = "Inverter"
DEFAULT_DISCOVERY = True
DEFAULT_PORT_INVERTER = 8899
DEFAULT_INVERTER_MB_SLAVE_ID = 1
DEFAULT_LOOKUP_FILE = "deye_sg04lp3.yaml"
DEFAULT_BATTERY_NOMINAL_VOLTAGE = 48
DEFAULT_BATTERY_LIFE_CYCLE_RATING = 6000
DEFAULT_DISABLE_TEMPLATING = False

LOOKUP_FILES = [
    "deye_2mppt.yaml",
    "deye_4mppt.yaml",
    "deye_hybrid.yaml",
    "deye_sg04lp3.yaml",
    "deye_string.yaml",
    "kstar_hybrid.yaml",
    "sofar_g3hyd.yaml",
    "sofar_hyd3k-6k-es.yaml",
    "sofar_lsw3.yaml",
    "sofar_wifikit.yaml",
    "solis_1p8k-5g.yaml",
    "solis_3p-4g.yaml",
    "solis_hybrid.yaml",
    "solis_s6-gr1p.yaml",
    "zcs_azzurro-ktl-v3.yaml",
    "custom_parameters.yaml"
]

COORDINATOR_INTERVAL = 5
COORDINATOR_TIMEOUT = 30
COORDINATOR_UPDATE_INTERVAL = td(seconds = COORDINATOR_INTERVAL)
COORDINATOR_SOCKET_TIMEOUT = COORDINATOR_TIMEOUT / 2
COORDINATOR_QUERY_INTERVAL_DEFAULT = 60
COORDINATOR_QUERY_RETRY_ATTEMPTS = 4
COORDINATOR_QUERY_ERROR_SLEEP = 4

FLOAT_ROUND_TO = 6