"""
Reverse-Geocoding Extension for GroupConnect Channels.
Provides optional coordinate conversion (WGS-84 to GCJ-02) and Amap reverse-geocoding
for IM platforms that deliver raw location coordinates (e.g. Telegram location pins).
"""

import logging
import math
import os
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("groupconnect.channels.extensions.geocoding")


def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
    """Convert WGS-84 (GPS / Google global) coords to GCJ-02 (Amap / China datum).

    Uses the public GCJ-02 offset model. Points outside mainland China are
    returned unchanged, since GCJ-02 only applies within China.
    """
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lon, lat
    a, ee = 6378245.0, 0.00669342162296594323
    x, y = lon - 105.0, lat - 35.0
    d_lat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    d_lat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    d_lat += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    d_lon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    d_lon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    d_lon += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lon + d_lon, lat + d_lat


async def resolve_address(
    lat: Optional[float],
    lon: Optional[float],
    client: Optional[httpx.AsyncClient] = None,
    api_key: Optional[str] = None,
) -> str:
    """Reverse-geocode (lat, lon) into a human-readable address via Amap.

    Input coords are treated as WGS-84 (GPS origin) and converted to GCJ-02 before querying.
    Returns "" on missing key, network error, or invalid coords, allowing graceful fallback.
    """
    key = api_key or os.environ.get("AMAP_WEB_KEY", "")
    if not key or lat is None or lon is None:
        return ""

    try:
        gcj_lon, gcj_lat = wgs84_to_gcj02(float(lon), float(lat))
        params = {
            "location": f"{gcj_lon:.6f},{gcj_lat:.6f}",
            "key": key,
            "extensions": "base",
        }
        url = "https://restapi.amap.com/v3/geocode/regeo"
        timeout = httpx.Timeout(3.0)

        if client is not None:
            resp = await client.get(url, params=params, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(url, params=params)

        data = resp.json()
        if data.get("status") == "1":
            return str(data.get("regeocode", {}).get("formatted_address", "") or "")
        logger.warning(f"Amap regeo rejected ({lat}, {lon}): {data.get('info', '')}")
    except Exception as e:
        logger.warning(f"Amap regeo failed for ({lat}, {lon}): {e}")

    return ""

