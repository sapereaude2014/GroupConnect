import unittest
from unittest.mock import AsyncMock, patch

from groupconnect.channels.extensions.geocoding import resolve_address, wgs84_to_gcj02


class TestGeocodingExtension(unittest.IsolatedAsyncioTestCase):
    def test_wgs84_to_gcj02_conversion(self):
        # Coordinates in Beijing
        lon, lat = 116.4074, 39.9042
        gcj_lon, gcj_lat = wgs84_to_gcj02(lon, lat)
        self.assertNotEqual((lon, lat), (gcj_lon, gcj_lat))
        # Coordinates outside China returned unchanged
        outside_lon, outside_lat = 0.0, 0.0
        self.assertEqual(wgs84_to_gcj02(outside_lon, outside_lat), (0.0, 0.0))

    async def test_resolve_address_no_key_graceful_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            addr = await resolve_address(39.9042, 116.4074, api_key="")
            self.assertEqual(addr, "")

    async def test_resolve_address_missing_coords(self):
        addr = await resolve_address(None, None, api_key="dummy_key")
        self.assertEqual(addr, "")

    async def test_resolve_address_success(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=AsyncMock(
            json=lambda: {"status": "1", "regeocode": {"formatted_address": "北京市东城区故宫博物院"}}
        ))

        addr = await resolve_address(39.9042, 116.4074, client=mock_client, api_key="valid_key")
        self.assertEqual(addr, "北京市东城区故宫博物院")
        mock_client.get.assert_called_once()

    async def test_resolve_address_api_error_fallback(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=AsyncMock(
            json=lambda: {"status": "0", "info": "INVALID_USER_KEY"}
        ))

        addr = await resolve_address(39.9042, 116.4074, client=mock_client, api_key="invalid_key")
        self.assertEqual(addr, "")

    async def test_resolve_address_network_exception_fallback(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection reset by peer")

        addr = await resolve_address(39.9042, 116.4074, client=mock_client, api_key="valid_key")
        self.assertEqual(addr, "")


if __name__ == "__main__":
    unittest.main()

