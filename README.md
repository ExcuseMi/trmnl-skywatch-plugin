# trmnl-skywatch-plugin

<!-- PLUGIN_STATS_START -->
## <img src="assets/plugin-images/286469_icon.svg" alt="SkyWatch icon" width="32"/> [SkyWatch](https://trmnl.com/recipes/286469)

![Installs](https://trmnl-badges.gohk.xyz/badge/installs?recipe=286469) ![Forks](https://trmnl-badges.gohk.xyz/badge/forks?recipe=286469)

![SkyWatch screenshot](assets/plugin-images/286469_screenshot.png)

### Description
Real-time aircraft radar on your TRMNL display.<br />Live map updates every 15 minutes with all aircraft in a 50 nm radius.<br />36 type-specific icons — A320s, 747s, helicopters, gliders and more.<br />Major airports marked on the map.<br />Altitude shown by icon brightness and label shading.<br />Emergency squawks (hijack · no radio · Mayday) flagged automatically.<br /><br />Powered by <strong>airplanes.live</strong> · Icons by <a href="https://adsb-radar.com/" target="_blank">ADS-B Radar</a> · <a href="https://github.com/ExcuseMi/trmnl-skywatch-plugin/blob/main/ICONS.md" target="_blank">Icon guide</a>

---
<!-- PLUGIN_STATS_END -->

## Documentation

- [Aircraft Icon Reference](ICONS.md) — all aircraft icons, fallback categories, visual encoding guide, and titlebar icon options

## Aircraft Icons

Icons by [ADS-B Radar](https://adsb-radar.com/) — free SVG set used for on-map aircraft rendering.

### Specific Aircraft Types

| Icon | File | Aircraft |
|------|------|----------|
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a320.svg" width="40"/> | `a320.svg` | Airbus A318 / A319 / A320 / A321 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a330.svg" width="40"/> | `a330.svg` | Airbus A330 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a340.svg" width="40"/> | `a340.svg` | Airbus A340 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a380.svg" width="40"/> | `a380.svg` | Airbus A380 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b737.svg" width="40"/> | `b737.svg` | Boeing 737 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b747.svg" width="40"/> | `b747.svg` | Boeing 747 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b767.svg" width="40"/> | `b767.svg` | Boeing 767 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b777.svg" width="40"/> | `b777.svg` | Boeing 777 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b787.svg" width="40"/> | `b787.svg` | Boeing 787 Dreamliner |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/cessna.svg" width="40"/> | `cessna.svg` | Cessna (C172, C152, C182, …) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/crjx.svg" width="40"/> | `crjx.svg` | Bombardier CRJ family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/dh8a.svg" width="40"/> | `dh8a.svg` | Bombardier Dash 8 / Q-Series |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/e195.svg" width="40"/> | `e195.svg` | Embraer E190 / E195 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/erj.svg" width="40"/> | `erj.svg` | Embraer ERJ-135 / 145 / 170 / 175 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f100.svg" width="40"/> | `f100.svg` | Fokker 70 / 100 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/md11.svg" width="40"/> | `md11.svg` | McDonnell Douglas MD-11 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/glf5.svg" width="40"/> | `glf5.svg` | Gulfstream G450 / G550 / G650 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/fa7x.svg" width="40"/> | `fa7x.svg` | Dassault Falcon 7X / 8X / 50 / 900 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/learjet.svg" width="40"/> | `learjet.svg` | Learjet 35 / 45 / 55 / 60 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/c130.svg" width="40"/> | `c130.svg` | Lockheed C-130 Hercules / C-17 / C-5 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f15.svg" width="40"/> | `f15.svg` | F-15 / F-16 / F-18 / F-22 / F-35 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f5.svg" width="40"/> | `f5.svg` | Northrop F-5 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f11.svg" width="40"/> | `f11.svg` | General Dynamics F-111 |

### ADS-B Emitter Category Fallbacks

Used when no specific type match is found. Based on the ADS-B `category` field broadcast by the aircraft.

| Icon | File | Category | Description |
|------|------|----------|-------------|
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a0.svg" width="40"/> | `a0.svg` | A0 | No emitter category info |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a1.svg" width="40"/> | `a1.svg` | A1 | Light (< 15,500 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a2.svg" width="40"/> | `a2.svg` | A2 | Small (15,500–75,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a3.svg" width="40"/> | `a3.svg` | A3 | Large (75,000–300,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a4.svg" width="40"/> | `a4.svg` | A4 | High vortex large (e.g. B757) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a5.svg" width="40"/> | `a5.svg` | A5 | Heavy (> 300,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a6.svg" width="40"/> | `a6.svg` | A6 | High performance (> 5g acceleration or > 400 kt) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a7.svg" width="40"/> | `a7.svg` | A7 | Rotorcraft / helicopter |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b0.svg" width="40"/> | `b0.svg` | B0 | No emitter category info (non-motorised) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b1.svg" width="40"/> | `b1.svg` | B1 | Glider / sailplane |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b3.svg" width="40"/> | `b3.svg` | B3 | Parachutist / skydiver |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b4.svg" width="40"/> | `b4.svg` | B4 | Ultralight / hang-glider / paraglider |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/c0.svg" width="40"/> | `c0.svg` | C0–C3 | Surface vehicle / ground traffic |