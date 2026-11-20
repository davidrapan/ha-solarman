# SOFAR 4KTLM-G3

This profile is for a single-phase, non-hybrid 4KTLM-G3 with two MPPT inputs.
It was tested with an LSW3 logger running `LSW3_15_270A_1.68`, using Solarman V5,
Modbus slave 1 and function code 03. Other KTLM-G3 models have not been tested.

Select `sofar_4ktlm-g3.yaml` in the integration options. To install the profile
before it is included in a release, copy it to
`custom_components/solarman/inverter_definitions/custom/` and select
`custom/sofar_4ktlm-g3.yaml`. HACS preserves that custom directory on updates.
Existing installations should retain their config entry and matching sensor names
to retain entity IDs and recorder history; back up before replacing an integration.

The profile reads the complete aligned ranges `0x0400–0x042E`,
`0x0480–0x04AF`, `0x0580–0x0589` and `0x0680–0x069B`. Interior-start requests
returned nonstandard error frames with invalid Modbus CRC on the tested logger.
`requests_fine_control` keeps these ranges intact, including the unused words.
All four blocks are read on each coordinator refresh; the default sensor update
interval does not throttle explicit fine-control requests.

PV and AC power are in W, voltage in V, current in A and energy in kWh.
Energy counters use the low word first in each register list, as expected by
the parser. `Fault 1` through `Fault 12` expose raw G3 bitfields: zero means
no error. Legacy Sofar fault descriptions are not reused. This profile defines
no writable entities, battery/off-grid values or L2/L3 sensors.

The former module-temperature address is not included. The profile instead
exposes the G3 radiator-temperature register at `0x041A`.

Regression checks use synthetic samples, without serial numbers, IP addresses
or household telemetry:

```sh
python -m pip install PyYAML aiohttp aiofiles voluptuous
python -m unittest discover -s tests -v
```

The tests exercise the integration's actual parser, including block scheduling,
energy word order, scales, G3 status and raw faults. The Home Assistant imports
used for slug and device metadata are shimmed for standalone execution. Hardware
validation also requires checking live values and advancing connection timestamps.
Some logger delays remain possible; this profile does not change reconnection
behavior or relax CRC validation.
