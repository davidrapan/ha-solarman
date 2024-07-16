# ⚡ Solarman Stick Logger integration

[![Stable](https://img.shields.io/github/release/davidrapan/ha-solarman.svg)](https://github.com/davidrapan/ha-solarman/releases/latest)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/davidrapan/ha-solarman.svg?label=commits)](https://github.com/davidrapan/ha-solarman/commits/main)
[![License](https://img.shields.io/github/license/davidrapan/ha-solarman.svg)](LICENSE)
[![HACS Supported](https://img.shields.io/badge/HACS-Supported-green.svg)](https://github.com/custom-components/hacs)
[![Discussions](https://img.shields.io/badge/community-discussions-brightgreen.svg)](https://github.com/davidrapan/ha-solarman/discussions)

> [!NOTE]  
> If you are curious about what's planned next look into [🪧 Milestones](https://github.com/davidrapan/ha-solarman/milestones)  
> Use [💬 Discussions](https://github.com/davidrapan/ha-solarman/discussions) for 🙏 Q&A and 💡 Development Planning, etc. and leave [🚩 Issues](https://github.com/davidrapan/ha-solarman/issues) for 🐞 bug reporting, 🎁 feature requests and such...  

> [!NOTE]  
> It's still 🚧 work in progress but currently very 🐎 stable 😉  
> *I mean at least for my device as I'm not able to* 🧪 *test it for any other so any* 🧍 *volunteers?* 😊  

> [!IMPORTANT]  
> This integration builds on and is heavily inspired by [@StephanJoubert](https://github.com/StephanJoubert/home_assistant_solarman) (but W/ decent amount of changes):
> - Using asynchronous part of [@jmccrohan](https://github.com/jmccrohan/pysolarmanv5) + small adjustments to the inner workings of the library itself
> - Fetching is implemented through DataUpdateCoordinator + incorporates many more up to date features of HA
> - Improved stability (no more disconnects and missing values)
> - Discovery and not just for configuration but also as part of initialization (i.e. adapts to changed IP)
> - New Inverter profiles features **See 'deye_sg04lp3.yaml' for examples*:
>   - Different registers can be requested in different intervals according to their 'update_interval' set in inverter definition file
>   - Registers which will be part of a request are decided dynamically (when missing from the inverter definition file)
>   - Added attribute type of a sensor which can be attached to any other sensor
>   - Added configuration for Battery Nominal Voltage and Battery Life Cycle Rating for calculating SOH and life cycles of the battery  
> - And many more fixes and improvements (while trying to fully preserve backward compatibility)

> [!WARNING]  
> It's note worthy that some names of the SG04LP3 sensors did change for different reasons (some were due to aestetics, etc.)  
> So look through the file and change them as you see fit manually before I'll make it available from the HA configuration.  
> One more thing.. It's not possible to use this integration side by side (with the same device) with the implementation from Stephan! It will override it.  
> TODO: Rest of the info... 😃  

## 🚀 Miscellaneous

Some might wonder why Energy Dashboard shows different(higher) Load Consumption than sensor like for example "Today(Daily) Load Consumption. And it's because the Energy Dashboard does it's own calculations by summing up Imported(Bought) and Produced energy which also includes consumption of the inverter itself + some AC/DC losses along the way."  

_So for those curious enough here is some insight..._  

#### Inverter power losses calculation [W]:
```
Power losses = Battery Power + PV1 Power + PV2 Power - Inverter Power
```

#### Total losses calculation [kWh]:
```
Total losses = Total Energy Imported(Bought) + Total Production + Total Battery Discharge - Total Energy Exported(Sold) - Total Battery Charge - Total Load Consumption
```

#### Today(Daily) losses calculation [kWh]:
```
Today(Daily) losses = Today(Daily) Energy Imported(Bought) + Today(Daily) Production + Today(Daily) Battery Discharge - Today(Daily) Energy Exported(Sold) - Today(Daily) Battery Charge - Today(Daily) Load Consumption
```

_To get value which is in Energy Dashboard as "Home Consumption" remove subtraction of Load Consumption from the above._  

## 🏭 Diagnostics

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
        state: "{{ max((states('sensor.update_ticker') | float - as_timestamp(states.sensor.inverter_connection_status.last_updated)) | round(0, 'ceil'), 0) }}"
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

## 🔨 Installation

[![🔌 Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=davidrapan&repository=ha-solarman&category=integration)

### 🪛 HACS (Manually)
- Follow the link [here](https://hacs.xyz/docs/faq/custom_repositories/)
- Add custom repository: https://github.com/davidrapan/ha-solarman
- Select type of the category: integration
- Find newly added Solarman, open it and then click on the DOWNLOAD button

### 🔧 Manually
- Copy the contents of 'custom_components/solarman' directory into the Home Assistant with exactly the same hirearchy withing the '/config' directory