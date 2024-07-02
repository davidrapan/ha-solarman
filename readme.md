# Solarman integration

Integration for Solarman Stick Logger

> [!IMPORTANT]  
> This integration builds on and is heavily inspired by [@StephanJoubert](https://github.com/StephanJoubert/home_assistant_solarman) (but W/ decent amount of changes):
> - Using asynchronous part of [@jmccrohan](https://github.com/jmccrohan/pysolarmanv5) + small adjustments to the inner workings of the library itself
> - Fetching is implemented through DataUpdateCoordinator + incorporates many more up to date features of HA
> - Improved stability (no more disconnects and missing values)
>
> - Discovery and not just for configuration but also as part of initialization (i.e. adapts to changed IP)
>
> - Registers which are requested are decided dynamically (when missing from the inverter definition file)
> - Different registers can be requested in different intervals according to their 'update_interval' set in inverter definition file
>
> - Added attribute type of a sensor which can be attached to any other sensor
> - Added template sensors defined by simple formulas and parameters which are then evaluated during runtime
> - Added configuration for Battery Nominal Voltage and Battery Life Cycle Rating for calculating SOH of the battery
> - *All this new features can be seen utilized in the 'deye_sg04lp3.yaml'*
>
> - And many more fixes and improvements (while trying to fully preserve backward compatibility)

> [!WARNING]  
> Is note worthy that some names of the SG04LP3 sensors did change for different reasons (some were due to aestetics, etc.)  
> So look through the file and change them as you see fit manually before I'll make it available from the HA configuration.
>
> One more thing.. It's not possible to use this integration side by side (with the same device) with the implementation from Stephen! It will override it.

> [!NOTE]  
> It's still work in progress but I'm now over 3 weeks of uptime so it's really stable ;)  
>
> *I mean at least for my device as I'm not able to test it for any other so any volunteers?*
> 
> ...

> [!WARNING]  
> TODO: Rest of the info :-D

## Diagnostics

I was using during the development also this sensor bundle:
```
template:
  - trigger:
      - platform: time_pattern
        seconds: /1
    sensor:
      - name: "Update Ticker"
        unique_id: "update_ticker"
        state: "{{ '%0.6f' % as_timestamp(now()) }}"
        icon: "mdi:metronome-tick"
  - sensor:
      - name: "Inverter Device Since Last update"
        unique_id: "inverter_device_since_last_update"
        availability: "{{ has_value('sensor.inverter_connection_status') }}"
        state: "{{ (states('sensor.update_ticker') | float - as_timestamp(states.sensor.inverter_connection_status.last_updated)) | round(0, 'ceil') }}"
        state_class: "Measurement"
        device_class: "Duration"
        unit_of_measurement: "s"
      - name: "Inverter Device Last update"
        unique_id: "inverter_device_last_update"
        availability: "{{ has_value('sensor.inverter_connection_status') }}"
        state: "{{ (states.sensor.inverter_connection_status.last_updated | as_local).strftime('%H:%M:%S') }} ❘ {{ '%02d' % states('sensor.inverter_device_since_last_update') | int(0) }} seconds ago"
        icon: "mdi:calendar-clock"
```
Which provides informantion about how long it is since last update (with resolution of seconds).  
Maybe it will be useful for some, but since the stability of the polling improved a lot it's not really needed.

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=davidrapan&repository=ha-solarman&category=integration)

### HACS (Manually)
- Follow the link [here](https://hacs.xyz/docs/faq/custom_repositories/)
- Add custom repository: https://github.com/davidrapan/ha-solarman
- Select type of the category: integration
- Find newly added Solarman, open it and then click on the DOWNLOAD button

### Manually
- Copy the contents of 'custom_components/solarman' directory into the Home Assistant with exactly the same hirearchy withing the '/config' directory