# Prompt Log — Experiment 1 (Enhanced Edition)
# Short-term Rainfall Forecasting & Alert System
# AI-Augmented Software Engineering | Smart Water Lab Series

---

## Interactions #1–5 (Core Experiment)

> See original prompt_log.md for the first 5 interactions covering
> API integration, alert logic, dashboard creation, forecast extension,
> and debugging session.

---

## Interaction #6 — EXT-1: Multiple City Monitoring

### Prompt Sent
```
Extend my rainfall monitoring Streamlit app to monitor multiple cities 
simultaneously. The user should be able to enter a list of city names 
in a text area (one per line). When they click "Fetch All Cities":
1. Loop through each city and call fetch_weather() for each
2. Show a summary DataFrame sorted by rainfall descending
3. Show a bar chart comparing all cities
4. Highlight the most at-risk city with an st.info() message
5. Store results in st.session_state so other tabs can use them
Also add a progress bar while fetching.
```

### AI Response Summary
The AI generated a multi-city loop with `st.progress()`, built a DataFrame from results, sorted by rainfall, rendered a `st.bar_chart()`, and stored `readings` in `st.session_state["multi_readings"]` for the map tab.

### Critical Evaluation
| Aspect | Assessment |
|--------|-----------|
| Progress bar | ✅ Correct — `st.progress((i+1)/len(cities))` |
| DataFrame sort | ✅ Sorts correctly descending |
| Session state | ✅ Enables tab-to-tab data sharing |
| API rate limits | ⚠️ **AI Error:** No delay between city requests — could hit the 60 calls/min limit with large lists. **Correction:** Added `_last_api_call` dict + 2-second minimum gap inside `fetch_weather()` |

### Correction Made
```python
# Added to fetch_weather() — rate limit guard
now = time.time()
if city in _last_api_call:
    elapsed = now - _last_api_call[city]
    if elapsed < API_MIN_INTERVAL:
        time.sleep(API_MIN_INTERVAL - elapsed)
_last_api_call[city] = time.time()
```

---

## Interaction #7 — EXT-2: Email Notifications

### Prompt Sent
```
Add email alert functionality to my rainfall monitor. When a RED alert 
triggers, send an HTML email to a configured recipient using smtplib.
Requirements:
- Use SMTP_SSL (port 465) for Gmail
- Email body should be styled HTML with all reading metrics
- The function should only fire on RED alerts, not YELLOW or GREEN
- Show success/failure feedback in the Streamlit sidebar
- Add sender email, password (hidden), and recipient inputs to the sidebar
```

### AI Response Summary
AI generated `send_email_alert()` using `smtplib.SMTP_SSL`, a `MIMEMultipart("alternative")` message with a styled HTML body, and separate error handling for `SMTPAuthenticationError` vs general `SMTPException`.

### Critical Evaluation
| Aspect | Assessment |
|--------|-----------|
| SMTP approach | ✅ Correct — SMTP_SSL for port 465, STARTTLS would need port 587 |
| HTML email | ✅ Styled with inline CSS (required for email clients) |
| Error handling | ✅ Auth error separated from general SMTP error |
| Security | ⚠️ **AI suggestion:** Store password in `.env` file. This is good practice but adds complexity. **Decision:** Kept as sidebar input for the experiment scope; added `type="password"` masking |
| One concern | ⚠️ **Physical validation:** Gmail requires an "App Password" (not the account password) when 2FA is enabled. The AI did not mention this. **Correction:** Added this requirement to the README. |

---

## Interaction #8 — EXT-3: Rainfall Prediction

### Prompt Sent
```
Add a short-term rainfall prediction feature to my monitoring app using 
historical readings stored in rainfall_history.json. Implement two methods:
1. 5-reading moving average — simple trend baseline
2. Linear regression using numpy.polyfit — extrapolate the trend line
Predict 3 steps ahead (15 minutes at 5-min intervals).
Show both methods in the same Streamlit chart. Require at least 5 readings 
to activate the prediction.
```

### AI Response Summary
AI generated `predict_rainfall()` using:
- `pandas.rolling(window=5)` for the moving average
- `numpy.polyfit(x, y, 1)` for linear regression (degree 1 = straight line)
- Future rows appended to the DataFrame with `is_forecast=True` flag
- Extrapolated future timestamps using `timedelta`

### Critical Evaluation
| Aspect | Assessment |
|--------|-----------|
| Moving average | ✅ Correct rolling window implementation |
| Linear regression | ✅ `polyfit` degree=1 gives slope+intercept correctly |
| Negative prediction guard | ⚠️ **AI Error:** Linear regression can predict negative rainfall. **Correction:** Added `max(0.0, ...)` clamp on predictions |
| Physical validity | ✅ Short-term linear extrapolation is reasonable for nowcasting (0–15 min). Would not be valid for longer horizons — flagged this in the chart caption |
| Model limitation note | Added caption: "Linear prediction assumes steady trend — valid for ≤15 min only" |

### Correction Made
```python
# Original AI output (can go negative):
lin_pred = slope * future_x + intercept

# Corrected — rainfall cannot be negative:
lin_pred = max(0.0, slope * future_x + intercept)
```

---

## Interaction #9 — EXT-4: Map Visualization with Folium

### Prompt Sent
```
Add an interactive map to my rainfall monitoring dashboard using the 
Folium library. Display each monitored city as a circle marker where:
- Color = alert level (green/orange/red)
- Popup shows: city name, rainfall, temperature, humidity, alert label
- Tooltip shows city + rainfall on hover
- RED alert cities get a larger pulsing outer ring to draw attention
- Add a legend explaining the color scheme
Use streamlit.components.v1.html() to embed the map.
Centre the map on the average coordinates of all loaded cities.
```

### AI Response Summary
AI generated `build_folium_map()` using:
- `folium.CircleMarker` for each city with color-coded fill
- `folium.Popup` with HTML content for click details
- `folium.Circle` (larger, unfilled) for RED cities as the "pulsing ring"
- A legend injected via `folium.Element` into `fmap.get_root().html`
- `fmap._repr_html_()` to extract the HTML string for Streamlit embedding

### Critical Evaluation
| Aspect | Assessment |
|--------|-----------|
| Folium integration | ✅ Correct — `components.html()` is the right Streamlit embed method |
| Color mapping | ✅ green/orange/red matches alert thresholds |
| Popup HTML | ✅ Emoji + metrics formatted cleanly |
| Coordinate centring | ✅ Mean lat/lon of all cities |
| Tile choice | ✅ `CartoDB positron` is clean and lightweight |
| Ring radius | ⚠️ **AI Error:** AI hardcoded `radius=50000` for all cities. **Correction:** Made radius proportional to rainfall: `max(20_000, rainfall × 8_000)` so heavier rain = bigger ring |

### Correction Made
```python
# Original AI output (static radius):
folium.Circle(location=[r.lat, r.lon], radius=50000, ...)

# Corrected — proportional to rainfall intensity:
radius = max(20_000, reading.rainfall * 8_000)
folium.Circle(location=[reading.lat, reading.lon], radius=radius, ...)
```

---

## Interaction #10 — Bug Fix: Auto-Refresh Blocking Issue

### Prompt Sent
```
My Streamlit app freezes completely for 5 minutes when auto-refresh is 
enabled because I used time.sleep(300) inside the render function. 
How do I implement a non-blocking 5-minute auto-refresh in Streamlit?
```

### AI Response Summary
AI explained that `time.sleep()` blocks the entire Streamlit execution thread, preventing any user interaction. The correct approach is to store the last refresh timestamp in `st.session_state`, then on each render cycle, check if enough time has passed and call `st.rerun()` if so.

### Critical Evaluation
- ✅ Diagnosis was correct and well-explained
- ✅ Session state approach is the standard Streamlit pattern
- ✅ AI also suggested showing a countdown timer in the sidebar — implemented

---

## Complete Error Summary (All Interactions)

| # | Interaction | Error Type | Description | Fix Applied |
|---|------------|-----------|-------------|-------------|
| 1 | API Integration | KeyError | Missing `rain` key on dry days | `.get()` with default 0.0 |
| 2 | Alert Logic | Design flaw | Logged GREEN (normal) alerts | Added early return for GREEN |
| 3 | Dashboard | Silent failure | `except: pass` hid forecast errors | Changed to warning + `return []` |
| 4 | Dashboard | Missing UX | No fallback without API key | Added demo slider mode |
| 5 | Multi-City | Rate limiting | No delay between city fetches | Added per-city rate limit guard |
| 6 | Email | Missing info | App Password requirement not mentioned | Added to README |
| 7 | Prediction | Physics error | Linear model predicted negative rainfall | Added `max(0.0, ...)` clamp |
| 8 | Map | Design flaw | Fixed ring radius regardless of intensity | Made radius proportional to rainfall |
| 9 | Auto-refresh | Critical bug | `time.sleep(300)` blocked UI thread | Replaced with session_state timer |

---

## Overall Reflection

**What AI excelled at:**
- Rapid scaffolding of boilerplate code (API calls, file I/O, Streamlit layout)
- Consistent use of modern library APIs (e.g., `st.rerun()` not deprecated `st.experimental_rerun()`)
- Generating formatted HTML for emails and Folium popups
- Debugging: correctly diagnosed all reported issues on the first attempt

**Where domain knowledge was irreplaceable:**
- Knowing that the `rain` API key is absent (not zero) in dry conditions
- Understanding that linear regression cannot predict negative physical quantities
- Recognising that a static flood-risk ring radius loses meaning vs. a proportional one
- Identifying the thread-blocking nature of `time.sleep()` in a reactive framework

**Key insight:**
AI handles *syntactic* correctness reliably. *Physical* correctness (units, sign constraints, real-world edge cases) and *systems* correctness (thread models, rate limits) require domain expertise to verify.

---
*End of Prompt Log — Enhanced Edition*
