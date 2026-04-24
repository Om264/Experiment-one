# weather_monitor.py  (Enhanced Edition)
# Short-term Rainfall Forecasting & Alert System
# AI-Augmented Software Engineering | Experiment 1 — Smart Water Lab Series
#
# Extensions included:
#   [EXT-1] Multiple city monitoring & comparison
#   [EXT-2] Email notifications on RED alert
#   [EXT-3] Rainfall trend prediction (moving average + linear regression)
#   [EXT-4] Interactive map visualization with Folium
#
# Bug fixes vs original:
#   - Auto-refresh now uses session_state timer instead of blocking time.sleep()
#   - fetch_forecast() logs warnings instead of silently swallowing errors
#   - display_metrics() uses a WeatherReading dataclass instead of 7 positional args

import requests
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import time
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import folium

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
API_KEY          = "your_api_key_here"   # Replace with your OpenWeatherMap key
BASE_URL         = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL     = "https://api.openweathermap.org/data/2.5/forecast"
LOG_FILE         = "alert_log.txt"
HISTORY_FILE     = "rainfall_history.json"
REFRESH_INTERVAL = 300                   # seconds (5 minutes)

# Alert thresholds (mm/h) — Experiment Part 2 specification
THRESHOLD_YELLOW = 10.0
THRESHOLD_RED    = 20.0

# China Meteorological Administration intensity categories
CMA_CATEGORIES = [
    {"label": "Light",    "max": 2.5,           "color": "#28a745"},
    {"label": "Moderate", "max": 8.0,           "color": "#007bff"},
    {"label": "Heavy",    "max": 16.0,          "color": "#ffc107"},
    {"label": "Violent",  "max": float("inf"),  "color": "#dc3545"},
]

# [EXT-1] Default cities for multi-city monitoring
DEFAULT_CITIES = ["Beijing", "Shanghai", "Guangzhou", "Chengdu", "Wuhan"]

# API rate limiting: free tier allows 60 calls/min
# We track last call time per city to avoid hammering the API
_last_api_call: dict[str, float] = {}
API_MIN_INTERVAL = 2.0   # minimum seconds between calls for the same city


# ─────────────────────────────────────────────
# DATA CLASSES  (fixes the 7-argument smell)
# ─────────────────────────────────────────────

@dataclass
class WeatherReading:
    """Structured container for a single weather API response."""
    rainfall:    float
    temperature: float
    humidity:    int
    description: str
    city:        str
    country:     str
    lat:         float
    lon:         float
    timestamp:   str

@dataclass
class AlertStatus:
    """Alert level with display properties."""
    level:   str   # GREEN | YELLOW | RED
    label:   str
    color:   str   # foreground hex
    bg:      str   # background hex
    emoji:   str
    message: str


# ─────────────────────────────────────────────
# PART 1: API INTEGRATION
# ─────────────────────────────────────────────

def fetch_weather(city: str, api_key: str) -> Optional[WeatherReading]:
    """
    Fetch current weather from OpenWeatherMap /data/2.5/weather.

    Respects a minimum inter-call interval per city to avoid rate-limit errors
    (free tier: 60 calls/min).

    Returns a WeatherReading dataclass on success, None on any error.
    """
    # ── Rate limiting guard ───────────────────
    now = time.time()
    if city in _last_api_call:
        elapsed = now - _last_api_call[city]
        if elapsed < API_MIN_INTERVAL:
            time.sleep(API_MIN_INTERVAL - elapsed)
    _last_api_call[city] = time.time()

    params = {
        "q":     city,
        "appid": api_key,
        "units": "metric",   # Celsius & mm
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Rainfall: key 'rain' is absent when dry — that is expected behavior
        rain_1h = 0.0
        if "rain" in data:
            rain_1h = data["rain"].get("1h", 0.0)

        return WeatherReading(
            rainfall    = round(rain_1h, 2),
            temperature = data["main"]["temp"],
            humidity    = data["main"]["humidity"],
            description = data["weather"][0]["description"].capitalize(),
            city        = data["name"],
            country     = data["sys"]["country"],
            lat         = data["coord"]["lat"],
            lon         = data["coord"]["lon"],
            timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    except requests.exceptions.ConnectionError:
        st.error(f"❌ [{city}] Network error — could not connect to API.")
    except requests.exceptions.Timeout:
        st.error(f"❌ [{city}] Request timed out.")
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            st.error("❌ Invalid API key. Check your OpenWeatherMap key.")
        elif code == 404:
            st.error(f"❌ City '{city}' not found.")
        elif code == 429:
            st.warning(f"⚠️ [{city}] Rate limit hit — waiting 60 s before retry.")
            time.sleep(60)
        else:
            st.error(f"❌ [{city}] HTTP {code}: {e}")
    except Exception as e:
        st.error(f"❌ [{city}] Unexpected error: {e}")

    return None


def fetch_forecast(city: str, api_key: str) -> list[dict]:
    """
    Fetch 48-hour forecast (16 × 3h intervals) from /data/2.5/forecast.

    Returns list of {time, rainfall} dicts, or [] on any failure.
    Unlike the original, this logs a warning instead of silently hiding errors.
    """
    params = {"q": city, "appid": api_key, "units": "metric", "cnt": 16}
    try:
        r = requests.get(FORECAST_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        return [
            {
                "time":    item["dt_txt"],
                "rainfall": round(item.get("rain", {}).get("3h", 0.0) / 3, 2),
            }
            for item in data.get("list", [])
        ]
    except requests.exceptions.HTTPError as e:
        st.warning(f"⚠️ Forecast unavailable ({e.response.status_code}) — chart hidden.")
        return []
    except Exception as e:
        st.warning(f"⚠️ Forecast fetch failed: {e}")
        return []


# ─────────────────────────────────────────────
# PART 2: ALERT LOGIC
# ─────────────────────────────────────────────

def check_alert(rainfall: float) -> AlertStatus:
    """
    Map rainfall intensity (mm/h) to a three-level alert status.

    Thresholds per experiment Part 2:
        GREEN  : < 10 mm/h  — Normal
        YELLOW : 10–20 mm/h — Moderate, monitor
        RED    : ≥ 20 mm/h  — Heavy, ALERT
    """
    if rainfall < THRESHOLD_YELLOW:
        return AlertStatus("GREEN",  "Normal",           "#28a745", "#d4edda", "🟢",
                           "Rainfall within safe limits. No action required.")
    if rainfall < THRESHOLD_RED:
        return AlertStatus("YELLOW", "Moderate — Monitor", "#856404", "#fff3cd", "🟡",
                           "Moderate rainfall detected. Monitor conditions closely.")
    return AlertStatus("RED",    "Heavy — ALERT!",   "#721c24", "#f8d7da", "🔴",
                       "⚠️ HEAVY RAINFALL ALERT! Possible flood risk. Take precautions.")


def get_cma_category(rainfall: float) -> dict:
    """Return the CMA intensity category dict for a given rainfall rate."""
    for cat in CMA_CATEGORIES:
        if rainfall < cat["max"]:
            return cat
    return CMA_CATEGORIES[-1]


def log_alert(reading: WeatherReading, alert: AlertStatus) -> None:
    """
    Append YELLOW or RED alerts to alert_log.txt with timestamp.
    GREEN is not logged — it would flood the file with noise.
    """
    if alert.level == "GREEN":
        return

    entry = (
        f"[{reading.timestamp}] "
        f"CITY={reading.city} ({reading.country}) | "
        f"LEVEL={alert.level} | "
        f"RAINFALL={reading.rainfall:.2f} mm/h | "
        f"{alert.message}\n"
    )
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except IOError as e:
        st.warning(f"⚠️ Could not write alert log: {e}")


def save_to_history(reading: WeatherReading, alert_level: str) -> None:
    """Persist each reading to JSON history store (last 100 per city)."""
    history: dict = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = {}

    city_key = reading.city
    history.setdefault(city_key, [])
    history[city_key].append({
        "timestamp": reading.timestamp,
        "rainfall":  reading.rainfall,
        "alert":     alert_level,
    })
    history[city_key] = history[city_key][-100:]   # keep last 100

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_history(city: str) -> list[dict]:
    """Return stored rainfall history list for a city."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f).get(city, [])
    except Exception:
        return []


# ─────────────────────────────────────────────
# [EXT-2] EMAIL NOTIFICATION
# ─────────────────────────────────────────────

def send_email_alert(reading: WeatherReading, alert: AlertStatus,
                     smtp_server: str, smtp_port: int,
                     sender: str, password: str, recipient: str) -> bool:
    """
    Send an HTML email when a RED alert is triggered.

    Uses Gmail SMTP by default. For other providers, adjust smtp_server/port.
    For Gmail: enable 'App Passwords' in Google Account > Security.

    Returns True on success, False on failure.
    """
    if alert.level != "RED":
        return False   # Only email on RED alerts

    subject = f"🔴 RAINFALL ALERT — {reading.city} ({reading.rainfall:.1f} mm/h)"

    body = f"""
    <html><body style="font-family: Arial, sans-serif;">
      <div style="background:#f8d7da; border-left:6px solid #dc3545;
                  padding:16px; border-radius:8px; max-width:500px;">
        <h2 style="color:#721c24;">⚠️ Heavy Rainfall Alert</h2>
        <p><strong>City:</strong> {reading.city}, {reading.country}</p>
        <p><strong>Rainfall Intensity:</strong>
           <span style="font-size:1.4em; color:#dc3545;">
             {reading.rainfall:.2f} mm/h
           </span>
        </p>
        <p><strong>Temperature:</strong> {reading.temperature:.1f} °C</p>
        <p><strong>Humidity:</strong> {reading.humidity}%</p>
        <p><strong>Conditions:</strong> {reading.description}</p>
        <p><strong>Time:</strong> {reading.timestamp}</p>
        <hr/>
        <p style="color:#721c24; font-weight:bold;">{alert.message}</p>
        <p style="font-size:0.85em; color:#666;">
          Automated alert from Smart Water Lab Rainfall Monitor
        </p>
      </div>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError:
        st.warning("⚠️ Email auth failed — check sender address & app password.")
    except smtplib.SMTPException as e:
        st.warning(f"⚠️ Email send failed: {e}")
    except Exception as e:
        st.warning(f"⚠️ Email error: {e}")

    return False


# ─────────────────────────────────────────────
# [EXT-3] RAINFALL PREDICTION
# ─────────────────────────────────────────────

def predict_rainfall(history: list[dict], steps_ahead: int = 3) -> pd.DataFrame | None:
    """
    Predict future rainfall using two methods:
      1. 5-reading moving average (simple baseline)
      2. Linear regression over all history (trend extrapolation)

    Args:
        history     : List of {timestamp, rainfall} dicts
        steps_ahead : Number of 5-minute steps to forecast (default 3 = 15 min)

    Returns a DataFrame with columns: timestamp, moving_avg, linear_pred
    or None if insufficient data (< 5 readings).
    """
    if len(history) < 5:
        return None

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["x"] = np.arange(len(df))   # numeric index for regression

    # ── Method 1: 5-reading moving average ───
    df["moving_avg"] = df["rainfall"].rolling(window=5, min_periods=1).mean().round(2)

    # ── Method 2: Linear regression ──────────
    x = df["x"].values
    y = df["rainfall"].values
    coeffs = np.polyfit(x, y, 1)      # slope + intercept
    slope, intercept = coeffs
    df["linear_fit"] = (slope * x + intercept).round(2)

    # ── Build future points ───────────────────
    last_time = df["timestamp"].iloc[-1]
    last_x    = df["x"].iloc[-1]

    future_rows = []
    for i in range(1, steps_ahead + 1):
        future_x    = last_x + i
        future_time = last_time + timedelta(minutes=5 * i)
        ma_last     = df["moving_avg"].iloc[-1]     # flat MA projection
        lin_pred    = max(0.0, slope * future_x + intercept)
        future_rows.append({
            "timestamp":   future_time,
            "rainfall":    None,
            "moving_avg":  round(ma_last, 2),
            "linear_pred": round(lin_pred, 2),
            "is_forecast": True,
        })

    df["is_forecast"] = False
    df["linear_pred"] = df["linear_fit"]

    result = pd.concat([df, pd.DataFrame(future_rows)], ignore_index=True)
    return result[["timestamp", "rainfall", "moving_avg", "linear_pred", "is_forecast"]]


# ─────────────────────────────────────────────
# [EXT-4] FOLIUM MAP VISUALIZATION
# ─────────────────────────────────────────────

def build_folium_map(readings: list[WeatherReading]) -> str:
    """
    Build a Folium map with one color-coded circle marker per city.

    Marker colors follow the alert thresholds:
        green  → Normal   (< 10 mm/h)
        orange → Moderate (10–20 mm/h)
        red    → Alert    (≥ 20 mm/h)

    Returns the rendered HTML as a string for embedding in Streamlit.
    """
    if not readings:
        return "<p>No data to display on map.</p>"

    # Centre map on the mean coordinates of all cities
    avg_lat = sum(r.lat for r in readings) / len(readings)
    avg_lon = sum(r.lon for r in readings) / len(readings)

    fmap = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=4,
        tiles="CartoDB positron",
    )

    color_map = {"GREEN": "green", "YELLOW": "orange", "RED": "red"}

    for reading in readings:
        alert  = check_alert(reading.rainfall)
        color  = color_map[alert.level]
        radius = max(20_000, reading.rainfall * 8_000)   # bigger = more rain

        # Filled circle proportional to rainfall intensity
        folium.CircleMarker(
            location=[reading.lat, reading.lon],
            radius=15,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(
                f"""<b>{reading.city}, {reading.country}</b><br>
                    🌧️ {reading.rainfall:.2f} mm/h<br>
                    {alert.emoji} {alert.label}<br>
                    🌡️ {reading.temperature:.1f} °C  💧 {reading.humidity}%<br>
                    <small>{reading.timestamp}</small>""",
                max_width=220,
            ),
            tooltip=f"{reading.city}: {reading.rainfall:.1f} mm/h {alert.emoji}",
        ).add_to(fmap)

        # Pulsing outer ring for RED alerts to draw attention
        if alert.level == "RED":
            folium.Circle(
                location=[reading.lat, reading.lon],
                radius=radius,
                color="red",
                fill=False,
                weight=2,
                opacity=0.5,
            ).add_to(fmap)

    # Legend
    legend_html = """
    <div style="position:fixed; bottom:30px; left:30px; z-index:1000;
                background:white; padding:10px; border-radius:8px;
                border:1px solid #ccc; font-size:13px;">
      <b>🌧️ Rainfall Alert Level</b><br>
      🟢 Normal (&lt;10 mm/h)<br>
      🟡 Moderate (10–20 mm/h)<br>
      🔴 Alert (≥20 mm/h)
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))

    return fmap._repr_html_()


# ─────────────────────────────────────────────
# PART 3: STREAMLIT DASHBOARD
# ─────────────────────────────────────────────

def render_alert_banner(alert: AlertStatus) -> None:
    """Render the colour-coded alert status banner."""
    st.markdown(
        f"""<div style="
                padding:1rem 1.5rem; border-radius:10px; margin-bottom:1rem;
                font-size:1.1rem; font-weight:600;
                background-color:{alert.bg}; color:{alert.color};
                border-left:6px solid {alert.color};">
            {alert.emoji}&nbsp;<strong>Alert Status: {alert.label}</strong>
            &nbsp;|&nbsp; {alert.message}
        </div>""",
        unsafe_allow_html=True,
    )


def render_metrics(reading: WeatherReading, alert: AlertStatus, demo: bool = False) -> None:
    """Render the KPI metric row and CMA category badge."""
    render_alert_banner(alert)

    cma = get_cma_category(reading.rainfall)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🌧️ Rainfall",    f"{reading.rainfall:.2f} mm/h")
    c2.metric("🌡️ Temperature", f"{reading.temperature:.1f} °C")
    c3.metric("💧 Humidity",     f"{reading.humidity} %")
    c4.metric("📍 Location",     f"{reading.city}, {reading.country}")
    c5.metric("🌤️ Conditions",   reading.description)

    st.markdown(
        f"""<div style="display:inline-block; background:{cma['color']}; color:white;
                padding:0.3rem 1rem; border-radius:20px; font-weight:600; margin-top:0.4rem;">
            CMA: {cma['label']}
        </div>""",
        unsafe_allow_html=True,
    )

    if demo:
        st.caption("⚠️ Demo mode — no real API call made.")


def render_history_and_prediction(city_name: str) -> None:
    """Render history line chart and prediction overlay for a single city."""
    st.subheader("📈 Rainfall History + Prediction")
    history = load_history(city_name)

    if len(history) < 2:
        st.info("History appears after a few readings — keep the app running.")
        return

    pred_df = predict_rainfall(history, steps_ahead=6)

    if pred_df is not None:
        # Split actual vs forecast for different line styles
        actual   = pred_df[~pred_df["is_forecast"]][["timestamp", "rainfall", "moving_avg"]].set_index("timestamp")
        forecast = pred_df[["timestamp", "moving_avg", "linear_pred"]].set_index("timestamp")

        col_h, col_p = st.columns([2, 1])

        with col_h:
            st.caption("📊 Observed readings + 5-reading moving average")
            st.line_chart(actual, use_container_width=True, height=200)

        with col_p:
            st.caption("🔮 Predicted next 30 min (moving avg & linear trend)")
            future = pred_df[pred_df["is_forecast"]][["timestamp", "moving_avg", "linear_pred"]].set_index("timestamp")
            st.line_chart(future, use_container_width=True, height=200)

        with st.expander("📋 Prediction detail table"):
            display = pred_df.tail(12)[["timestamp", "rainfall", "moving_avg", "linear_pred", "is_forecast"]]
            display.columns = ["Time", "Actual (mm/h)", "MovAvg Pred", "Linear Pred", "Forecast?"]
            st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        df = pd.DataFrame(history).set_index("timestamp")
        st.line_chart(df["rainfall"], height=200, use_container_width=True)
        st.caption("Need ≥ 5 readings for prediction model to activate.")


def render_dashboard() -> None:
    """Main Streamlit entry point."""

    st.set_page_config(page_title="Rainfall Monitor", page_icon="🌧️", layout="wide")

    # ── Sidebar ───────────────────────────────
    with st.sidebar:
        st.markdown("## 🌧️ Rainfall Monitor")
        st.markdown("_Smart Water Lab — Experiment 1_")
        st.markdown("---")

        api_key = st.text_input("🔑 API Key", value=API_KEY, type="password",
                                help="openweathermap.org — free tier works")

        st.markdown("---")
        st.markdown("### 📊 Thresholds")
        st.markdown(f"🟢 Normal → < {THRESHOLD_YELLOW} mm/h")
        st.markdown(f"🟡 Moderate → {THRESHOLD_YELLOW}–{THRESHOLD_RED} mm/h")
        st.markdown(f"🔴 Alert → ≥ {THRESHOLD_RED} mm/h")

        st.markdown("---")
        # [EXT-2] Email settings
        st.markdown("### ✉️ Email Alerts (EXT-2)")
        email_on       = st.checkbox("Enable email on RED alert")
        smtp_server    = st.text_input("SMTP server", value="smtp.gmail.com")
        smtp_port      = st.number_input("Port", value=465, step=1)
        sender_email   = st.text_input("Sender email")
        sender_pass    = st.text_input("App password", type="password")
        recipient      = st.text_input("Recipient email")

        st.markdown("---")
        auto_refresh = st.checkbox("⏱️ Auto-refresh (5 min)")

    # ── Tabs ──────────────────────────────────
    tab_single, tab_multi, tab_map, tab_log = st.tabs([
        "🏙️ Single City",
        "🌐 Multi-City (EXT-1)",
        "🗺️ Map View (EXT-4)",
        "📝 Alert Log",
    ])

    # ─ Tab 1: Single City ─────────────────────
    with tab_single:
        city = st.text_input("🏙️ City", value="Beijing", key="single_city")
        st.title(f"🌧️ Rainfall Monitor — {city}")
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Demo mode when no API key set
        if api_key in ("your_api_key_here", "") or not api_key.strip():
            st.warning("⚠️ Enter your API key in the sidebar to use live data.")
            st.markdown("#### 🧪 Demo Mode")
            demo_rain = st.slider("Simulate rainfall (mm/h)", 0.0, 40.0, 5.0, 0.5)
            demo_reading = WeatherReading(demo_rain, 22.0, 65, "Simulated",
                                          "Demo City", "XX", 39.9, 116.4,
                                          datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            render_metrics(demo_reading, check_alert(demo_rain), demo=True)
        else:
            with st.spinner(f"Fetching {city}..."):
                reading = fetch_weather(city, api_key)

            if reading:
                alert = check_alert(reading.rainfall)
                log_alert(reading, alert)
                save_to_history(reading, alert.level)

                # [EXT-2] Email notification
                if email_on and alert.level == "RED":
                    sent = send_email_alert(
                        reading, alert, smtp_server, int(smtp_port),
                        sender_email, sender_pass, recipient
                    )
                    if sent:
                        st.success("📧 Alert email sent successfully!")

                render_metrics(reading, alert)
                st.markdown("---")

                # [EXT-3] History + Prediction
                render_history_and_prediction(reading.city)

                st.markdown("---")
                # 48h forecast
                st.subheader("🔮 48-Hour API Forecast")
                fc = fetch_forecast(city, api_key)
                if fc:
                    df_fc = pd.DataFrame(fc).set_index("time")
                    st.area_chart(df_fc["rainfall"], height=180, use_container_width=True)

    # ─ Tab 2: Multi-City [EXT-1] ──────────────
    with tab_multi:
        st.subheader("🌐 Multi-City Monitoring")
        st.caption("Compare rainfall across multiple cities simultaneously.")

        cities_input = st.text_area(
            "Cities (one per line)",
            value="\n".join(DEFAULT_CITIES),
            height=120,
            help="Enter city names, one per line",
        )
        selected_cities = [c.strip() for c in cities_input.splitlines() if c.strip()]

        if st.button("🔄 Fetch All Cities") and api_key not in ("your_api_key_here", ""):
            multi_readings: list[WeatherReading] = []
            progress = st.progress(0)
            status_text = st.empty()

            for i, city_name in enumerate(selected_cities):
                status_text.text(f"Fetching {city_name} ({i+1}/{len(selected_cities)})...")
                r = fetch_weather(city_name, api_key)
                if r:
                    multi_readings.append(r)
                    a = check_alert(r.rainfall)
                    log_alert(r, a)
                    save_to_history(r, a.level)
                progress.progress((i + 1) / len(selected_cities))

            status_text.empty()
            progress.empty()

            if multi_readings:
                # Store in session for map tab
                st.session_state["multi_readings"] = multi_readings

                # Summary comparison table
                rows = []
                for r in multi_readings:
                    a = check_alert(r.rainfall)
                    rows.append({
                        "City":          f"{r.city}, {r.country}",
                        "Rainfall mm/h": r.rainfall,
                        "Alert":         f"{a.emoji} {a.label}",
                        "Temp °C":       r.temperature,
                        "Humidity %":    r.humidity,
                        "Conditions":    r.description,
                    })

                df_multi = pd.DataFrame(rows).sort_values("Rainfall mm/h", ascending=False)
                st.dataframe(df_multi, use_container_width=True, hide_index=True)

                # Bar chart comparison
                st.subheader("📊 Rainfall Comparison")
                chart_df = df_multi.set_index("City")[["Rainfall mm/h"]]
                st.bar_chart(chart_df, use_container_width=True, height=250)

                # Highlight most at-risk city
                top = multi_readings[0] if multi_readings else None
                top = max(multi_readings, key=lambda r: r.rainfall)
                top_alert = check_alert(top.rainfall)
                st.info(f"{top_alert.emoji} Highest rainfall: **{top.city}** at "
                        f"**{top.rainfall:.2f} mm/h** — {top_alert.label}")
        elif api_key in ("your_api_key_here", ""):
            st.warning("⚠️ Please enter your API key in the sidebar first.")

    # ─ Tab 3: Map [EXT-4] ─────────────────────
    with tab_map:
        st.subheader("🗺️ Rainfall Map — Folium Visualization")

        readings_for_map: list[WeatherReading] = st.session_state.get("multi_readings", [])

        if not readings_for_map:
            st.info("👆 Fetch cities from the **Multi-City** tab first, then return here.")

            # Offer a quick single-city map fetch
            map_city = st.text_input("Or fetch a single city for the map:", value="Beijing")
            if st.button("📍 Show on Map") and api_key not in ("your_api_key_here", ""):
                with st.spinner("Fetching..."):
                    r = fetch_weather(map_city, api_key)
                if r:
                    readings_for_map = [r]

        if readings_for_map:
            map_html = build_folium_map(readings_for_map)
            components.html(map_html, height=520, scrolling=False)

            st.caption(
                "🟢 Green = Normal  |  🟡 Orange = Moderate  |  "
                "🔴 Red = Alert  |  Red circle = flood risk radius"
            )

    # ─ Tab 4: Alert Log ───────────────────────
    with tab_log:
        st.subheader("📝 Alert Log")
        col_log, col_clear = st.columns([4, 1])

        with col_clear:
            if st.button("🗑️ Clear Log"):
                open(LOG_FILE, "w").close()
                st.success("Log cleared.")

        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()

            non_comment = [l for l in lines if not l.startswith("#")]
            if non_comment:
                # Show latest first
                st.code("".join(reversed(non_comment[-30:])), language=None)

                # Parse for stats
                yellow = sum(1 for l in non_comment if "LEVEL=YELLOW" in l)
                red    = sum(1 for l in non_comment if "LEVEL=RED" in l)
                s1, s2, s3 = st.columns(3)
                s1.metric("Total alerts", len(non_comment))
                s2.metric("🟡 Yellow",    yellow)
                s3.metric("🔴 Red",       red)
            else:
                st.success("✅ No alerts triggered yet.")
        else:
            st.info("Log file will be created when the first alert fires.")

    # ── Auto-refresh (non-blocking) ───────────
    # FIX: Original used time.sleep(300) which freezes the UI thread.
    # Correct approach: store fetch time in session_state and rerun only
    # when the interval has elapsed.
    if auto_refresh:
        key = "last_auto_refresh"
        now = time.time()
        st.session_state.setdefault(key, now)

        elapsed = now - st.session_state[key]
        remaining = max(0, REFRESH_INTERVAL - int(elapsed))

        st.sidebar.caption(f"⏱️ Next refresh in {remaining} s")

        if elapsed >= REFRESH_INTERVAL:
            st.session_state[key] = now
            st.rerun()
        else:
            time.sleep(1)
            st.rerun()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    render_dashboard()
