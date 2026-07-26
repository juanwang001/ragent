/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.nageoffer.ai.ragent.mcp.weather.infrastructure.location;

import com.nageoffer.ai.ragent.mcp.weather.application.port.out.LocationResolver;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.AdministrativeLocationQuery;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Loads the generated administrative-division CSV once and resolves locations
 * through three immutable maps: province, city-with-parent, and
 * county-with-parent.
 */
@Slf4j
@Component
public class CsvAdministrativeDivisionResolver implements LocationResolver {

    static final String DEFAULT_RESOURCE = "weather/china-mainland-divisions-wgs84.csv";

    private static final Pattern ADCODE_PATTERN = Pattern.compile("\\d{6}");
    private static final Set<String> MUNICIPALITY_ADCODES = Set.of(
            "110000", "120000", "310000", "500000"
    );
    private static final List<String> PROVINCE_SUFFIXES = List.of(
            "维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省", "市"
    );
    private static final List<String> CITY_SUFFIXES = List.of("自治州", "地区", "市", "盟");
    private static final List<String> COUNTY_SUFFIXES = List.of(
            "自治县", "林区", "特区", "新区", "矿区", "区", "县", "旗", "市"
    );

    private final Map<String, AdministrativeDivision> provinceMap;
    private final Map<CityKey, AdministrativeDivision> cityMap;
    private final Map<CountyKey, AdministrativeDivision> countyMap;

    public CsvAdministrativeDivisionResolver() {
        this(new ClassPathResource(DEFAULT_RESOURCE));
    }

    public CsvAdministrativeDivisionResolver(Resource resource) {
        List<AdministrativeDivision> divisions = load(resource);
        Map<String, AdministrativeDivision> byAdcode = validateHierarchy(divisions);

        Map<String, AdministrativeDivision> provinces = new HashMap<>();
        Map<CityKey, AdministrativeDivision> cities = new HashMap<>();
        Map<CountyKey, AdministrativeDivision> counties = new HashMap<>();

        Set<String> exactProvinceKeys = new LinkedHashSet<>();
        Set<CityKey> exactCityKeys = new LinkedHashSet<>();
        Set<CountyKey> exactCountyKeys = new LinkedHashSet<>();
        for (AdministrativeDivision division : divisions) {
            switch (division.level()) {
                case PROVINCE -> putExactProvince(provinces, exactProvinceKeys, division);
                case CITY -> putExactCity(cities, exactCityKeys, division);
                case COUNTY -> putExactCounty(counties, exactCountyKeys, division);
            }
        }

        Set<String> ambiguousProvinceAliases = new LinkedHashSet<>();
        Set<CityKey> ambiguousCityAliases = new LinkedHashSet<>();
        Set<CountyKey> ambiguousCountyAliases = new LinkedHashSet<>();
        for (AdministrativeDivision division : divisions) {
            switch (division.level()) {
                case PROVINCE -> putProvinceShortAlias(
                        provinces,
                        exactProvinceKeys,
                        ambiguousProvinceAliases,
                        division
                );
                case CITY -> putCityShortAlias(
                        cities,
                        exactCityKeys,
                        ambiguousCityAliases,
                        division
                );
                case COUNTY -> putCountyShortAlias(
                        counties,
                        exactCountyKeys,
                        ambiguousCountyAliases,
                        division
                );
            }
        }

        provinceMap = Map.copyOf(provinces);
        cityMap = Map.copyOf(cities);
        countyMap = Map.copyOf(counties);
        log.info(
                "天气行政区索引加载完成，records={}, provinces={}, cities={}, counties={}",
                byAdcode.size(),
                divisions.stream().filter(item -> item.level() == DivisionLevel.PROVINCE).count(),
                divisions.stream().filter(item -> item.level() == DivisionLevel.CITY).count(),
                divisions.stream().filter(item -> item.level() == DivisionLevel.COUNTY).count()
        );
    }

    @Override
    public GeoLocation resolve(AdministrativeLocationQuery query) {
        if (query == null || query.province() == null) {
            throw new IllegalArgumentException("请提供规范的省级行政区名称");
        }

        AdministrativeDivision province = provinceMap.get(normalize(query.province()));
        if (province == null) {
            throw new IllegalArgumentException("未找到省级行政区：" + query.province());
        }

        if (query.city() == null && query.district() == null) {
            return province.toGeoLocation();
        }

        AdministrativeDivision city = null;
        if (query.city() != null) {
            city = cityMap.get(new CityKey(province.adcode(), normalize(query.city())));
            if (city == null) {
                throw new IllegalArgumentException(
                        "未在" + province.province() + "找到城市：" + query.city()
                );
            }
        } else if (query.district() != null && MUNICIPALITY_ADCODES.contains(province.adcode())) {
            city = cityMap.get(new CityKey(province.adcode(), normalize(province.province())));
            if (city == null) {
                throw new IllegalStateException("直辖市缺少市级索引：" + province.fullName());
            }
        }

        if (query.district() == null) {
            if (city == null) {
                return province.toGeoLocation();
            }
            return city.toGeoLocation();
        }

        String countyParentAdcode = city == null ? province.adcode() : city.adcode();
        AdministrativeDivision county = countyMap.get(
                new CountyKey(countyParentAdcode, normalize(query.district()))
        );
        if (county != null) {
            return county.toGeoLocation();
        }

        if (city == null) {
            throw new IllegalArgumentException(
                    "未在" + province.province() + "找到省直辖区县：" + query.district()
                            + "；普通区县请补充所属城市"
            );
        }
        throw new IllegalArgumentException(
                "未在" + city.fullName() + "找到区县：" + query.district()
        );
    }

    private static List<AdministrativeDivision> load(Resource resource) {
        CSVFormat format = CSVFormat.DEFAULT.builder()
                .setHeader()
                .setSkipHeaderRecord(true)
                .setTrim(true)
                .get();
        try (
                Reader reader = new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8);
                CSVParser parser = format.parse(reader)
        ) {
            ensureHeaders(parser);
            return parser.stream().map(CsvAdministrativeDivisionResolver::parseRecord).toList();
        } catch (IOException e) {
            throw new IllegalStateException("无法读取天气行政区 CSV：" + resource.getDescription(), e);
        }
    }

    private static void ensureHeaders(CSVParser parser) {
        Set<String> required = Set.of(
                "adcode",
                "parent_adcode",
                "level",
                "province",
                "city",
                "district",
                "full_name",
                "longitude",
                "latitude",
                "coordinate_system"
        );
        if (!parser.getHeaderMap().keySet().containsAll(required)) {
            throw new IllegalStateException("天气行政区 CSV 字段不完整");
        }
    }

    private static AdministrativeDivision parseRecord(CSVRecord record) {
        try {
            String adcode = record.get("adcode");
            if (!ADCODE_PATTERN.matcher(adcode).matches()) {
                throw new IllegalArgumentException("adcode 必须为六位数字");
            }
            String coordinateSystem = record.get("coordinate_system");
            if (!"WGS84".equals(coordinateSystem)) {
                throw new IllegalArgumentException("坐标系必须为 WGS84");
            }
            return new AdministrativeDivision(
                    adcode,
                    blankToNull(record.get("parent_adcode")),
                    DivisionLevel.valueOf(record.get("level")),
                    record.get("province"),
                    blankToNull(record.get("city")),
                    blankToNull(record.get("district")),
                    record.get("full_name"),
                    Double.parseDouble(record.get("longitude")),
                    Double.parseDouble(record.get("latitude"))
            );
        } catch (RuntimeException e) {
            throw new IllegalStateException("天气行政区 CSV 第 " + record.getRecordNumber() + " 行无效", e);
        }
    }

    private static Map<String, AdministrativeDivision> validateHierarchy(
            List<AdministrativeDivision> divisions
    ) {
        Map<String, AdministrativeDivision> byAdcode = new HashMap<>();
        for (AdministrativeDivision division : divisions) {
            AdministrativeDivision previous = byAdcode.putIfAbsent(division.adcode(), division);
            if (previous != null) {
                throw new IllegalStateException("天气行政区 adcode 重复：" + division.adcode());
            }
        }
        if (byAdcode.size() < 3000) {
            throw new IllegalStateException("天气行政区记录数异常：" + byAdcode.size());
        }

        for (AdministrativeDivision division : divisions) {
            if (division.level() == DivisionLevel.PROVINCE) {
                if (division.parentAdcode() != null) {
                    throw new IllegalStateException("省级行政区不应有父级：" + division.adcode());
                }
                continue;
            }
            AdministrativeDivision parent = byAdcode.get(division.parentAdcode());
            if (parent == null) {
                throw new IllegalStateException("行政区父级不存在：" + division.adcode());
            }
            if (division.level() == DivisionLevel.CITY && parent.level() != DivisionLevel.PROVINCE) {
                throw new IllegalStateException("市级行政区父级必须是省级：" + division.adcode());
            }
            if (division.level() == DivisionLevel.COUNTY
                    && parent.level() != DivisionLevel.CITY
                    && parent.level() != DivisionLevel.PROVINCE) {
                throw new IllegalStateException("区县级行政区父级无效：" + division.adcode());
            }
        }
        return byAdcode;
    }

    private static void putExactProvince(
            Map<String, AdministrativeDivision> provinces,
            Set<String> exactKeys,
            AdministrativeDivision division
    ) {
        String key = normalize(division.province());
        putUnique(provinces, key, division, "省级");
        exactKeys.add(key);
    }

    private static void putExactCity(
            Map<CityKey, AdministrativeDivision> cities,
            Set<CityKey> exactKeys,
            AdministrativeDivision division
    ) {
        CityKey key = new CityKey(division.parentAdcode(), normalize(division.city()));
        putUnique(cities, key, division, "市级");
        exactKeys.add(key);
    }

    private static void putExactCounty(
            Map<CountyKey, AdministrativeDivision> counties,
            Set<CountyKey> exactKeys,
            AdministrativeDivision division
    ) {
        CountyKey key = new CountyKey(division.parentAdcode(), normalize(division.district()));
        putUnique(counties, key, division, "区县级");
        exactKeys.add(key);
    }

    private static void putProvinceShortAlias(
            Map<String, AdministrativeDivision> provinces,
            Set<String> exactKeys,
            Set<String> ambiguousAliases,
            AdministrativeDivision division
    ) {
        String alias = shortAlias(division.province(), PROVINCE_SUFFIXES);
        putUnambiguousAlias(provinces, exactKeys, ambiguousAliases, alias, division);
    }

    private static void putCityShortAlias(
            Map<CityKey, AdministrativeDivision> cities,
            Set<CityKey> exactKeys,
            Set<CityKey> ambiguousAliases,
            AdministrativeDivision division
    ) {
        String alias = shortAlias(division.city(), CITY_SUFFIXES);
        CityKey key = alias == null ? null : new CityKey(division.parentAdcode(), alias);
        putUnambiguousAlias(cities, exactKeys, ambiguousAliases, key, division);
    }

    private static void putCountyShortAlias(
            Map<CountyKey, AdministrativeDivision> counties,
            Set<CountyKey> exactKeys,
            Set<CountyKey> ambiguousAliases,
            AdministrativeDivision division
    ) {
        String alias = shortAlias(division.district(), COUNTY_SUFFIXES);
        CountyKey key = alias == null ? null : new CountyKey(division.parentAdcode(), alias);
        putUnambiguousAlias(counties, exactKeys, ambiguousAliases, key, division);
    }

    private static String shortAlias(String name, List<String> suffixes) {
        if (name == null) {
            throw new IllegalStateException("行政区名称不能为空");
        }
        String normalized = normalize(name);
        for (String suffix : suffixes) {
            if (normalized.endsWith(suffix) && normalized.length() > suffix.length()) {
                return normalized.substring(0, normalized.length() - suffix.length());
            }
        }
        return null;
    }

    private static <K> void putUnambiguousAlias(
            Map<K, AdministrativeDivision> index,
            Set<K> exactKeys,
            Set<K> ambiguousAliases,
            K key,
            AdministrativeDivision division
    ) {
        if (key == null || exactKeys.contains(key) || ambiguousAliases.contains(key)) {
            return;
        }
        AdministrativeDivision previous = index.putIfAbsent(key, division);
        if (previous != null && !previous.adcode().equals(division.adcode())) {
            index.remove(key);
            ambiguousAliases.add(key);
            log.warn(
                    "忽略有歧义的天气行政区简称：{} -> {}/{}",
                    key,
                    previous.adcode(),
                    division.adcode()
            );
        }
    }

    private static <K> void putUnique(
            Map<K, AdministrativeDivision> index,
            K key,
            AdministrativeDivision division,
            String level
    ) {
        AdministrativeDivision previous = index.putIfAbsent(key, division);
        if (previous != null && !previous.adcode().equals(division.adcode())) {
            throw new IllegalStateException(
                    level + "行政区别名冲突：" + key + " -> "
                            + previous.adcode() + "/" + division.adcode()
            );
        }
    }

    private static String normalize(String value) {
        return value == null ? null : value.replaceAll("\\s+", "").trim();
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    private enum DivisionLevel {
        PROVINCE,
        CITY,
        COUNTY
    }

    private record CityKey(String provinceAdcode, String cityName) {
    }

    private record CountyKey(String parentAdcode, String countyName) {
    }

    private record AdministrativeDivision(
            String adcode,
            String parentAdcode,
            DivisionLevel level,
            String province,
            String city,
            String district,
            String fullName,
            double longitude,
            double latitude
    ) {

        GeoLocation toGeoLocation() {
            return new GeoLocation(adcode, fullName, "CN", latitude, longitude);
        }
    }
}
