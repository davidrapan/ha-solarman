# ⚡ Solarman Stick Logger

[![License](https://img.shields.io/github/license/davidrapan/ha-solarman)](https://github.com/davidrapan/ha-solarman/blob/main/license)
[![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/davidrapan/ha-solarman/total)](https://github.com/davidrapan/ha-solarman/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/davidrapan/ha-solarman?label=commits)](https://github.com/davidrapan/ha-solarman/commits/main)
[![HACS Supported](https://img.shields.io/badge/HACS-Supported-03a9f4)](https://github.com/custom-components/hacs)
[![Community Forum](https://img.shields.io/badge/community-forum-03a9f4)](https://community.home-assistant.io/t/solarman-stick-logger-by-david-rapan)
[![Discussions](https://img.shields.io/badge/discussions-orange)](https://github.com/davidrapan/ha-solarman/discussions)
[![Wiki](https://img.shields.io/badge/wiki-8A2BE2)](https://github.com/davidrapan/ha-solarman/wiki)

#### 🠶 Signpost
- [Automations](https://github.com/davidrapan/ha-solarman/wiki/Automations)
- [Custom Sensors](https://github.com/davidrapan/ha-solarman/wiki/Custom-Sensors)
- [Dashboards](https://github.com/davidrapan/ha-solarman/wiki/Dashboards)
- [Documentation](https://github.com/davidrapan/ha-solarman/wiki/Documentation)
- [Naming Scheme](https://github.com/davidrapan/ha-solarman/wiki/Naming-Scheme)
- [Supported Devices](https://github.com/davidrapan/ha-solarman/wiki/Supported-Devices)

> [!IMPORTANT]  
> - Made for [🏡 Home Assistant](https://www.home-assistant.io/)  
> - Read about [✍ crucial changes & new features](https://github.com/davidrapan/ha-solarman/wiki#-changes)  
> - Built on asynchronous [pysolarmanv5](https://github.com/jmccrohan/pysolarmanv5) and supports Modbus TCP ([ESP](https://github.com/davidrapan/esphome-modbus_bridge), [Waveshare](https://www.waveshare.com/wiki/RS485_TO_ETH_(B)), [Ethernet logger](https://www.solarmanpv.com/download/lse-3/), etc.)

> [!NOTE]  
> - If you are curious about what's planned next look into [🪧 Milestones](https://github.com/davidrapan/ha-solarman/milestones)  
> - Use [💬 Discussions](https://github.com/davidrapan/ha-solarman/discussions) for 🙏 Q&A, 💡 Development Planning and 🎁 feature requests, etc. and [🚩 Issues](https://github.com/davidrapan/ha-solarman/issues) for 🐞 bug reporting and such...

## 🔌 Installation

[![🔌 Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=davidrapan&repository=ha-solarman&category=integration)

- Go to Home Assistant Community Store
- Search for and open **Solarman** repository
- Make sure it's the right one (using displayed frontpage) and click DOWNLOAD

### 🛠 Manually
- Copy the contents of `custom_components/` to `/homeassistant/custom_components/`

## ⚙️ Configuration

[![⚙️ Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=solarman)

- Go to Settings > Devices & services > Integrations
- Click ADD INTEGRATION, search for and select **Solarman**
- Enter the appropriate details (should be autodiscovered under most circumstances) and click SUBMIT

## 👤 Contributors
<a href="https://github.com/davidrapan/ha-solarman/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=davidrapan/ha-solarman" />
</a>
<br>
<br>
<div align="right">Inspired by <a href="https://github.com/StephanJoubert/home_assistant_solarman">Stephan Joubert's Solarman</div>
