# Deye SUN-30K-SG02HP3-EU-AM3

Select `deye_sg02hp3_30k.yaml` explicitly for this model. It is a standalone
three-phase, three-MPPT HV profile, derived from `deye_p3.yaml`. It preserves
entity names and keys and does not redirect to or depend on another YAML file.

## Units and limits

- Battery voltage and voltage settings use **0.1 V per register unit**.
- Battery settings use **160–700 V**, matching the manufacturer's battery input
  range. The corresponding raw limits are **1600–7000**. Settings that already
  permit zero, including the six Program Voltage thresholds, continue to do so.
- Battery maximum, grid and generator charging/discharging current settings are
  limited to **75 A**. This does not change the interpretation of BMS attributes.
- HV power settings use the existing **10 W** register resolution; other current,
  temperature, SOC, AC/PV voltage and cell-voltage conversions remain specific to
  their registers. Only three PV trackers contribute to totals and power losses.
- The writable **Max Solar Power** setting uses register `0x0154` and 10 W steps.
  Its entity ID remains `number.solarman_pv_power` to preserve existing references;
  the local display name distinguishes it from the measured PV Power sensor.

The shared `deye_p3.yaml` supports additional LV/HV models and retains its generic
limits. Its eight voltage minima are now `[3800, 380]`: 38 V with either the LV
0.01 or HV 0.1 scale. Its LV limits and energy modifier meanings are unchanged.

## Energy firmware variants

This profile defaults to firmware reporting whole-kWh counters. This behavior was
checked against an owner's display comparison on control firmware `1134`.
Firmware numbers alone are not a reliable way to infer a register's energy unit;
compare a nonzero counter with the inverter display or app before choosing a
variant for another installation.

| Additional options: Modifier | Direct energy unit | Raw `27` |
| --- | --- | --- |
| **0 (default)** | 1 kWh | 27 kWh |
| **1 (legacy)** | 0.1 kWh | 2.7 kWh |
| **2** | 1 kWh | 27 kWh |

The YAML uses `scale: [1, 0.1, 1]`. This applies to all 14 direct energy counters
and the two losses calculated from raw energy registers. Other derived sensors
consume the corrected values. Battery capacity, current, SOC and voltage are not
multiplied by the energy factor. The modifier does not switch this profile to LV.

Unlike the generic profile, this model-specific filename does not invoke model
autodetection. Three trackers are fixed in the mapping, even if the MPPT option
has its default larger value. Configure the optional number of battery packs
explicitly if you need the per-pack BMS data; the pack count is separate from the
single physical battery input.

The nominal battery voltage and expected cycle life remain battery-specific
integration options for estimates; this profile does not assume a universal
nominal voltage for every HV bank.

For a future installation, select the profile on the existing integration entry
to retain its identity. Existing writable entities are included, as in the
upstream profile. Selecting/reloading an integration may interact with existing
automations; this contribution was validated without installing it on the
owner's Home Assistant or executing any inverter writes. It does not migrate or
rewrite recorded energy statistics.

## Offline verification

```sh
python -m pip install PyYAML==6.0.3
python -B tools/test_deye_profiles.py -v
```

The tests run the actual `ParameterParser`, preprocessing helpers and number
encoding method without importing integration startup code. HA's ASCII slugifier
and asynchronous local YAML loading are isolated; the number writer uses an
`AsyncMock` transport. No network connections, physical writes or live Home
Assistant are required. Public register fixtures are synthetic.

Coverage includes low HV thresholds, raw/displayed bounds, LV compatibility,
energy variants and losses, unsigned 16/32-bit counters and word order, three-MPPT
totals, preserved entity keys, optional zero thresholds, 75 A limits and voltage
step round trips. Scaled number encoding uses decimal arithmetic so `160.1 / 0.1`
produces register `1601`, rather than truncating a binary floating-point result
to `1600`. Integer truncation for values between register steps is retained.

References: [Deye specifications](https://www.deyeinverter.com/product/three-phase-high-voltage-hybrid-inverter/sun25-29-9-30ksg02hp3euam3.html),
[HV limit discussion #768](https://github.com/davidrapan/ha-solarman/issues/768),
[energy scaling discussion #782](https://github.com/davidrapan/ha-solarman/issues/782),
[model support request #1097](https://github.com/davidrapan/ha-solarman/issues/1097).
