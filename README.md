# 🌧️ Rainfall Monitor — Enhanced Edition
## Setup & Run Guide

---

## Installation

```bash
pip install requests pandas streamlit numpy folium
```

> **Note:** `folium` is required for the Map tab (EXT-4).
> The base experiment only needs `requests pandas streamlit`.

---

## Quick Start

### 1. Add your API key
Open `weather_monitor_enhanced.py`, line 18:
```python
API_KEY = "paste_your_key_here"
```
Or just enter it in the sidebar when the app is running.

Get a free key at: https://openweathermap.org/api

### 2. Run the dashboard
```bash
streamlit run weather_monitor_enhanced.py
```

---

## Features by Tab

| Tab | Feature | Extension |
|-----|---------|-----------|
| 🏙️ Single City | Live weather + alert + history + prediction | Core + EXT-3 |
| 🌐 Multi-City | Compare up to 10+ cities at once | EXT-1 |
| 🗺️ Map View | Folium interactive map, colour-coded markers | EXT-4 |
| 📝 Alert Log | Full alert history with stats | Core |

---

## Email Alerts Setup (EXT-2)

To receive email alerts when a RED condition triggers:

1. Enable "Email Alerts" in the sidebar
2. Enter your Gmail address as sender
3. For password — **do NOT use your Google account password**.  
   Instead, create a **Gmail App Password**:
   - Google Account → Security → 2-Step Verification → App Passwords
   - Generate a password for "Mail" → use that 16-character code
4. Enter the recipient email

---

## Testing All Alert Levels

Use the **Demo Mode** (visible when no API key is set) to test:

| Slider value | Alert level | What to verify |
|-------------|-------------|---------------|
| `5.0 mm/h`  | 🟢 Green  | Banner is green, no log entry |
| `15.0 mm/h` | 🟡 Yellow | Banner is yellow, log entry written |
| `25.0 mm/h` | 🔴 Red    | Banner is red, log entry + email sent |

---

## Deliverables

| File | Status |
|------|--------|
| `weather_monitor_enhanced.py` | ✅ Main app |
| `alert_log.txt` | ✅ Auto-generated |
| `prompt_log_enhanced.md` | ✅ 10 interactions documented |
| `rainfall_history.json` | ✅ Auto-generated on first fetch |
| Dashboard screenshot | 📸 Take manually after running |
