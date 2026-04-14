"""
Weather AI MCP Server
Weather intelligence tools powered by MEOK AI Labs.
"""


import sys, os
sys.path.insert(0, os.path.expanduser('~/clawd/meok-labs-engine/shared'))
from auth_middleware import check_access

import time
import math
import hashlib
import random
from datetime import date, datetime, timedelta
from collections import defaultdict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather-ai-mcp")

_call_counts: dict[str, list[float]] = defaultdict(list)
FREE_TIER_LIMIT = 50
WINDOW = 86400


def _check_rate_limit(tool_name: str) -> None:
    now = time.time()
    _call_counts[tool_name] = [t for t in _call_counts[tool_name] if now - t < WINDOW]
    if len(_call_counts[tool_name]) >= FREE_TIER_LIMIT:
        raise ValueError(f"Rate limit exceeded for {tool_name}. Free tier: {FREE_TIER_LIMIT}/day.")
    _call_counts[tool_name].append(now)


# City climate baselines (lat, lon, avg_temp_c_jan, avg_temp_c_jul, avg_rain_mm_month)
CITY_CLIMATE = {
    "london": (51.51, -0.13, 5, 18, 60),
    "new_york": (40.71, -74.01, 1, 25, 100),
    "tokyo": (35.68, 139.69, 5, 26, 130),
    "sydney": (-33.87, 151.21, 23, 13, 80),
    "paris": (48.86, 2.35, 4, 20, 55),
    "berlin": (52.52, 13.41, 1, 19, 55),
    "dubai": (25.20, 55.27, 19, 36, 5),
    "singapore": (1.35, 103.82, 27, 27, 170),
    "mumbai": (19.08, 72.88, 25, 28, 340),
    "moscow": (55.76, 37.62, -8, 19, 60),
    "cairo": (30.04, 31.24, 14, 28, 2),
    "nairobi": (-1.29, 36.82, 20, 16, 50),
    "rio": (-22.91, -43.17, 27, 20, 80),
    "toronto": (43.65, -79.38, -4, 22, 70),
    "beijing": (39.90, 116.40, -3, 27, 80),
    "melbourne": (-37.81, 144.96, 20, 10, 50),
    "cape_town": (-33.93, 18.42, 21, 12, 30),
    "amsterdam": (52.37, 4.90, 3, 18, 70),
    "los_angeles": (34.05, -118.24, 14, 22, 15),
    "chicago": (41.88, -87.63, -3, 24, 85),
}


def _simulate_weather(city_key: str, target_date: date, seed_extra: str = "") -> dict:
    """Generate deterministic simulated weather data based on city climate baseline and date."""
    data = CITY_CLIMATE.get(city_key)
    if not data:
        # Default to mild
        data = (50, 0, 10, 20, 70)

    lat, lon, jan_temp, jul_temp, avg_rain = data

    # Day of year for seasonal variation
    doy = target_date.timetuple().tm_yday
    # Southern hemisphere swap
    if lat < 0:
        doy = (doy + 182) % 365

    # Sinusoidal temperature model
    season_factor = math.cos(2 * math.pi * (doy - 15) / 365)  # peaks in January (day ~15)
    base_temp = (jan_temp + jul_temp) / 2 + (jan_temp - jul_temp) / 2 * season_factor

    # Add daily variation with deterministic seed
    seed = hashlib.md5(f"{city_key}{target_date.isoformat()}{seed_extra}".encode()).hexdigest()
    rng = random.Random(seed)
    temp_var = rng.gauss(0, 3)
    temp = round(base_temp + temp_var, 1)

    # Precipitation likelihood
    rain_factor = avg_rain / 150  # normalize
    is_rainy = rng.random() < rain_factor * 0.5
    precipitation_mm = round(rng.uniform(1, avg_rain / 10), 1) if is_rainy else 0

    humidity = round(max(20, min(100, 50 + rain_factor * 30 + rng.gauss(0, 10))))
    wind_speed = round(max(0, rng.gauss(15, 8)), 1)
    wind_dir = rng.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"])

    # UV index (higher in summer, lower in winter, adjusted for latitude)
    uv_base = max(1, 11 - abs(lat) / 8)
    uv_seasonal = uv_base * (1 - 0.5 * season_factor)
    uv_index = round(max(1, min(11, uv_seasonal + rng.gauss(0, 1))))

    # Conditions
    if precipitation_mm > 5:
        condition = "Heavy Rain" if temp > 2 else "Heavy Snow"
    elif precipitation_mm > 0:
        condition = "Light Rain" if temp > 2 else "Light Snow"
    elif humidity > 80:
        condition = "Overcast"
    elif humidity > 60:
        condition = "Partly Cloudy"
    else:
        condition = "Clear"

    feels_like = temp
    if wind_speed > 20:
        wind_chill = 13.12 + 0.6215 * temp - 11.37 * wind_speed**0.16 + 0.3965 * temp * wind_speed**0.16
        feels_like = round(min(temp, wind_chill), 1)
    elif temp > 27 and humidity > 60:
        feels_like = round(temp + (humidity - 50) * 0.1, 1)

    return {
        "temperature_c": temp,
        "feels_like_c": feels_like,
        "humidity_percent": humidity,
        "wind_speed_kmh": wind_speed,
        "wind_direction": wind_dir,
        "precipitation_mm": precipitation_mm,
        "condition": condition,
        "uv_index": uv_index,
    }


@mcp.tool()
def get_current_conditions(
    city: str,
    units: str = "metric", api_key: str = "") -> dict:
    """Get current weather conditions for a city.

    Args:
        city: City name (e.g. london, new_york, tokyo)
        units: Unit system: metric (Celsius, km/h) or imperial (Fahrenheit, mph)
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("get_current_conditions")

    city_key = city.lower().replace(" ", "_")
    if city_key not in CITY_CLIMATE:
        closest = min(CITY_CLIMATE.keys(), key=lambda k: sum(c1 != c2 for c1, c2 in zip(k, city_key)))
        city_key = closest

    weather = _simulate_weather(city_key, date.today(), seed_extra=str(time.time() // 3600))
    lat, lon = CITY_CLIMATE[city_key][:2]

    if units == "imperial":
        weather["temperature_f"] = round(weather["temperature_c"] * 9 / 5 + 32, 1)
        weather["feels_like_f"] = round(weather["feels_like_c"] * 9 / 5 + 32, 1)
        weather["wind_speed_mph"] = round(weather["wind_speed_kmh"] * 0.621371, 1)
        weather["precipitation_in"] = round(weather["precipitation_mm"] * 0.0393701, 2)

    weather["city"] = city_key.replace("_", " ").title()
    weather["coordinates"] = {"lat": lat, "lon": lon}
    weather["timestamp"] = datetime.now().isoformat()
    weather["units"] = units
    weather["data_source"] = "MEOK Weather Model (simulated)"

    return weather


@mcp.tool()
def get_forecast(
    city: str,
    days: int = 7,
    units: str = "metric", api_key: str = "") -> dict:
    """Get multi-day weather forecast for a city.

    Args:
        city: City name
        days: Forecast days (1-14)
        units: metric or imperial
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("get_forecast")

    days = max(1, min(14, days))
    city_key = city.lower().replace(" ", "_")
    if city_key not in CITY_CLIMATE:
        closest = min(CITY_CLIMATE.keys(), key=lambda k: sum(c1 != c2 for c1, c2 in zip(k, city_key)))
        city_key = closest

    today = date.today()
    forecast = []

    for i in range(days):
        d = today + timedelta(days=i)
        weather = _simulate_weather(city_key, d)

        # Generate high/low from base
        high = round(weather["temperature_c"] + abs(random.Random(f"{city_key}{d}{0}").gauss(0, 2)) + 3, 1)
        low = round(weather["temperature_c"] - abs(random.Random(f"{city_key}{d}{1}").gauss(0, 2)) - 3, 1)

        entry = {
            "date": d.isoformat(),
            "day": d.strftime("%A"),
            "high_c": high,
            "low_c": low,
            "condition": weather["condition"],
            "precipitation_mm": weather["precipitation_mm"],
            "humidity_percent": weather["humidity_percent"],
            "wind_speed_kmh": weather["wind_speed_kmh"],
            "wind_direction": weather["wind_direction"],
            "uv_index": weather["uv_index"],
        }

        if units == "imperial":
            entry["high_f"] = round(high * 9 / 5 + 32, 1)
            entry["low_f"] = round(low * 9 / 5 + 32, 1)
            entry["wind_speed_mph"] = round(weather["wind_speed_kmh"] * 0.621371, 1)

        forecast.append(entry)

    # Summary
    avg_temp = sum(f["high_c"] + f["low_c"] for f in forecast) / (len(forecast) * 2)
    total_precip = sum(f["precipitation_mm"] for f in forecast)
    rainy_days = sum(1 for f in forecast if f["precipitation_mm"] > 0)

    return {
        "city": city_key.replace("_", " ").title(),
        "forecast_days": days,
        "units": units,
        "forecast": forecast,
        "summary": {
            "average_temp_c": round(avg_temp, 1),
            "total_precipitation_mm": round(total_precip, 1),
            "rainy_days": rainy_days,
            "warmest_day": max(forecast, key=lambda f: f["high_c"])["date"],
            "coldest_day": min(forecast, key=lambda f: f["low_c"])["date"],
        },
    }


@mcp.tool()
def get_historical_weather(
    city: str,
    start_date: str,
    end_date: str,
    units: str = "metric", api_key: str = "") -> dict:
    """Get historical weather data for a city and date range.

    Args:
        city: City name
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        units: metric or imperial
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("get_historical_weather")

    city_key = city.lower().replace(" ", "_")
    if city_key not in CITY_CLIMATE:
        closest = min(CITY_CLIMATE.keys(), key=lambda k: sum(c1 != c2 for c1, c2 in zip(k, city_key)))
        city_key = closest

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    max_days = 365
    if (end - start).days > max_days:
        end = start + timedelta(days=max_days)

    daily_data = []
    current = start
    while current <= end:
        weather = _simulate_weather(city_key, current, seed_extra="historical")
        daily_data.append({
            "date": current.isoformat(),
            "temperature_c": weather["temperature_c"],
            "humidity_percent": weather["humidity_percent"],
            "precipitation_mm": weather["precipitation_mm"],
            "condition": weather["condition"],
            "wind_speed_kmh": weather["wind_speed_kmh"],
        })
        current += timedelta(days=1)

    temps = [d["temperature_c"] for d in daily_data]
    precips = [d["precipitation_mm"] for d in daily_data]

    return {
        "city": city_key.replace("_", " ").title(),
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": len(daily_data)},
        "units": units,
        "daily_data": daily_data,
        "statistics": {
            "avg_temperature_c": round(sum(temps) / len(temps), 1),
            "max_temperature_c": max(temps),
            "min_temperature_c": min(temps),
            "total_precipitation_mm": round(sum(precips), 1),
            "rainy_days": sum(1 for p in precips if p > 0),
            "dry_days": sum(1 for p in precips if p == 0),
        },
        "data_source": "MEOK Weather Model (simulated historical)",
    }


@mcp.tool()
def get_agricultural_alerts(
    city: str,
    crop_type: str = "general", api_key: str = "") -> dict:
    """Get agricultural weather alerts and growing condition analysis.

    Args:
        city: City/region name
        crop_type: Crop type: general, wheat, rice, corn, vegetables, fruit, grapes
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("get_agricultural_alerts")

    city_key = city.lower().replace(" ", "_")
    if city_key not in CITY_CLIMATE:
        closest = min(CITY_CLIMATE.keys(), key=lambda k: sum(c1 != c2 for c1, c2 in zip(k, city_key)))
        city_key = closest

    today = date.today()
    weather = _simulate_weather(city_key, today)

    # 7-day forecast for agricultural planning
    week_forecast = []
    for i in range(7):
        d = today + timedelta(days=i)
        w = _simulate_weather(city_key, d)
        week_forecast.append(w)

    min_temp_week = min(w["temperature_c"] for w in week_forecast)
    max_temp_week = max(w["temperature_c"] for w in week_forecast)
    total_rain_week = sum(w["precipitation_mm"] for w in week_forecast)

    # Crop-specific thresholds
    crop_thresholds = {
        "general": {"frost": 0, "heat_stress": 35, "optimal_low": 10, "optimal_high": 30, "min_rain_weekly": 15, "max_rain_weekly": 80},
        "wheat": {"frost": -5, "heat_stress": 30, "optimal_low": 5, "optimal_high": 25, "min_rain_weekly": 10, "max_rain_weekly": 60},
        "rice": {"frost": 10, "heat_stress": 38, "optimal_low": 20, "optimal_high": 35, "min_rain_weekly": 30, "max_rain_weekly": 150},
        "corn": {"frost": 2, "heat_stress": 35, "optimal_low": 15, "optimal_high": 30, "min_rain_weekly": 20, "max_rain_weekly": 80},
        "vegetables": {"frost": 2, "heat_stress": 32, "optimal_low": 10, "optimal_high": 28, "min_rain_weekly": 15, "max_rain_weekly": 60},
        "fruit": {"frost": 0, "heat_stress": 33, "optimal_low": 12, "optimal_high": 30, "min_rain_weekly": 15, "max_rain_weekly": 70},
        "grapes": {"frost": -2, "heat_stress": 35, "optimal_low": 10, "optimal_high": 30, "min_rain_weekly": 8, "max_rain_weekly": 50},
    }

    thresholds = crop_thresholds.get(crop_type, crop_thresholds["general"])
    alerts = []

    if min_temp_week <= thresholds["frost"]:
        alerts.append({
            "type": "FROST_WARNING",
            "severity": "high",
            "message": f"Frost risk: temperatures expected to drop to {min_temp_week}C. Protect sensitive crops.",
            "action": "Cover crops with frost cloth. Irrigate soil (wet soil retains heat).",
        })

    if max_temp_week >= thresholds["heat_stress"]:
        alerts.append({
            "type": "HEAT_STRESS",
            "severity": "high",
            "message": f"Heat stress risk: temperatures expected to reach {max_temp_week}C.",
            "action": "Increase irrigation. Apply shade cloth if possible. Harvest early morning.",
        })

    if total_rain_week < thresholds["min_rain_weekly"]:
        alerts.append({
            "type": "DROUGHT_RISK",
            "severity": "medium",
            "message": f"Low rainfall expected: {total_rain_week}mm (threshold: {thresholds['min_rain_weekly']}mm).",
            "action": "Increase irrigation schedule. Apply mulch to retain soil moisture.",
        })

    if total_rain_week > thresholds["max_rain_weekly"]:
        alerts.append({
            "type": "WATERLOGGING_RISK",
            "severity": "medium",
            "message": f"Heavy rainfall expected: {total_rain_week}mm (threshold: {thresholds['max_rain_weekly']}mm).",
            "action": "Ensure drainage is clear. Delay planting if soil is saturated.",
        })

    if weather["humidity_percent"] > 80 and weather["temperature_c"] > 15:
        alerts.append({
            "type": "DISEASE_RISK",
            "severity": "medium",
            "message": "High humidity and warm temperatures increase fungal disease risk.",
            "action": "Monitor for signs of blight, mildew, or rot. Consider preventive fungicide application.",
        })

    conditions = "optimal" if thresholds["optimal_low"] <= weather["temperature_c"] <= thresholds["optimal_high"] else \
                 "suboptimal" if abs(weather["temperature_c"] - (thresholds["optimal_low"] + thresholds["optimal_high"]) / 2) < 15 else "poor"

    return {
        "city": city_key.replace("_", " ").title(),
        "crop_type": crop_type,
        "date": today.isoformat(),
        "current_conditions": weather,
        "growing_conditions": conditions,
        "alerts": alerts,
        "alert_count": len(alerts),
        "7_day_outlook": {
            "min_temp": min_temp_week,
            "max_temp": max_temp_week,
            "total_rainfall_mm": round(total_rain_week, 1),
            "optimal_range": f"{thresholds['optimal_low']}-{thresholds['optimal_high']}C",
        },
    }


@mcp.tool()
def get_severe_weather_warnings(
    city: str, api_key: str = "") -> dict:
    """Check for severe weather warnings and safety advisories.

    Args:
        city: City name
    """
    allowed, msg, tier = check_access(api_key)
    if not allowed:
        return {"error": msg, "upgrade_url": "https://meok.ai/pricing"}

    _check_rate_limit("get_severe_weather_warnings")

    city_key = city.lower().replace(" ", "_")
    if city_key not in CITY_CLIMATE:
        closest = min(CITY_CLIMATE.keys(), key=lambda k: sum(c1 != c2 for c1, c2 in zip(k, city_key)))
        city_key = closest

    today = date.today()
    warnings = []

    # Check next 3 days for severe conditions
    for i in range(3):
        d = today + timedelta(days=i)
        weather = _simulate_weather(city_key, d)

        if weather["temperature_c"] > 38:
            warnings.append({
                "type": "EXTREME_HEAT",
                "severity": "RED",
                "date": d.isoformat(),
                "message": f"Extreme heat warning: {weather['temperature_c']}C expected.",
                "safety": ["Stay hydrated", "Avoid outdoor activity 11am-3pm", "Check on vulnerable neighbours", "Never leave children/pets in vehicles"],
            })
        elif weather["temperature_c"] > 33:
            warnings.append({
                "type": "HEAT_ADVISORY",
                "severity": "AMBER",
                "date": d.isoformat(),
                "message": f"Heat advisory: {weather['temperature_c']}C expected.",
                "safety": ["Drink plenty of water", "Seek shade during peak hours", "Wear light clothing"],
            })

        if weather["temperature_c"] < -10:
            warnings.append({
                "type": "EXTREME_COLD",
                "severity": "RED",
                "date": d.isoformat(),
                "message": f"Extreme cold warning: {weather['temperature_c']}C expected.",
                "safety": ["Limit outdoor exposure", "Dress in layers", "Check heating systems", "Protect pipes from freezing"],
            })

        if weather["wind_speed_kmh"] > 80:
            warnings.append({
                "type": "HIGH_WIND",
                "severity": "RED",
                "date": d.isoformat(),
                "message": f"High wind warning: {weather['wind_speed_kmh']} km/h gusts expected.",
                "safety": ["Secure loose objects outdoors", "Avoid driving high-sided vehicles", "Stay away from trees and power lines"],
            })
        elif weather["wind_speed_kmh"] > 50:
            warnings.append({
                "type": "WIND_ADVISORY",
                "severity": "AMBER",
                "date": d.isoformat(),
                "message": f"Wind advisory: {weather['wind_speed_kmh']} km/h gusts expected.",
                "safety": ["Secure loose garden items", "Drive with caution"],
            })

        if weather["precipitation_mm"] > 30:
            warnings.append({
                "type": "HEAVY_RAIN",
                "severity": "AMBER",
                "date": d.isoformat(),
                "message": f"Heavy rain warning: {weather['precipitation_mm']}mm expected.",
                "safety": ["Avoid flood-prone areas", "Do not drive through standing water", "Check local flood alerts"],
            })

    active_count = len(warnings)
    max_severity = "GREEN"
    if any(w["severity"] == "RED" for w in warnings):
        max_severity = "RED"
    elif any(w["severity"] == "AMBER" for w in warnings):
        max_severity = "AMBER"

    return {
        "city": city_key.replace("_", " ").title(),
        "checked_at": datetime.now().isoformat(),
        "overall_status": max_severity,
        "active_warnings": active_count,
        "warnings": warnings,
        "safety_message": {
            "GREEN": "No severe weather warnings. Normal conditions expected.",
            "AMBER": "Weather warnings in effect. Stay informed and take precautions.",
            "RED": "Severe weather warnings active. Take immediate safety precautions.",
        }[max_severity],
    }


if __name__ == "__main__":
    mcp.run()
