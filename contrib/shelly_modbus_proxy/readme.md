# Shelly Modbus proxy

If you have a [Shelly](https://www.shelly.com/) with the [Modbus add-on](https://kb.shelly.cloud/knowledge-base/shelly-modbus-add-on) wired to your inverter's RS485/Modbus port, this transport lets ha-solarman talk to it directly over your local network instead of through a Solarman WiFi datalogger dongle. Useful if your dongle is flaky, unreliable, or you'd simply rather not depend on it.

It's a genuine alternative to a dongle, not a limited one: since it relays raw Modbus RTU frames, it supports the full read/write register set for whichever `inverter_definitions/*.yaml` profile you're using — not just a fixed subset of telemetry.

## Why not the existing `modbus_tcp`/`modbus_rtu` transports?

Those assume a real TCP/IP Modbus gateway (an ESP-based bridge, a Waveshare RS485-to-Ethernet adapter, etc.) that speaks Modbus over a raw TCP socket. A Shelly's scripting engine can't open a raw TCP server — it can only expose HTTP endpoints — so a Shelly-based bridge needs its own transport that speaks HTTP instead.

## Setup

1. On the Shelly, go to **Scripts**, create a new script, paste in [`proxy.js`](proxy.js), and start it. Note the script's **id** (shown in the script list).
2. In Home Assistant, configure the Solarman integration:
   - **Host**: the Shelly's IP address
   - **Port**: the script's id from step 1 (not a network port — reused here to avoid adding a new config field)
   - **Transport**: "Shelly Modbus proxy"
3. Save. ha-solarman will now poll through the Shelly instead of the dongle.

## Notes

- The proxy is stateless and register-agnostic — it just relays whatever Modbus RTU frame it's given and returns the raw response, so it works with any inverter brand/profile ha-solarman supports, not just Deye.
- If the Shelly is also running another script that uses the same UART (e.g. an existing local polling loop), only one Modbus transaction can be in flight at a time. The proxy returns `429 {"error":"busy"}` when that happens; ha-solarman's `shelly_modbus` transport retries transparently, so this is not normally visible.
- See [`deye_virtual_components.js`](deye_virtual_components.js) for an example of layering local virtual-component mirroring on top of the same proxy with zero extra UART traffic, by snooping on the requests ha-solarman already makes rather than polling independently.
