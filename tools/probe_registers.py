#!/usr/bin/env python3
"""
Probe Modbus TCP registers on a hybrid inverter and check for plausible values.
Usage: python3 tools/probe_registers.py --host 192.168.178.134
"""

import os
import yaml
import struct
import argparse
from pymodbus.client import ModbusTcpClient

PROFILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "solarman",
    "inverter_definitions", "bexie_hybrid.yaml",
)

HOST = "192.168.178.134"
PORT = 502
UNIT = 1

# Registers to probe based on the Hybrid Modbus Protocol PDF
# (address, count, type, scale, unit, description)
REGISTERS = [
    # --- PV ---
    (0x1010, 1, "U16", 0.1,   "V",   "PV1 Voltage"),
    (0x1011, 1, "U16", 0.01,  "A",   "PV1 Current"),
    (0x1012, 2, "U32", 0.1,   "W",   "MPPT1 Power"),
    (0x1014, 1, "U16", 0.1,   "V",   "PV2 Voltage"),
    (0x1015, 1, "U16", 0.01,  "A",   "PV2 Current"),
    (0x1016, 2, "U32", 0.1,   "W",   "MPPT2 Power"),
    (0x1048, 2, "U32", 0.1,   "W",   "PV Total Power"),
    # --- Inverter ---
    (0x101C, 1, "S16", 1.0,   "°C",  "Inverter Temperature"),
    (0x101D, 1, "U16", 1.0,   "",    "Inverter Mode"),
    (0x1021, 2, "U32", 1.0,   "kWh", "Total Energy"),
    (0x1027, 2, "U32", 1.0,   "Wh",  "Today Energy"),
    (0x1037, 2, "S32", 0.1,   "W",   "Active Power"),
    # --- Grid ---
    (0x1300, 2, "S32", 0.1,   "W",   "Grid Power (Phase R)"),
    (0x131A, 1, "U16", 0.1,   "V",   "Grid Voltage L1"),
    (0x1338, 1, "U16", 0.01,  "Hz",  "Grid Frequency"),
    (0x1306, 2, "U32", 10.0,  "Wh",  "Grid Accumulated Import"),
    (0x1308, 2, "U32", 10.0,  "Wh",  "Grid Accumulated Export"),
    (0x1332, 2, "U32", 10.0,  "Wh",  "Today Import Energy"),
    (0x1334, 2, "U32", 10.0,  "Wh",  "Today Export Energy"),
    # --- Load ---
    (0x130A, 2, "S32", 0.1,   "W",   "Load Power (Phase R)"),
    (0x1310, 2, "U32", 10.0,  "Wh",  "Load Accumulated Energy"),
    (0x1336, 2, "U32", 10.0,  "Wh",  "Today Load Energy"),
    # --- Battery ---
    (0x2000, 1, "U16", 1.0,   "%",   "Battery SOC"),
    (0x2001, 1, "S16", 1.0,   "°C",  "Battery Temperature (PDF: 0x2001)"),
    (0x201B, 1, "U16", 1.0,   "°C",  "Battery Temperature (YAML: 0x201B)"),
    (0x2006, 1, "U16", 0.1,   "V",   "Battery Voltage"),
    (0x2007, 2, "S32", 0.01,  "A",   "Battery Current"),
    (0x2009, 2, "U32", 0.1,   "W",   "Battery Power (PDF: 0x2009, U32)"),
    (0x200A, 1, "S16", 0.1,   "W",   "Battery Power (YAML: 0x200A, S16)"),
    (0x200B, 2, "U32", 10.0,  "Wh",  "Battery Daily Charge Energy"),
    (0x200F, 2, "U32", 10.0,  "Wh",  "Battery Daily Discharge Energy"),
]


def decode(registers, rtype):
    if rtype == "U16":
        return registers[0]
    elif rtype == "S16":
        v = registers[0]
        return v if v < 0x8000 else v - 0x10000
    elif rtype == "U32":
        return (registers[0] << 16) | registers[1]
    elif rtype == "S32":
        v = (registers[0] << 16) | registers[1]
        return v if v < 0x80000000 else v - 0x100000000
    return None


def plausible(value, rtype, unit, description):
    """Rough sanity checks — flag obviously bad values."""
    flags = []
    if rtype in ("U16", "U32") and value == 0xFFFF:
        flags.append("MAX_U16 (likely N/A)")
    if rtype == "U32" and value == 0xFFFFFFFF:
        flags.append("MAX_U32 (likely N/A)")
    if "Voltage" in description and unit == "V":
        if not (0 < value < 1500):
            flags.append(f"out of range for voltage ({value}V)")
    if "Current" in description and unit == "A":
        if not (-200 < value < 200):
            flags.append(f"out of range for current ({value}A)")
    if "Frequency" in description:
        if not (45 < value < 65):
            flags.append(f"out of range for freq ({value}Hz)")
    if "Temperature" in description:
        if not (-20 < value < 120):
            flags.append(f"out of range for temp ({value}°C)")
    if "SOC" in description:
        if not (0 <= value <= 100):
            flags.append(f"out of range for SOC ({value}%)")
    return flags


def check_autodetection(client, profile_path=PROFILE_PATH):
    """Probe the block this profile's "autodetection" declares and check it decodes
    to the expected string, using the exact decode/normalize logic in common.py's
    lookup_profile (ASCII pairs, then strip to printable-ASCII range and strip())."""
    with open(profile_path) as f:
        profile = yaml.safe_load(f)

    auto = profile.get("autodetection")
    if not auto:
        print(f"No 'autodetection' block in {profile_path}")
        return

    code, start, end, equals = auto["code"], auto["start"], auto["end"], auto["equals"]
    expected = equals if isinstance(equals, list) else [equals]
    count = end - start + 1

    print(f"\nAutodetection probe: fc{code} @ 0x{start:04X}-0x{end:04X} ({count} regs)")
    rr = client.read_holding_registers(start, count=count)
    if rr.isError():
        print(f"  ERROR reading registers: {rr}")
        return

    print(f"  Raw registers: {[f'0x{r:04X}' for r in rr.registers]}")

    decoded = "".join(chr(r >> 8) + chr(r & 0xFF) for r in rr.registers)
    print(f"  Decoded (raw):  {decoded!r}")

    filtered = "".join(c for c in decoded if "\x20" <= c <= "\x7e").strip()
    print(f"  Decoded (filtered): {filtered!r}")

    if filtered in expected:
        print(f"  MATCH against {expected!r}")
    else:
        print(f"  NO MATCH against {expected!r} -- update 'equals' in {profile_path} to {filtered!r}")


def main():
    parser = argparse.ArgumentParser(description="Probe hybrid inverter Modbus registers")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", default=PORT, type=int)
    parser.add_argument("--unit", default=UNIT, type=int)
    args = parser.parse_args()

    client = ModbusTcpClient(args.host, port=args.port)
    if not client.connect():
        print(f"ERROR: Cannot connect to {args.host}:{args.port}")
        return

    print(f"\nConnected to {args.host}:{args.port} (unit {args.unit})\n")

    check_autodetection(client)

    print(f"\n{'Address':<10} {'Description':<42} {'Raw':>10}  {'Value':>12}  {'Notes'}")
    print("-" * 100)

    for addr, count, rtype, scale, unit, desc in REGISTERS:
        try:
            rr = client.read_holding_registers(addr, count=count)
            if rr.isError():
                print(f"0x{addr:04X}     {desc:<42} ERROR: {rr}")
                continue
            raw = decode(rr.registers, rtype)
            value = raw * scale
            flags = plausible(value, rtype, unit, desc)
            flag_str = "  ⚠ " + ", ".join(flags) if flags else ""
            print(f"0x{addr:04X}     {desc:<42} {raw:>10}  {value:>10.2f} {unit:<4}{flag_str}")
        except Exception as e:
            print(f"0x{addr:04X}     {desc:<42} EXCEPTION: {e}")

    client.close()
    print()


if __name__ == "__main__":
    main()
