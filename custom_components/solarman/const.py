import types
import struct

from datetime import timedelta as td

DOMAIN = "solarman"

IP_BROADCAST = "<broadcast>"
IP_ANY = "0.0.0.0"

PORT_ANY = 0

DISCOVERY_PORT = 48899
DISCOVERY_TIMEOUT = 1.0
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]
DISCOVERY_RECV_MESSAGE_SIZE = 1024

COMPONENTS_DIRECTORY = "custom_components"

LOOKUP_DIRECTORY = "inverter_definitions"
LOOKUP_DIRECTORY_PATH = f"{COMPONENTS_DIRECTORY}/{DOMAIN}/{LOOKUP_DIRECTORY}/"
LOOKUP_CUSTOM_DIRECTORY_PATH = f"{COMPONENTS_DIRECTORY}/{DOMAIN}/{LOOKUP_DIRECTORY}/custom/"

CONF_SERIAL = "serial"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_LOOKUP_FILE = "lookup_file"
CONF_ADDITIONAL_OPTIONS = "additional_options"
CONF_MPPT = "mppt"
CONF_PHASE = "phase"
CONF_BATTERY_NOMINAL_VOLTAGE = "battery_nominal_voltage"
CONF_BATTERY_LIFE_CYCLE_RATING = "battery_life_cycle_rating"
CONF_MB_SLAVE_ID = "mb_slave_id"

DEFAULT_TABLE = {
    "name": "Inverter",
    CONF_HOST: "",
    CONF_PORT: 8899, 
    CONF_MB_SLAVE_ID: 1,
    CONF_LOOKUP_FILE: "Auto",
    CONF_MPPT: 4,
    CONF_PHASE: 3,
    CONF_BATTERY_NOMINAL_VOLTAGE: 48,
    CONF_BATTERY_LIFE_CYCLE_RATING: 6000,
    "register_update_interval": 60,
    "is_single_code": False,
    "registers_code": 0x03,
    "registers_min_span": 25,
    "registers_max_size": 125,
    "digits": 6
}

AUTODETECTION_REDIRECT_TABLE = ["deye_string.yaml", "deye_hybrid.yaml", "deye_micro.yaml", "deye_4mppt.yaml", "deye_2mppt.yaml", "deye_sg04lp3.yaml", "deye_sg01hp3.yaml"]
AUTODETECTION_CODE_DEYE = 0x03
AUTODETECTION_REQUEST_DEYE = (AUTODETECTION_CODE_DEYE, 0x00, 0x16)
AUTODETECTION_TYPE_DEYE = (AUTODETECTION_CODE_DEYE, 0x00)
AUTODETECTION_TABLE_DEYE = { (0x0002, 0x0200): ("deye_string.yaml", 0x12), (0x0003, 0x0300): ("deye_hybrid.yaml", 18), (0x0004, 0x0400): ("deye_micro.yaml", 18), (0x0005, 0x0500): ("deye_sg04lp3.yaml", 0x16), (0x0006, 0x0007, 0x0600, 0x0008, 0x0601): ("deye_sg01hp3.yaml", 0x16) }

PROFILE_REDIRECT_TABLE = { "deye_4mppt.yaml": "deye_micro.yaml", "deye_2mppt.yaml": "deye_micro.yaml", "sofar_hyd3k-6k-es.yaml": "sofar_hyd-es.yaml", "hyd-zss-hp-3k-6k.yaml": "zcs_azzurro-hyd-zss-hp.yaml", "solis_1p8k-5g.yaml": "solis_1p-5g.yaml" }

STATE_SENSORS = [{"name": "Connection", "artificial": "state", "platform": "binary_sensor"}, {"name": "Update Interval", "artificial": "interval"}]

CONTROL_CODE = types.SimpleNamespace()
CONTROL_CODE.REQUEST = struct.pack("<H", 0x4510)
CONTROL_CODE.RESPONSE = struct.pack("<H", 0x1510)

AUTO_RECONNECT = True

# Data are requsted in most cases in different invervals:
# - from 5s for power sensors for example (deye_sg04lp3, ..)
# - up to 5m (deye_sg04lp3, ..) or 10m (kstar_hybrid, ..) for static valus like Serial Number, etc.
#
# Changing of this value does not affects the amount of stored data by HA in any way
# HA's Recorder is controlling that using its sampling rate (default is 5m)
# On the contrary changing this value can break:
# - Request scheduling according "update_interval" properties set in profiles
# - Inverter configuring flows
# - Behavior of services
#
TIMINGS_INTERVAL = 5
TIMINGS_INTERVAL_SCALE = 1
TIMINGS_UPDATE_INTERVAL = td(seconds = TIMINGS_INTERVAL * TIMINGS_INTERVAL_SCALE)
TIMINGS_UPDATE_TIMEOUT = TIMINGS_INTERVAL * 6
TIMINGS_SOCKET_TIMEOUT = TIMINGS_INTERVAL * 4 - 1
TIMINGS_WAIT_SLEEP = 0.2
TIMINGS_WAIT_FOR_SLEEP = 1

# Constants also tied to TIMINGS_INTERVAL to ensure maximum synergy
ACTION_ATTEMPTS = 5
ACTION_ATTEMPTS_MAX = ACTION_ATTEMPTS * 6

ATTR_FRIENDLY_NAME = "friendly_name"
ATTR_MPPT = "mppt"
ATTR_PHASE = "l"

REQUEST_UPDATE_INTERVAL = "update_interval"
REQUEST_MIN_SPAN = "min_span"
REQUEST_MAX_SIZE = "max_size"
REQUEST_CODE = "code"
REQUEST_CODE_ALT = "mb_functioncode"
REQUEST_START = "start"
REQUEST_END = "end"

CODE = types.SimpleNamespace()
CODE.READ_COILS = 1
CODE.READ_DISCRETE_INPUTS = 2
CODE.READ_HOLDING_REGISTERS = 3
CODE.READ_INPUT = 4
CODE.WRITE_SINGLE_COIL = 5
CODE.WRITE_HOLDING_REGISTER = 6
CODE.WRITE_MULTIPLE_COILS = 15
CODE.WRITE_MULTIPLE_HOLDING_REGISTERS = 16

SERVICES_PARAM_DEVICE = "device"
SERVICES_PARAM_REGISTER = "register"
SERVICES_PARAM_QUANTITY = "quantity"
SERVICES_PARAM_VALUE = "value"
SERVICES_PARAM_VALUES = "values"
SERVICES_PARAM_WAIT_FOR_ATTEMPTS = "wait_for_attempts"

SERVICE_READ_HOLDING_REGISTERS = "read_holding_registers"
SERVICE_READ_INPUT_REGISTERS = "read_input_registers"
SERVICE_WRITE_HOLDING_REGISTER = "write_holding_register"
SERVICE_WRITE_MULTIPLE_HOLDING_REGISTERS = "write_multiple_holding_registers"

DATETIME_FORMAT = "%y/%m/%d %H:%M:%S"
TIME_FORMAT = "%H:%M"