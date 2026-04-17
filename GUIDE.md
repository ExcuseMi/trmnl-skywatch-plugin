# SkyWatch Guide

[← Back to README](README.md)

SkyWatch shows a live radar of all aircraft within 50 nm (~90 km / 55 mi) of your location, updated every 15 minutes.

---

## Reading the Display

Each aircraft appears as an icon pointing in its direction of travel, with a label attached.

**Label lines:**
1. **Callsign** — flight number or registration (e.g. BAW123, G-ABCD)
2. Aircraft type description (e.g. Airbus A320, Robinson R44)
3. Altitude · Speed (e.g. 35,000 ft · 480 kt)

**Brightness** reflects altitude — brighter icons are higher up, darker icons are low or on the ground.

**Airports** are marked with a crosshair symbol and IATA code.

**Emergency squawks** are shown at full brightness with a dashed ring and a HIJACK / NORDO / MAYDAY label:

| Squawk | Meaning |
|--------|---------|
| 7500 | Hijack |
| 7600 | No radio (NORDO) |
| 7700 | Mayday / general emergency |

---

## How ADS-B Works

Every commercial aircraft continuously broadcasts its position, altitude, speed, and identity on 1090 MHz using an ADS-B transponder. A global network of volunteers runs ground receivers that pick up these signals and feeds them to [airplanes.live](https://airplanes.live), which powers SkyWatch.

---

## Aircraft Icons

Icons sourced from [ADS-B Radar](https://adsb-radar.com/). Matched first by ICAO type code, then by ADS-B emitter category.

### Specific Aircraft Types

| Icon | Aircraft |
|------|----------|
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a320.svg" width="40"/> | Airbus A318 / A319 / A320 / A321 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a330.svg" width="40"/> | Airbus A330 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a340.svg" width="40"/> | Airbus A340 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a380.svg" width="40"/> | Airbus A380 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b737.svg" width="40"/> | Boeing 737 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b747.svg" width="40"/> | Boeing 747 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b767.svg" width="40"/> | Boeing 767 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b777.svg" width="40"/> | Boeing 777 family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b787.svg" width="40"/> | Boeing 787 Dreamliner |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/cessna.svg" width="40"/> | Cessna (C172, C152, C182, …) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/crjx.svg" width="40"/> | Bombardier CRJ family |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/dh8a.svg" width="40"/> | Bombardier Dash 8 / Q-Series |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/e195.svg" width="40"/> | Embraer E190 / E195 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/erj.svg" width="40"/> | Embraer ERJ-135 / 145 / 170 / 175 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f100.svg" width="40"/> | Fokker 70 / 100 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/md11.svg" width="40"/> | McDonnell Douglas MD-11 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/glf5.svg" width="40"/> | Gulfstream G450 / G550 / G650 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/fa7x.svg" width="40"/> | Dassault Falcon 7X / 8X / 50 / 900 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/learjet.svg" width="40"/> | Learjet 35 / 45 / 55 / 60 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/c130.svg" width="40"/> | Lockheed C-130 Hercules / C-17 / C-5 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f15.svg" width="40"/> | F-15 / F-16 / F-18 / F-22 / F-35 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f5.svg" width="40"/> | Northrop F-5 |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/f11.svg" width="40"/> | General Dynamics F-111 |

### ADS-B Emitter Category Fallbacks

Used when no specific ICAO type match is found.

| Icon | Category | Description |
|------|----------|-------------|
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a0.svg" width="40"/> | A0 | No emitter category info |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a1.svg" width="40"/> | A1 | Light (< 15,500 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a2.svg" width="40"/> | A2 | Small (15,500–75,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a3.svg" width="40"/> | A3 | Large (75,000–300,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a4.svg" width="40"/> | A4 | High vortex large (e.g. B757) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a5.svg" width="40"/> | A5 | Heavy (> 300,000 lbs) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a6.svg" width="40"/> | A6 | High performance (> 5g or > 400 kt) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/a7.svg" width="40"/> | A7 | Rotorcraft / helicopter |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b0.svg" width="40"/> | B0 | No emitter category info (non-motorised) |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b1.svg" width="40"/> | B1 | Glider / sailplane |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b3.svg" width="40"/> | B3 | Parachutist / skydiver |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/b4.svg" width="40"/> | B4 | Ultralight / hang-glider / paraglider |
| <img src="assets/ADS-B_Radar_Free_Aircraft_SVG_Icons/c0.svg" width="40"/> | C0–C3 | Surface vehicle / ground traffic |