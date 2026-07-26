import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_open_meteo_samples.py"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_open_meteo_samples",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ValidateOpenMeteoSamplesTest(unittest.TestCase):

    def test_haversine_distance_is_zero_for_same_coordinate(self):
        self.assertEqual(
            0.0,
            MODULE.haversine_km(114.3, 30.5, 114.3, 30.5),
        )

    def test_load_samples_uses_exact_adcode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "locations.csv"
            source.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name,"
                "longitude,latitude,coordinate_system\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,"
                "湖北省武汉市洪山区,114.337177,30.503023,WGS84\n",
                encoding="utf-8",
            )

            samples = MODULE.load_samples(source, ["420111"])

        self.assertEqual(1, len(samples))
        self.assertEqual("湖北省武汉市洪山区", samples[0].full_name)
        self.assertEqual(114.337177, samples[0].longitude)

    def test_validate_response_accepts_complete_provider_shape(self):
        sample = MODULE.LocationSample(
            adcode="420111",
            level="COUNTY",
            full_name="湖北省武汉市洪山区",
            longitude=114.337177,
            latitude=30.503023,
        )
        response = {
            "latitude": 30.5,
            "longitude": 114.3125,
            "elevation": 35.0,
            "timezone": "Asia/Shanghai",
            "utc_offset_seconds": 28800,
            "generationtime_ms": 0.3,
            "current": {
                "time": "2026-07-25T20:15",
                "temperature_2m": 31.0,
                "relative_humidity_2m": 60,
                "apparent_temperature": 35.0,
                "weather_code": 2,
                "wind_speed_10m": 8.0,
                "wind_direction_10m": 120,
            },
            "daily": {
                "time": ["2026-07-25"],
                "weather_code": [2],
                "temperature_2m_max": [34.0],
                "temperature_2m_min": [27.0],
                "precipitation_probability_max": [20],
                "wind_speed_10m_max": [12.0],
            },
        }

        result = MODULE.validate_response(
            sample,
            response,
            maximum_grid_distance_km=15.0,
        )

        self.assertEqual("PASS", result["status"])
        self.assertLess(result["gridDistanceKm"], 3.0)
        self.assertEqual(31.0, result["current"]["temperature2m"])

    def test_validate_response_rejects_far_grid_cell(self):
        sample = MODULE.LocationSample(
            adcode="420111",
            level="COUNTY",
            full_name="湖北省武汉市洪山区",
            longitude=114.337177,
            latitude=30.503023,
        )
        response = {
            "latitude": 39.9,
            "longitude": 116.4,
            "timezone": "Asia/Shanghai",
            "utc_offset_seconds": 28800,
            "current": {
                "time": "2026-07-25T20:15",
                "temperature_2m": 31.0,
                "relative_humidity_2m": 60,
                "apparent_temperature": 35.0,
                "weather_code": 2,
                "wind_speed_10m": 8.0,
                "wind_direction_10m": 120,
            },
            "daily": {
                "time": ["2026-07-25"],
                "weather_code": [2],
                "temperature_2m_max": [34.0],
                "temperature_2m_min": [27.0],
                "precipitation_probability_max": [20],
                "wind_speed_10m_max": [12.0],
            },
        }

        with self.assertRaisesRegex(ValueError, "网格"):
            MODULE.validate_response(
                sample,
                response,
                maximum_grid_distance_km=15.0,
            )


if __name__ == "__main__":
    unittest.main()
