#!/usr/bin/env python3
"""Build a small WGS84 administrative-division CSV from offline vector data.

The vector source supplies geometry. A separate metadata CSV supplies stable
administrative codes and hierarchy. They are joined by a six-digit adcode so
the build never relies on fuzzy name matching.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ADCODE_PATTERN = re.compile(r"^\d{6}$")
VALID_LEVELS = {"PROVINCE", "CITY", "COUNTY"}
OUTPUT_FIELDS = (
    "adcode",
    "parent_adcode",
    "level",
    "province",
    "city",
    "district",
    "full_name",
    "longitude",
    "latitude",
    "coordinate_system",
)

# These are deliberately loose and are only intended to catch swapped or
# obviously corrupt coordinates before the generated file enters the service.
MIN_CHINA_LONGITUDE = 73.0
MAX_CHINA_LONGITUDE = 136.0
MIN_CHINA_LATITUDE = 3.0
MAX_CHINA_LATITUDE = 54.0

MAINLAND_PROVINCE_PREFIXES = {
    "11", "12", "13", "14", "15",
    "21", "22", "23",
    "31", "32", "33", "34", "35", "36", "37",
    "41", "42", "43", "44", "45", "46",
    "50", "51", "52", "53", "54",
    "61", "62", "63", "64", "65",
}

AREACITY_SOURCE_NAME = "xiangyuecn/AreaCity-JsSpider-StatsGov"
AREACITY_RELEASE_URL = (
    "https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov/"
    "releases/tag/2025.251231.260403"
)

DEFAULT_REQUIRED_LOCATIONS = {
    "110108": "海淀区",
    "330106": "西湖区",
    "420111": "洪山区",
    "440305": "南山区",
    "419001": "济源市",
    "620200": "嘉峪关市",
}


@dataclass(frozen=True)
class AdminDivision:
    adcode: str
    parent_adcode: str
    level: str
    province: str
    city: str
    district: str
    full_name: str


@dataclass(frozen=True)
class Coordinate:
    longitude: float
    latitude: float


@dataclass(frozen=True)
class AreaCitySourceRow:
    source_id: str
    parent_source_id: str
    depth: int
    ext_id: str
    ext_name: str


@dataclass(frozen=True)
class AreaCityBuildStats:
    source_admin_records: int
    source_geo_records: int
    output_records: int
    collapsed_synthetic_records: int
    excluded_non_mainland_records: int


def _outside_china(coordinate: Coordinate) -> bool:
    return not (
        72.004 <= coordinate.longitude <= 137.8347
        and 0.8293 <= coordinate.latitude <= 55.8271
    )


def _gcj02_offset(coordinate: Coordinate) -> Coordinate:
    """Return the standard GCJ-02 offset for a WGS84 coordinate."""
    if _outside_china(coordinate):
        return Coordinate(0.0, 0.0)

    x = coordinate.longitude - 105.0
    y = coordinate.latitude - 35.0
    latitude_offset = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
        + (
            20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)
        )
        * 2.0
        / 3.0
        + (
            20.0 * math.sin(y * math.pi)
            + 40.0 * math.sin(y / 3.0 * math.pi)
        )
        * 2.0
        / 3.0
        + (
            160.0 * math.sin(y / 12.0 * math.pi)
            + 320.0 * math.sin(y * math.pi / 30.0)
        )
        * 2.0
        / 3.0
    )
    longitude_offset = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
        + (
            20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)
        )
        * 2.0
        / 3.0
        + (
            20.0 * math.sin(x * math.pi)
            + 40.0 * math.sin(x / 3.0 * math.pi)
        )
        * 2.0
        / 3.0
        + (
            150.0 * math.sin(x / 12.0 * math.pi)
            + 300.0 * math.sin(x / 30.0 * math.pi)
        )
        * 2.0
        / 3.0
    )

    latitude_radians = coordinate.latitude / 180.0 * math.pi
    magic = math.sin(latitude_radians)
    magic = 1.0 - 0.00669342162296594323 * magic * magic
    sqrt_magic = math.sqrt(magic)
    latitude_offset = (
        latitude_offset * 180.0
        / (
            (6378245.0 * (1.0 - 0.00669342162296594323))
            / (magic * sqrt_magic)
            * math.pi
        )
    )
    longitude_offset = (
        longitude_offset * 180.0
        / (6378245.0 / sqrt_magic * math.cos(latitude_radians) * math.pi)
    )
    return Coordinate(longitude_offset, latitude_offset)


def wgs84_to_gcj02(coordinate: Coordinate) -> Coordinate:
    offset = _gcj02_offset(coordinate)
    return Coordinate(
        longitude=coordinate.longitude + offset.longitude,
        latitude=coordinate.latitude + offset.latitude,
    )


def gcj02_to_wgs84(coordinate: Coordinate) -> Coordinate:
    """Invert GCJ-02 by binary search to better than 1e-7 degrees."""
    if _outside_china(coordinate):
        return coordinate

    longitude_low = coordinate.longitude - 0.02
    longitude_high = coordinate.longitude + 0.02
    latitude_low = coordinate.latitude - 0.02
    latitude_high = coordinate.latitude + 0.02

    result = coordinate
    for _ in range(32):
        result = Coordinate(
            longitude=(longitude_low + longitude_high) / 2.0,
            latitude=(latitude_low + latitude_high) / 2.0,
        )
        projected = wgs84_to_gcj02(result)
        longitude_delta = projected.longitude - coordinate.longitude
        latitude_delta = projected.latitude - coordinate.latitude
        if (
            abs(longitude_delta) < 1e-8
            and abs(latitude_delta) < 1e-8
        ):
            break
        if longitude_delta > 0:
            longitude_high = result.longitude
        else:
            longitude_low = result.longitude
        if latitude_delta > 0:
            latitude_high = result.latitude
        else:
            latitude_low = result.latitude
    return result


def normalize_adcode(raw_value: object) -> str:
    """Normalize values such as the spreadsheet form ``420111.0``."""
    value = "" if raw_value is None else str(raw_value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    if not ADCODE_PATTERN.fullmatch(value):
        raise ValueError(f"行政区划代码必须是 6 位数字，实际值：{raw_value!r}")
    return value


def normalize_optional_adcode(raw_value: object) -> str:
    value = "" if raw_value is None else str(raw_value).strip()
    return "" if not value else normalize_adcode(value)


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    return "" if value is None else str(value).strip()


def _derived_full_name(
    province: str,
    city: str,
    district: str,
) -> str:
    # A municipality commonly repeats itself in province and city columns.
    parts: list[str] = []
    for value in (province, city, district):
        if value and (not parts or parts[-1] != value):
            parts.append(value)
    return "".join(parts)


def load_admin_metadata(path: Path) -> dict[str, AdminDivision]:
    required_fields = {
        "adcode",
        "parent_adcode",
        "level",
        "province",
        "city",
        "district",
        "full_name",
    }
    divisions: dict[str, AdminDivision] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_fields = set(reader.fieldnames or ())
        missing_fields = sorted(required_fields - actual_fields)
        if missing_fields:
            raise ValueError(
                f"行政区元数据缺少字段：{', '.join(missing_fields)}"
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                adcode = normalize_adcode(row.get("adcode"))
                if adcode in divisions:
                    raise ValueError(f"adcode 重复：{adcode}")

                level = _text(row, "level").upper()
                if level not in VALID_LEVELS:
                    raise ValueError(
                        f"level 必须是 {sorted(VALID_LEVELS)}，实际值：{level!r}"
                    )

                province = _text(row, "province")
                city = _text(row, "city")
                district = _text(row, "district")
                full_name = _text(row, "full_name") or _derived_full_name(
                    province,
                    city,
                    district,
                )
                if not full_name:
                    raise ValueError("full_name 不能为空")

                divisions[adcode] = AdminDivision(
                    adcode=adcode,
                    parent_adcode=normalize_optional_adcode(
                        row.get("parent_adcode")
                    ),
                    level=level,
                    province=province,
                    city=city,
                    district=district,
                    full_name=full_name,
                )
            except ValueError as error:
                raise ValueError(
                    f"行政区元数据第 {line_number} 行无效：{error}"
                ) from error

    if not divisions:
        raise ValueError(f"行政区元数据为空：{path}")

    for division in divisions.values():
        if division.level == "PROVINCE":
            if division.parent_adcode:
                raise ValueError(
                    f"省级行政区 {division.adcode} 不应设置父级 "
                    f"{division.parent_adcode}"
                )
            continue

        if not division.parent_adcode:
            raise ValueError(f"行政区 {division.adcode} 缺少父级 adcode")

        parent = divisions.get(division.parent_adcode)
        if parent is None:
            raise ValueError(
                f"行政区 {division.adcode} 的父级 "
                f"{division.parent_adcode} 不存在"
            )

        allowed_parent_levels = (
            {"PROVINCE"}
            if division.level == "CITY"
            else {"PROVINCE", "CITY"}
        )
        if parent.level not in allowed_parent_levels:
            raise ValueError(
                f"行政区 {division.adcode} 的父级层级无效："
                f"{parent.level}"
            )
    return divisions


def validate_coordinate(coordinate: Coordinate, adcode: str) -> None:
    if not MIN_CHINA_LONGITUDE <= coordinate.longitude <= MAX_CHINA_LONGITUDE:
        raise ValueError(
            f"adcode={adcode} 经度超出中国宽松边界："
            f"{coordinate.longitude}"
        )
    if not MIN_CHINA_LATITUDE <= coordinate.latitude <= MAX_CHINA_LATITUDE:
        raise ValueError(
            f"adcode={adcode} 纬度超出中国宽松边界："
            f"{coordinate.latitude}"
        )


def _source_adcode(ext_id: str) -> str:
    if not re.fullmatch(r"\d{12}", ext_id):
        raise ValueError(f"数据源 ext_id 不是 12 位数字：{ext_id!r}")
    return normalize_adcode(ext_id[:6])


def _read_areacity_admin(path: Path) -> list[AreaCitySourceRow]:
    required_fields = {"id", "pid", "deep", "ext_id", "ext_name"}
    rows: list[AreaCitySourceRow] = []
    source_ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(required_fields - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"AreaCity 行政区 CSV 缺少字段：{', '.join(missing)}")
        for line_number, raw in enumerate(reader, start=2):
            source_id = _text(raw, "id")
            if not source_id or source_id in source_ids:
                raise ValueError(
                    f"AreaCity 行政区 CSV 第 {line_number} 行 id 为空或重复："
                    f"{source_id!r}"
                )
            source_ids.add(source_id)
            try:
                depth = int(_text(raw, "deep"))
            except ValueError as error:
                raise ValueError(
                    f"AreaCity 行政区 CSV 第 {line_number} 行 deep 无效"
                ) from error
            if depth not in {0, 1, 2}:
                raise ValueError(
                    f"AreaCity 行政区 CSV 第 {line_number} 行 deep 超出三级范围"
                )
            rows.append(
                AreaCitySourceRow(
                    source_id=source_id,
                    parent_source_id=_text(raw, "pid"),
                    depth=depth,
                    ext_id=_text(raw, "ext_id"),
                    ext_name=_text(raw, "ext_name"),
                )
            )
    return rows


def _select_mainland_rows(
    rows: Sequence[AreaCitySourceRow],
) -> tuple[list[AreaCitySourceRow], int, int]:
    grouped: dict[str, list[AreaCitySourceRow]] = {}
    excluded = 0
    for row in rows:
        if row.ext_id == "0" or row.ext_id[:2] not in MAINLAND_PROVINCE_PREFIXES:
            excluded += 1
            continue
        adcode = _source_adcode(row.ext_id)
        grouped.setdefault(adcode, []).append(row)

    selected: list[AreaCitySourceRow] = []
    collapsed = 0
    for adcode, candidates in grouped.items():
        if len(candidates) == 1:
            selected.append(candidates[0])
            continue

        # AreaCity inserts nodes to force every location into a three-level
        # selector. For prefecture-level cities without counties, the real
        # code ends in 00 and the city row is authoritative. For a
        # province-administered county, the code does not end in 00 and the
        # deepest county row is authoritative.
        target_depth = 1 if adcode.endswith("00") else 2
        authoritative = [
            row for row in candidates if row.depth == target_depth
        ]
        if len(authoritative) != 1:
            details = ", ".join(
                f"id={row.source_id}/deep={row.depth}" for row in candidates
            )
            raise ValueError(
                f"无法折叠 AreaCity 补齐节点 adcode={adcode}：{details}"
            )
        selected.append(authoritative[0])
        collapsed += len(candidates) - 1
    return selected, collapsed, excluded


def _find_selected_parent(
    row: AreaCitySourceRow,
    all_by_source_id: Mapping[str, AreaCitySourceRow],
    selected_by_adcode: Mapping[str, AreaCitySourceRow],
) -> str:
    current_adcode = _source_adcode(row.ext_id)
    parent_source_id = row.parent_source_id
    visited: set[str] = set()
    while parent_source_id and parent_source_id != "0":
        if parent_source_id in visited:
            raise ValueError(f"AreaCity 父级关系出现循环：{row.source_id}")
        visited.add(parent_source_id)
        parent = all_by_source_id.get(parent_source_id)
        if parent is None:
            raise ValueError(
                f"AreaCity 节点 {row.source_id} 的父级不存在："
                f"{parent_source_id}"
            )
        if (
            parent.ext_id != "0"
            and parent.ext_id[:2] in MAINLAND_PROVINCE_PREFIXES
        ):
            parent_adcode = _source_adcode(parent.ext_id)
            if (
                parent_adcode != current_adcode
                and parent_adcode in selected_by_adcode
            ):
                return parent_adcode
        parent_source_id = parent.parent_source_id
    return ""


def load_areacity_mainland(
    admin_path: Path,
    geo_path: Path,
) -> tuple[
    dict[str, AdminDivision],
    dict[str, Coordinate],
    AreaCityBuildStats,
]:
    """Load current AreaCity data and collapse it to real mainland divisions."""
    source_rows = _read_areacity_admin(admin_path)
    all_by_source_id = {row.source_id: row for row in source_rows}
    selected, collapsed, excluded = _select_mainland_rows(source_rows)
    selected_by_adcode = {
        _source_adcode(row.ext_id): row for row in selected
    }

    metadata: dict[str, AdminDivision] = {}
    level_by_depth = {0: "PROVINCE", 1: "CITY", 2: "COUNTY"}
    for row in selected:
        adcode = _source_adcode(row.ext_id)
        parent_adcode = _find_selected_parent(
            row,
            all_by_source_id,
            selected_by_adcode,
        )
        if row.depth > 0 and not parent_adcode:
            raise ValueError(f"AreaCity 节点 {row.source_id} 缺少有效父级")

        province_code = f"{adcode[:2]}0000"
        province_row = selected_by_adcode.get(province_code)
        if province_row is None or province_row.depth != 0:
            raise ValueError(f"adcode={adcode} 缺少省级节点 {province_code}")
        province = province_row.ext_name
        city = ""
        district = ""
        if row.depth == 1:
            city = row.ext_name
        elif row.depth == 2:
            district = row.ext_name
            parent = selected_by_adcode[parent_adcode]
            if parent.depth == 1:
                city = parent.ext_name

        metadata[adcode] = AdminDivision(
            adcode=adcode,
            parent_adcode=parent_adcode,
            level=level_by_depth[row.depth],
            province=province,
            city=city,
            district=district,
            full_name=_derived_full_name(province, city, district),
        )

    csv.field_size_limit(sys.maxsize)
    coordinates_by_source_id: dict[str, Coordinate] = {}
    source_geo_records = 0
    selected_source_ids = {row.source_id for row in selected}
    with geo_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"id", "geo"}
        missing = sorted(required_fields - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"AreaCity 坐标 CSV 缺少字段：{', '.join(missing)}")
        for raw in reader:
            source_geo_records += 1
            source_id = _text(raw, "id")
            if source_id not in selected_source_ids:
                continue
            geo = _text(raw, "geo")
            if geo == "EMPTY":
                continue
            parts = geo.split()
            if len(parts) != 2:
                raise ValueError(
                    f"AreaCity 节点 {source_id} 的 geo 格式无效：{geo!r}"
                )
            gcj02 = Coordinate(
                longitude=float(parts[0]),
                latitude=float(parts[1]),
            )
            coordinates_by_source_id[source_id] = gcj02_to_wgs84(gcj02)

    coordinates: dict[str, Coordinate] = {}
    missing_source_ids: list[str] = []
    for adcode, row in selected_by_adcode.items():
        coordinate = coordinates_by_source_id.get(row.source_id)
        if coordinate is None:
            missing_source_ids.append(row.source_id)
            continue
        validate_coordinate(coordinate, adcode)
        coordinates[adcode] = coordinate
    if missing_source_ids:
        preview = ", ".join(missing_source_ids[:10])
        raise ValueError(
            f"{len(missing_source_ids)} 个大陆行政区缺少中心点：{preview}"
        )

    stats = AreaCityBuildStats(
        source_admin_records=len(source_rows),
        source_geo_records=source_geo_records,
        output_records=len(metadata),
        collapsed_synthetic_records=collapsed,
        excluded_non_mainland_records=excluded,
    )
    return metadata, coordinates, stats


def write_location_csv(
    output: Path,
    metadata: Mapping[str, AdminDivision],
    coordinates: Mapping[str, Coordinate],
    minimum_records: int,
    maximum_records: int,
) -> int:
    if minimum_records < 1 or maximum_records < minimum_records:
        raise ValueError("记录数范围配置无效")

    missing_coordinates = sorted(set(metadata) - set(coordinates))
    if missing_coordinates:
        preview = ", ".join(missing_coordinates[:10])
        suffix = "..." if len(missing_coordinates) > 10 else ""
        raise ValueError(
            f"{len(missing_coordinates)} 个行政区缺少坐标：{preview}{suffix}"
        )

    record_count = len(metadata)
    if not minimum_records <= record_count <= maximum_records:
        raise ValueError(
            f"输出记录数异常：{record_count}，预期范围："
            f"{minimum_records}～{maximum_records}"
        )

    for adcode, coordinate in coordinates.items():
        if adcode in metadata:
            validate_coordinate(coordinate, adcode)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=output.parent,
            prefix=f"{output.name}.",
            suffix=".tmp",
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            for adcode in sorted(metadata):
                division = metadata[adcode]
                coordinate = coordinates[adcode]
                writer.writerow(
                    {
                        **asdict(division),
                        "longitude": f"{coordinate.longitude:.6f}",
                        "latitude": f"{coordinate.latitude:.6f}",
                        "coordinate_system": "WGS84",
                    }
                )
        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return record_count


def validate_location_csv_file(
    path: Path,
    expected_province_count: int = 31,
    required_adcodes: Mapping[str, str] | None = None,
) -> dict[str, object]:
    required_fields = set(OUTPUT_FIELDS)
    rows_by_adcode: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_fields = sorted(required_fields - set(reader.fieldnames or ()))
        if missing_fields:
            raise ValueError(
                f"输出 CSV 缺少字段：{', '.join(missing_fields)}"
            )
        for line_number, row in enumerate(reader, start=2):
            adcode = normalize_adcode(row.get("adcode"))
            if adcode in rows_by_adcode:
                raise ValueError(f"输出 CSV adcode 重复：{adcode}")
            if row.get("coordinate_system") != "WGS84":
                raise ValueError(
                    f"输出 CSV 第 {line_number} 行坐标系不是 WGS84"
                )
            coordinate = Coordinate(
                longitude=float(row["longitude"]),
                latitude=float(row["latitude"]),
            )
            validate_coordinate(coordinate, adcode)
            rows_by_adcode[adcode] = row

    levels = Counter(row["level"] for row in rows_by_adcode.values())
    unknown_levels = set(levels) - VALID_LEVELS
    if unknown_levels:
        raise ValueError(f"输出 CSV 存在未知层级：{sorted(unknown_levels)}")
    if levels["PROVINCE"] != expected_province_count:
        raise ValueError(
            f"省级记录数异常：{levels['PROVINCE']}，"
            f"预期：{expected_province_count}"
        )

    direct_admin_counties = 0
    for adcode, row in rows_by_adcode.items():
        level = row["level"]
        parent_adcode = row["parent_adcode"]
        if level == "PROVINCE":
            if parent_adcode:
                raise ValueError(f"省级记录 {adcode} 不应有父级")
            continue
        if not parent_adcode:
            raise ValueError(f"记录 {adcode} 缺少父级")
        parent = rows_by_adcode.get(parent_adcode)
        if parent is None:
            raise ValueError(
                f"记录 {adcode} 的父级 {parent_adcode} 不存在"
            )
        expected_parent_levels = (
            {"PROVINCE"} if level == "CITY" else {"CITY", "PROVINCE"}
        )
        if parent["level"] not in expected_parent_levels:
            raise ValueError(
                f"记录 {adcode} 的父级层级无效：{parent['level']}"
            )
        if level == "COUNTY" and parent["level"] == "PROVINCE":
            direct_admin_counties += 1

    required_location_rows: dict[str, dict[str, str]] = {}
    for adcode, expected_name in (required_adcodes or {}).items():
        row = rows_by_adcode.get(adcode)
        if row is None:
            raise ValueError(f"关键行政区缺失：{adcode} {expected_name}")
        display_name = row["district"] or row["city"] or row["province"]
        if display_name != expected_name:
            raise ValueError(
                f"关键行政区 {adcode} 名称异常："
                f"{display_name!r} != {expected_name!r}"
            )
        required_location_rows[adcode] = {
            "province": row["province"],
            "city": row["city"],
            "district": row["district"],
            "longitude": row["longitude"],
            "latitude": row["latitude"],
        }

    return {
        "validatedAt": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
        "recordCount": len(rows_by_adcode),
        "levelCounts": {
            level: levels[level]
            for level in ("PROVINCE", "CITY", "COUNTY")
        },
        "directAdminCountyCount": direct_admin_counties,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "requiredLocations": required_location_rows,
    }


def write_validation_report(
    output: Path,
    report: Mapping[str, object],
) -> Path:
    report_path = output.with_suffix(output.suffix + ".validation.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def _expand_inputs(patterns: Sequence[str]) -> list[Path]:
    inputs: list[Path] = []
    for pattern in patterns:
        direct_path = Path(pattern)
        matches = [direct_path] if direct_path.exists() else [
            Path(match) for match in glob.glob(pattern, recursive=True)
        ]
        inputs.extend(path.resolve() for path in matches if path.exists())

    unique_inputs = list(dict.fromkeys(inputs))
    if not unique_inputs:
        raise ValueError("没有找到任何矢量输入文件")
    return unique_inputs


def _require_geospatial_dependencies():
    try:
        import geopandas as geopandas
        import pandas as pandas
        from pyproj import CRS
    except ImportError as error:
        raise RuntimeError(
            "缺少离线地理处理依赖，请先执行："
            "python -m pip install -r "
            "offline/weather-location-data/requirements.txt"
        ) from error
    return geopandas, pandas, CRS


def load_vector_coordinates(
    inputs: Sequence[Path],
    layer: str | None,
    geometry_code_field: str,
    source_crs: str | None,
) -> dict[str, Coordinate]:
    geopandas, pandas, CRS = _require_geospatial_dependencies()
    frames = []

    for input_path in inputs:
        frame = geopandas.read_file(
            input_path,
            layer=layer,
            engine="pyogrio",
        )
        if geometry_code_field not in frame.columns:
            available = ", ".join(map(str, frame.columns))
            raise ValueError(
                f"{input_path} 不包含行政区代码字段 "
                f"{geometry_code_field!r}；现有字段：{available}"
            )
        if frame.crs is None:
            if source_crs is None:
                raise ValueError(
                    f"{input_path} 未声明坐标系，请显式传入 --source-crs"
                )
            frame = frame.set_crs(source_crs)
        elif source_crs is not None:
            expected_crs = CRS.from_user_input(source_crs)
            actual_crs = CRS.from_user_input(frame.crs)
            if actual_crs != expected_crs:
                raise ValueError(
                    f"{input_path} 声明的坐标系为 {actual_crs.to_string()}，"
                    f"与 --source-crs={expected_crs.to_string()} 不一致"
                )

        frame = frame[[geometry_code_field, "geometry"]].copy()
        frame["_adcode"] = frame[geometry_code_field].map(normalize_adcode)
        frame = frame.drop(columns=[geometry_code_field])
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        frame = frame.to_crs("EPSG:4326")
        frames.append(frame)

    combined = geopandas.GeoDataFrame(
        pandas.concat(frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )
    if combined.empty:
        raise ValueError("矢量输入不包含有效行政区几何")

    try:
        combined.geometry = combined.geometry.make_valid()
    except AttributeError:
        combined.geometry = combined.geometry.buffer(0)

    dissolved = combined.dissolve(by="_adcode", as_index=False)
    points = dissolved.geometry.representative_point()

    coordinates: dict[str, Coordinate] = {}
    for adcode, point in zip(dissolved["_adcode"], points, strict=True):
        coordinate = Coordinate(
            longitude=float(point.x),
            latitude=float(point.y),
        )
        validate_coordinate(coordinate, adcode)
        coordinates[adcode] = coordinate
    return coordinates


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    paths = (
        [path]
        if path.is_file()
        else sorted(item for item in path.rglob("*") if item.is_file())
    )
    for item in paths:
        if path.is_dir():
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    output: Path,
    inputs: Iterable[Path],
    admin_metadata: Path,
    source_name: str,
    source_version: str,
    record_count: int,
) -> Path:
    manifest_path = output.with_suffix(output.suffix + ".metadata.json")
    content = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceName": source_name,
        "sourceVersion": source_version,
        "targetCoordinateSystem": "WGS84 (EPSG:4326)",
        "recordCount": record_count,
        "output": {
            "path": output.name,
            "sha256": _sha256(output),
        },
        "adminMetadata": {
            "path": str(admin_metadata),
            "sha256": _sha256(admin_metadata),
        },
        "vectorInputs": [
            {
                "path": str(path),
                "sha256": _sha256(path),
            }
            for path in inputs
        ],
    }
    manifest_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def write_areacity_manifest(
    output: Path,
    admin_source: Path,
    geo_source: Path,
    source_version: str,
    stats: AreaCityBuildStats,
) -> Path:
    manifest_path = output.with_suffix(output.suffix + ".metadata.json")
    content = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "中国大陆 31 个省级行政区的省、市、区县",
        "sourceName": AREACITY_SOURCE_NAME,
        "sourceVersion": source_version,
        "sourceReleaseUrl": AREACITY_RELEASE_URL,
        "sourceCoordinateSystem": "GCJ-02",
        "targetCoordinateSystem": "WGS84 (EPSG:4326)",
        "coordinateTransformation": {
            "method": (
                "iterative inverse of the standard GCJ-02 forward transform"
            ),
            "convergenceThresholdDegrees": 1e-8,
            "maximumIterations": 32,
        },
        "selectionRules": [
            "exclude Taiwan, Hong Kong, Macao and foreign helper records",
            "collapse synthetic selector nodes that duplicate a real adcode",
            "retain province-administered counties directly under province",
        ],
        "statistics": asdict(stats),
        "output": {
            "path": output.name,
            "bytes": output.stat().st_size,
            "sha256": _sha256(output),
        },
        "inputs": [
            {
                "path": str(admin_source),
                "bytes": admin_source.stat().st_size,
                "sha256": _sha256(admin_source),
            },
            {
                "path": str(geo_source),
                "bytes": geo_source.stat().st_size,
                "sha256": _sha256(geo_source),
            },
        ],
    }
    manifest_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def inspect_vector(path: Path, layer: str | None) -> None:
    try:
        import pyogrio
    except ImportError as error:
        raise RuntimeError(
            "缺少 pyogrio，请先安装 requirements.txt"
        ) from error

    print(f"文件：{path}")
    print("图层：")
    for name, geometry_type in pyogrio.list_layers(path):
        print(f"  - {name} ({geometry_type})")

    if layer:
        info = pyogrio.read_info(path, layer=layer)
        print(f"选中图层：{layer}")
        print(f"CRS：{info.get('crs')}")
        print(f"要素数量：{info.get('features')}")
        print("字段：")
        for field in info.get("fields", ()):
            print(f"  - {field}")


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线生成天气模块使用的中国行政区 WGS84 中心点 CSV"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="检查矢量文件的图层、CRS 和字段",
    )
    inspect_parser.add_argument("--input", type=Path, required=True)
    inspect_parser.add_argument("--layer")

    build_parser = subparsers.add_parser(
        "build",
        help="从行政区矢量和元数据生成标准 CSV",
    )
    build_parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="矢量文件路径或 glob；可重复传入",
    )
    build_parser.add_argument("--layer")
    build_parser.add_argument("--geometry-code-field", required=True)
    build_parser.add_argument(
        "--source-crs",
        help="输入未声明 CRS 时使用；官方 CGCS2000 经纬度一般为 EPSG:4490",
    )
    build_parser.add_argument(
        "--admin-metadata",
        type=Path,
        required=True,
    )
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--source-name", required=True)
    build_parser.add_argument("--source-version", required=True)
    build_parser.add_argument("--minimum-records", type=int, default=2500)
    build_parser.add_argument("--maximum-records", type=int, default=4000)

    areacity_parser = subparsers.add_parser(
        "build-areacity",
        help="从 AreaCity 发布包生成中国大陆行政区 WGS84 CSV",
    )
    areacity_parser.add_argument("--admin-source", type=Path, required=True)
    areacity_parser.add_argument("--geo-source", type=Path, required=True)
    areacity_parser.add_argument("--output", type=Path, required=True)
    areacity_parser.add_argument("--source-version", required=True)
    areacity_parser.add_argument("--minimum-records", type=int, default=3000)
    areacity_parser.add_argument("--maximum-records", type=int, default=3500)

    validate_parser = subparsers.add_parser(
        "validate",
        help="独立校验已生成的行政区中心点 CSV",
    )
    validate_parser.add_argument("--input", type=Path, required=True)
    validate_parser.add_argument("--report", type=Path)
    validate_parser.add_argument(
        "--expected-province-count",
        type=int,
        default=31,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _create_parser().parse_args(argv)
    if args.command == "inspect":
        inspect_vector(args.input, args.layer)
        return 0

    if args.command == "validate":
        report = validate_location_csv_file(
            args.input,
            expected_province_count=args.expected_province_count,
            required_adcodes=DEFAULT_REQUIRED_LOCATIONS,
        )
        report_path = args.report or args.input.with_suffix(
            args.input.suffix + ".validation.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"校验通过：{args.input}")
        print(f"校验报告：{report_path}")
        return 0

    if args.command == "build-areacity":
        metadata, coordinates, stats = load_areacity_mainland(
            args.admin_source,
            args.geo_source,
        )
        record_count = write_location_csv(
            output=args.output,
            metadata=metadata,
            coordinates=coordinates,
            minimum_records=args.minimum_records,
            maximum_records=args.maximum_records,
        )
        manifest = write_areacity_manifest(
            output=args.output,
            admin_source=args.admin_source,
            geo_source=args.geo_source,
            source_version=args.source_version,
            stats=stats,
        )
        report = validate_location_csv_file(
            args.output,
            expected_province_count=31,
            required_adcodes=DEFAULT_REQUIRED_LOCATIONS,
        )
        validation_report = write_validation_report(args.output, report)
        print(f"生成 CSV：{args.output}")
        print(f"生成清单：{manifest}")
        print(f"校验报告：{validation_report}")
        print(f"记录数量：{record_count}")
        return 0

    inputs = _expand_inputs(args.input)
    metadata = load_admin_metadata(args.admin_metadata)
    coordinates = load_vector_coordinates(
        inputs=inputs,
        layer=args.layer,
        geometry_code_field=args.geometry_code_field,
        source_crs=args.source_crs,
    )
    record_count = write_location_csv(
        output=args.output,
        metadata=metadata,
        coordinates=coordinates,
        minimum_records=args.minimum_records,
        maximum_records=args.maximum_records,
    )
    manifest = write_manifest(
        output=args.output,
        inputs=inputs,
        admin_metadata=args.admin_metadata,
        source_name=args.source_name,
        source_version=args.source_version,
        record_count=record_count,
    )
    print(f"生成 CSV：{args.output}")
    print(f"生成清单：{manifest}")
    print(f"记录数量：{record_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
