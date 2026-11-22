import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

mcp = FastMCP("Weather MCP Server")

OPENWEATHER_API_KEY = os.getenv(
    "OPENWEATHER_API_KEY"
)

REQUEST_TIMEOUT_SECONDS = 20


def _get_api_key() -> str:
    if not OPENWEATHER_API_KEY:
        raise RuntimeError(
            "OPENWEATHER_API_KEY is missing "
            "from the project .env file."
        )

    return OPENWEATHER_API_KEY


def _request_json(
    url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as exc:
        details = ""

        failed_response = getattr(
            exc,
            "response",
            None,
        )

        if failed_response is not None:
            details = (
                f" Response: "
                f"{failed_response.text[:500]}"
            )

        raise RuntimeError(
            f"OpenWeather request failed: "
            f"{exc}.{details}"
        ) from exc


@mcp.tool()
def get_current_weather(
    city: str,
) -> dict[str, Any]:
    """Return the current weather for a city."""

    city = city.strip()

    if not city:
        raise ValueError(
            "city cannot be empty"
        )

    data = _request_json(
        "https://api.openweathermap.org/data/2.5/weather",
        {
            "q": city,
            "appid": _get_api_key(),
            "units": "metric",
        },
    )

    return {
        "city": data["name"],
        "temperature_c": data["main"]["temp"],
        "feels_like_c": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "wind_speed": data["wind"]["speed"],
    }


def _summarise_days(entries: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Collapse OpenWeather's 3-hourly entries into one summary per date."""

    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in entries:
        by_date.setdefault(item["dt_txt"].split(" ")[0], []).append(item)

    summary = []
    for date in sorted(by_date)[:days]:
        items = by_date[date]
        conditions = [entry["weather"][0]["description"] for entry in items]
        summary.append(
            {
                "date": date,
                "temp_min_c": round(min(e["main"]["temp_min"] for e in items), 1),
                "temp_max_c": round(max(e["main"]["temp_max"] for e in items), 1),
                "condition": max(set(conditions), key=conditions.count),
                "rain_chance_pct": round(100 * max(e.get("pop", 0) for e in items)),
            }
        )
    return summary


@mcp.tool()
def get_forecast(
    city: str,
    days: int = 5,
) -> dict[str, Any]:
    """
    Return a daily forecast summary (min/max temperature, dominant
    condition, rain chance) for up to five upcoming days.
    """

    city = city.strip()

    if not city:
        raise ValueError(
            "city cannot be empty"
        )

    days = max(1, min(int(days), 5))

    data = _request_json(
        "https://api.openweathermap.org/data/2.5/forecast",
        {
            "q": city,
            "appid": _get_api_key(),
            "units": "metric",
        },
    )

    return {
        "city": data.get(
            "city",
            {},
        ).get(
            "name",
            city,
        ),
        "daily_forecast": _summarise_days(data.get("list", []), days),
    }


if __name__ == "__main__":
    # mcp_client.py launches this as a stdio subprocess.
    mcp.run(
        transport="stdio",
    )
