#!/usr/bin/env python3
"""Sample a generated location CSV against the live Open-Meteo Forecast API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
)
DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)

# Covers geographic extremes, dense cities and the two special hierarchy
# shapes handled by the offline build.
DEFAULT_SAMPLE_ADCODES = (
    "110108",  # 北京市海淀区
    "230103",  # 黑龙江省哈尔滨市南岗区
    "310115",  # 上海市浦东新区
    "330106",  # 浙江省杭州市西湖区
    "420111",  # 湖北省武汉市洪山区
    "440305",  # 广东省深圳市南山区
    "460203",  # 海南省三亚市吉阳区
    "510107",  # 四川省成都市武侯区
    "540102",  # 西藏自治区拉萨市城关区
    "650102",  # 新疆维吾尔自治区乌鲁木齐市天山区
    "419001",  # 河南省直辖县级济源市
    "620200",  # 不设下辖区县的嘉峪关市
)


@dataclass(frozen=True)
class LocationSample:
    adcode: str
    level: str
    full_name: str
    longitude: float
    latitude: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_samples(
    path: Path,
    sample_adcodes: Sequence[str],
) -> list[LocationSample]:
    requested = list(dict.fromkeys(sample_adcodes))
    rows_by_adcode: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {
            "adcode",
            "level",
            "full_name",
            "longitude",
            "latitude",
            "coordinate_system",
        }
        missing = sorted(required_fields - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"地点 CSV 缺少字段：{', '.join(missing)}")
        for row in reader:
            adcode = row["adcode"]
            if adcode in requested:
                rows_by_adcode[adcode] = row

    missing_adcodes = [code for code in requested if code not in rows_by_adcode]
    if missing_adcodes:
        raise ValueError(f"抽样行政区不存在：{', '.join(missing_adcodes)}")

    samples: list[LocationSample] = []
    for adcode in requested:
        row = rows_by_adcode[adcode]
        if row["coordinate_system"] != "WGS84":
            raise ValueError(f"抽样行政区 {adcode} 不是 WGS84 坐标")
        samples.append(
            LocationSample(
                adcode=adcode,
                level=row["level"],
                full_name=row["full_name"],
                longitude=float(row["longitude"]),
                latitude=float(row["latitude"]),
            )
        )
    return samples


def haversine_km(
    longitude1: float,
    latitude1: float,
    longitude2: float,
    latitude2: float,
) -> float:
    radius_km = 6371.0088
    latitude1_radians = math.radians(latitude1)
    latitude2_radians = math.radians(latitude2)
    latitude_delta = latitude2_radians - latitude1_radians
    longitude_delta = math.radians(longitude2 - longitude1)
    haversine = (
        math.sin(latitude_delta / 2.0) ** 2
        + math.cos(latitude1_radians)
        * math.cos(latitude2_radians)
        * math.sin(longitude_delta / 2.0) ** 2
    )
    return radius_km * 2.0 * math.asin(math.sqrt(haversine))


def _required_number(
    values: Mapping[str, object],
    field: str,
) -> int | float:
    value = values.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Open-Meteo 缺少数值字段：{field}")
    return value


def _required_daily_value(
    daily: Mapping[str, object],
    field: str,
) -> object:
    values = daily.get(field)
    if not isinstance(values, list) or not values or values[0] is None:
        raise ValueError(f"Open-Meteo 缺少日预报字段：{field}")
    return values[0]


def validate_response(
    sample: LocationSample,
    response: Mapping[str, object],
    maximum_grid_distance_km: float,
) -> dict[str, object]:
    response_longitude = float(_required_number(response, "longitude"))
    response_latitude = float(_required_number(response, "latitude"))
    grid_distance = haversine_km(
        sample.longitude,
        sample.latitude,
        response_longitude,
        response_latitude,
    )
    if grid_distance > maximum_grid_distance_km:
        raise ValueError(
            f"Open-Meteo 模型网格距离过大：{grid_distance:.3f} km，"
            f"阈值 {maximum_grid_distance_km:.3f} km"
        )

    if response.get("timezone") != "Asia/Shanghai":
        raise ValueError(
            f"Open-Meteo 时区异常：{response.get('timezone')!r}"
        )
    if response.get("utc_offset_seconds") != 28800:
        raise ValueError(
            "Open-Meteo UTC 偏移异常："
            f"{response.get('utc_offset_seconds')!r}"
        )

    current = response.get("current")
    daily = response.get("daily")
    if not isinstance(current, Mapping):
        raise ValueError("Open-Meteo 缺少 current 对象")
    if not isinstance(daily, Mapping):
        raise ValueError("Open-Meteo 缺少 daily 对象")
    current_time = current.get("time")
    if not isinstance(current_time, str) or not current_time:
        raise ValueError("Open-Meteo 缺少 current.time")

    current_values = {
        "time": current_time,
        "temperature2m": _required_number(current, "temperature_2m"),
        "relativeHumidity2m": _required_number(
            current,
            "relative_humidity_2m",
        ),
        "apparentTemperature": _required_number(
            current,
            "apparent_temperature",
        ),
        "weatherCode": _required_number(current, "weather_code"),
        "windSpeed10m": _required_number(current, "wind_speed_10m"),
        "windDirection10m": _required_number(
            current,
            "wind_direction_10m",
        ),
    }
    daily_values = {
        "date": _required_daily_value(daily, "time"),
        "weatherCode": _required_daily_value(daily, "weather_code"),
        "temperature2mMax": _required_daily_value(
            daily,
            "temperature_2m_max",
        ),
        "temperature2mMin": _required_daily_value(
            daily,
            "temperature_2m_min",
        ),
        "precipitationProbabilityMax": _required_daily_value(
            daily,
            "precipitation_probability_max",
        ),
        "windSpeed10mMax": _required_daily_value(
            daily,
            "wind_speed_10m_max",
        ),
    }

    return {
        "status": "PASS",
        "location": asdict(sample),
        "openMeteoGrid": {
            "longitude": response_longitude,
            "latitude": response_latitude,
            "distanceKm": round(grid_distance, 3),
            "elevationMeters": response.get("elevation"),
            "timezone": response.get("timezone"),
        },
        "gridDistanceKm": round(grid_distance, 3),
        "generationTimeMs": response.get("generationtime_ms"),
        "current": current_values,
        "daily": daily_values,
    }


def _build_url(sample: LocationSample) -> str:
    # Keep the same parameter set and fixed Asia/Shanghai timezone used by
    # OpenMeteoWeatherProvider in mcp-server.
    return (
        f"{FORECAST_ENDPOINT}?latitude={sample.latitude}"
        f"&longitude={sample.longitude}"
        f"&current={','.join(CURRENT_FIELDS)}"
        f"&daily={','.join(DAILY_FIELDS)}"
        "&timezone=Asia%2FShanghai&forecast_days=1"
    )


def request_and_validate(
    sample: LocationSample,
    timeout_seconds: float,
    maximum_grid_distance_km: float,
) -> dict[str, object]:
    url = _build_url(sample)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ragent-open-meteo-sample-validator/1.0",
        },
        method="GET",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status_code = response.status
        payload = json.loads(response.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if status_code < 200 or status_code >= 300:
        raise ValueError(f"Open-Meteo HTTP 状态异常：{status_code}")
    if not isinstance(payload, Mapping):
        raise ValueError("Open-Meteo 返回的 JSON 不是对象")

    result = validate_response(
        sample,
        payload,
        maximum_grid_distance_km=maximum_grid_distance_km,
    )
    result["httpStatus"] = status_code
    result["responseTimeMs"] = round(elapsed_ms, 1)
    result["requestUrl"] = url
    return result


def run_validation(
    csv_path: Path,
    output_path: Path,
    sample_adcodes: Sequence[str],
    timeout_seconds: float,
    maximum_grid_distance_km: float,
) -> dict[str, object]:
    samples = load_samples(csv_path, sample_adcodes)
    results: list[dict[str, object]] = []
    for sample in samples:
        try:
            results.append(
                request_and_validate(
                    sample,
                    timeout_seconds=timeout_seconds,
                    maximum_grid_distance_km=maximum_grid_distance_km,
                )
            )
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            results.append(
                {
                    "status": "FAIL",
                    "location": asdict(sample),
                    "error": str(error),
                    "requestUrl": _build_url(sample),
                }
            )

    passed = [result for result in results if result["status"] == "PASS"]
    failed = [result for result in results if result["status"] == "FAIL"]
    distances = [
        float(result["gridDistanceKm"])
        for result in passed
    ]
    response_times = [
        float(result["responseTimeMs"])
        for result in passed
    ]
    report: dict[str, object] = {
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "csv": {
            "path": str(csv_path),
            "bytes": csv_path.stat().st_size,
            "sha256": _sha256(csv_path),
            "coordinateSystem": "WGS84",
        },
        "openMeteo": {
            "endpoint": FORECAST_ENDPOINT,
            "currentFields": list(CURRENT_FIELDS),
            "dailyFields": list(DAILY_FIELDS),
            "timezone": "Asia/Shanghai",
            "forecastDays": 1,
            "timeoutSeconds": timeout_seconds,
        },
        "criteria": {
            "httpStatus": "2xx",
            "maximumGridDistanceKm": maximum_grid_distance_km,
            "requiredCurrentAndDailyFields": True,
            "timezone": "Asia/Shanghai",
            "utcOffsetSeconds": 28800,
        },
        "summary": {
            "sampleCount": len(results),
            "passCount": len(passed),
            "failCount": len(failed),
            "maximumObservedGridDistanceKm": (
                max(distances) if distances else None
            ),
            "averageGridDistanceKm": (
                round(sum(distances) / len(distances), 3)
                if distances else None
            ),
            "maximumResponseTimeMs": (
                max(response_times) if response_times else None
            ),
            "allPassed": not failed,
        },
        "samples": results,
        "interpretation": {
            "proves": (
                "CSV WGS84 coordinates are accepted by Open-Meteo, map to a "
                "nearby forecast grid cell, and return the complete response "
                "shape consumed by OpenMeteoWeatherProvider."
            ),
            "doesNotProve": (
                "A single live API sample cannot establish meteorological "
                "forecast accuracy against ground-station observations."
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抽样验证地点 CSV 与 Open-Meteo Forecast API 的对应关系"
    )
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sample-adcode",
        action="append",
        dest="sample_adcodes",
        help="六位行政代码；可重复传入。省略时使用默认 12 个样本。",
    )
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument(
        "--maximum-grid-distance-km",
        type=float,
        default=15.0,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _create_parser().parse_args(argv)
    report = run_validation(
        csv_path=args.csv,
        output_path=args.output,
        sample_adcodes=args.sample_adcodes or DEFAULT_SAMPLE_ADCODES,
        timeout_seconds=args.timeout_seconds,
        maximum_grid_distance_km=args.maximum_grid_distance_km,
    )
    summary = report["summary"]
    print(f"抽样数量：{summary['sampleCount']}")
    print(f"通过：{summary['passCount']}")
    print(f"失败：{summary['failCount']}")
    print(f"报告：{args.output}")
    return 0 if summary["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
