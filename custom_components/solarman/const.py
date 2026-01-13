from re import compile
from datetime import timedelta
from aiohttp import BasicAuth, FormData

DOMAIN = "solarman"

IP_BROADCAST = "<broadcast>"
IP_ANY = "0.0.0.0"

PORT_ANY = 0

DISCOVERY_PORT = 48899
DISCOVERY_TIMEOUT = .5
DISCOVERY_MESSAGE = ["WIFIKIT-214028-READ".encode(), "HF-A11ASSISTHREAD".encode()]
DISCOVERY_INTERVAL = timedelta(minutes = 15)
DISCOVERY_CACHE = timedelta(seconds = 10)

COMPONENTS_DIRECTORY = "custom_components"

LOOKUP_DIRECTORY = "inverter_definitions"
LOOKUP_DIRECTORY_PATH = f"{COMPONENTS_DIRECTORY}/{DOMAIN}/{LOOKUP_DIRECTORY}/"
LOOKUP_CUSTOM_DIRECTORY_PATH = f"{COMPONENTS_DIRECTORY}/{DOMAIN}/{LOOKUP_DIRECTORY}/custom/"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TRANSPORT = "transport"
CONF_LOOKUP_FILE = "lookup_file"
CONF_ADDITIONAL_OPTIONS = "additional_options"
CONF_MOD = "mod"
CONF_MPPT = "mppt"
CONF_PHASE = "phase"
CONF_PACK = "pack"
CONF_BATTERY_NOMINAL_VOLTAGE = "battery_nominal_voltage"
CONF_BATTERY_LIFE_CYCLE_RATING = "battery_life_cycle_rating"
CONF_MB_SLAVE_ID = "mb_slave_id"

OLD_ = { "name": "name", "serial": "inverter_serial", "sn": "serial", "sn": "sn", CONF_HOST: "inverter_host", CONF_PORT: "inverter_port" }

LOGGER_AUTH = BasicAuth("admin", "admin")
LOGGER_SET = "hide_set_edit.html"
LOGGER_CMD = "do_cmd.html"
LOGGER_SUCCESS = "success.html"
LOGGER_RESTART = "restart.html"
LOGGER_RESTART_DATA = FormData({"HF_PROCESS_CMD": "RESTART"})
LOGGER_REGEX = {"setting_protocol": compile("var net_setting_pro.?=.?\"(.*)\";"), "setting_cs": compile("var net_setting_cs.?=.?\"(.*)\";"), "setting_port": compile("var net_setting_port.?=.?\"(.*)\";"), "setting_ip": compile("var net_setting_ip.?=.?\"(.*)\";"), "setting_timeout": compile("var net_setting_to.?=.?\"(.*)\";"), "mode": compile("var yz_tmode.?=.?\"(.*)\";"), "server": compile("var server_[a|b].?=.?\"(.*)\";"), "ap": compile("var apsta_mode.?=.?\"(.*)\";")}

SUGGESTED_VALUE = "suggested_value"
UPDATE_INTERVAL = "update_interval"
IS_SINGLE_CODE = "is_single_code"
REGISTERS_CODE = "registers_code"
REGISTERS_MIN_SPAN = "registers_min_span"
REGISTERS_MAX_SIZE = "registers_max_size"
DIGITS = "digits"

DEFAULT_ = {
    "name": "Inverter",
    CONF_HOST: "",
    CONF_PORT: 8899,
    CONF_TRANSPORT: "tcp",
    CONF_MB_SLAVE_ID: 1,
    CONF_LOOKUP_FILE: "Auto",
    CONF_MOD: 0,
    CONF_MPPT: 4,
    CONF_PHASE: 3,
    CONF_PACK: -1,
    CONF_BATTERY_NOMINAL_VOLTAGE: 48,
    CONF_BATTERY_LIFE_CYCLE_RATING: 6000,
    UPDATE_INTERVAL: 60,
    IS_SINGLE_CODE: False,
    REGISTERS_CODE: 0x03,
    REGISTERS_MIN_SPAN: 25,
    REGISTERS_MAX_SIZE: 125,
    DIGITS: 6
}

AUTODETECTION_DEYE_STRING = ((0x0002, 0x0200), "deye_string.yaml")
AUTODETECTION_DEYE_P1 = ((0x0003, 0x0300, 0x0103, 0x0104), "deye_hybrid.yaml")
AUTODETECTION_DEYE_MICRO = ((0x0004, 0x0400), "deye_micro.yaml")
AUTODETECTION_DEYE_4P3 = ((0x0005, 0x0500), "deye_p3.yaml")
AUTODETECTION_DEYE_1P3 = ((0x0006, 0x0007, 0x0600, 0x0008, 0x0601), "deye_p3.yaml")
AUTODETECTION_REDIRECT = [DEFAULT_[CONF_LOOKUP_FILE], AUTODETECTION_DEYE_STRING[1], "deye_p1.yaml", AUTODETECTION_DEYE_P1[1], AUTODETECTION_DEYE_MICRO[1], "deye_4mppt.yaml", "deye_2mppt.yaml", AUTODETECTION_DEYE_4P3[1], "deye_sg04lp3.yaml", "deye_sg01hp3.yaml"]
AUTODETECTION_CODE_DEYE = 0x03
AUTODETECTION_REGISTERS_DEYE = (0x0000, 0x0016)
AUTODETECTION_REQUEST_DEYE = (AUTODETECTION_CODE_DEYE, *AUTODETECTION_REGISTERS_DEYE)
AUTODETECTION_DEVICE_DEYE = (AUTODETECTION_CODE_DEYE, AUTODETECTION_REGISTERS_DEYE[0])
AUTODETECTION_TYPE_DEYE = (AUTODETECTION_CODE_DEYE, 0x0008)
AUTODETECTION_DEYE = { AUTODETECTION_DEYE_STRING[0]: (AUTODETECTION_DEYE_STRING[1], 0, 0x12), AUTODETECTION_DEYE_P1[0]: (AUTODETECTION_DEYE_P1[1], 0, 0x12), AUTODETECTION_DEYE_MICRO[0]: (AUTODETECTION_DEYE_MICRO[1], 0, 0x12), AUTODETECTION_DEYE_4P3[0]: (AUTODETECTION_DEYE_4P3[1], 0, 0x16), AUTODETECTION_DEYE_1P3[0]: (AUTODETECTION_DEYE_1P3[1], 1, 0x16) }
AUTODETECTION_BATTERY_REGISTERS_DEYE = (0x2712, 0x2712)
AUTODETECTION_BATTERY_REQUEST_DEYE = (AUTODETECTION_CODE_DEYE, *AUTODETECTION_BATTERY_REGISTERS_DEYE)
AUTODETECTION_BATTERY_NUMBER_DEYE = (AUTODETECTION_CODE_DEYE, AUTODETECTION_BATTERY_REGISTERS_DEYE[0])

PROFILE_REDIRECT = { "sofar_wifikit.yaml": "sofar_hybrid.yaml", "sofar_hyd-es.yaml": "sofar_hybrid.yaml:mod=1", "sofar_hyd3k-6k-es.yaml": "sofar_hybrid.yaml:mod=1", "hyd-zss-hp-3k-6k.yaml": "sofar_g3.yaml:pack=1", "solis_1p8k-5g.yaml": "solis_1p-5g.yaml", "solis_3p-4g+.yaml": "solis_3p-4g.yaml", "sofar_tlx-g3.yaml": "sofar_g3.yaml", "sofar_lsw3.yaml": "sofar_string.yaml", "zcs_azzurro-1ph-tl-v3.yaml": "sofar_string.yaml:mppt=1&l=1", "zcs_azzurro-hyd-zss-hp.yaml": "sofar_g3.yaml:pack=1", "zcs_azzurro-ktl-v3.yaml": "sofar_g3.yaml", "pylontech_Force-H.yaml": "pylontech_force.yaml:mod=1", "astro-energy_2mppt.yaml": "astro-energy_micro.yaml" }

PARAM_ = { CONF_MOD: CONF_MOD, CONF_MPPT: CONF_MPPT, CONF_PHASE: "l", CONF_PACK: CONF_PACK }

# Data are requsted in most cases in different invervals:
# - from 5s for power sensors for example (deye_sg04lp3, ..)
# - up to 5m (deye_sg04lp3, ..) or 10m (kstar_hybrid, ..) for static valus like Serial Number, etc.
#
# Changing of this value does not affects the amount of stored data beyond recorder's retention period
# On the contrary changing this value can break:
# - Request scheduling according "update_interval" properties set in profiles
# - Behavior of services
# - Configuration flow
#
TIMINGS_INTERVAL = 5
TIMINGS_INTERVAL_SCALE = 1
TIMINGS_UPDATE_INTERVAL = timedelta(seconds = TIMINGS_INTERVAL * TIMINGS_INTERVAL_SCALE)

REQUEST_UPDATE_INTERVAL = UPDATE_INTERVAL
REQUEST_MIN_SPAN = "min_span"
REQUEST_MAX_SIZE = "max_size"
REQUEST_CODE = "code"
REQUEST_CODE_ALT = "mb_functioncode"
REQUEST_START = "start"
REQUEST_END = "end"
REQUEST_COUNT = "count"

SERVICES_PARAM_DEVICE = "device"
SERVICES_PARAM_ADDRESS = "address"
SERVICES_PARAM_COUNT = "count"
SERVICES_PARAM_QUANTITY = "quantity"
SERVICES_PARAM_VALUE = "value"
SERVICES_PARAM_VALUES = "values"

SERVICE_READ_HOLDING_REGISTERS = "read_holding_registers"
SERVICE_READ_INPUT_REGISTERS = "read_input_registers"
SERVICE_WRITE_SINGLE_REGISTER = "write_single_register"
SERVICE_WRITE_MULTIPLE_REGISTERS = "write_multiple_registers"

SERVICES_PARAM_REGISTER = "register"
SERVICES_PARAM_QUANTITY = "quantity"
DEPRECATION_SERVICE_WRITE_SINGLE_REGISTER = "write_holding_register"
DEPRECATION_SERVICE_WRITE_MULTIPLE_REGISTERS = "write_multiple_holding_registers"

DATETIME_FORMAT = "%y/%m/%d %H:%M:%S"
TIME_FORMAT = "%H:%M"
