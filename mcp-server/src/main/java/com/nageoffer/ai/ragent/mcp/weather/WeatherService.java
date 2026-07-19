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

package com.nageoffer.ai.ragent.mcp.weather;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.concurrent.TimeUnit;

// 协调“先地理编码、再按经纬度缓存天气”的业务流程。
@Slf4j
@Service
@RequiredArgsConstructor
public class WeatherService {

    private static final String CURRENT_CACHE_PREFIX = "ragent:weather:current:cn:";
    private static final String FORECAST_CACHE_PREFIX = "ragent:weather:forecast:cn:";

    private final OpenMeteoWeatherClient openMeteoWeatherClient;
    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;
    private final WeatherProperties properties;

    public WeatherData queryCurrent(String city) {
        // 每次先地理编码，天气缓存永远以供应商返回的地点身份为准。
        GeoLocation location = openMeteoWeatherClient.geocodeChinaCity(city);
        String cacheKey = CURRENT_CACHE_PREFIX + location.cacheLocationId();

        WeatherData cached = readCurrentCache(cacheKey);
        if (cached != null) {
            return cached;
        }

        WeatherData weather = openMeteoWeatherClient.queryCurrent(location);
        writeCache(cacheKey, weather, properties.getCurrentCacheMinutes());
        return weather;
    }

    public List<WeatherData> queryForecast(String city, int days) {
        // days 是预报结果的一部分，相同地点不同天数不能共用缓存。
        GeoLocation location = openMeteoWeatherClient.geocodeChinaCity(city);
        String cacheKey = FORECAST_CACHE_PREFIX + location.cacheLocationId() + ":" + days;

        List<WeatherData> cached = readForecastCache(cacheKey);
        if (cached != null) {
            return cached;
        }

        List<WeatherData> forecast = openMeteoWeatherClient.queryForecast(location, days);
        writeCache(cacheKey, forecast, properties.getForecastCacheMinutes());
        return forecast;
    }

    private WeatherData readCurrentCache(String cacheKey) {
        try {
            String cacheValue = stringRedisTemplate.opsForValue().get(cacheKey);
            if (cacheValue == null) {
                return null;
            }
            return objectMapper.readValue(cacheValue, WeatherData.class);
        } catch (DataAccessException | JsonProcessingException e) {
            // 缓存不可用或数据损坏时直接回源，不能让缓存故障阻断天气查询。
            log.warn("读取当前天气缓存失败，cacheKey={}", cacheKey, e);
            deleteQuietly(cacheKey);
            return null;
        }
    }

    private List<WeatherData> readForecastCache(String cacheKey) {
        try {
            String cacheValue = stringRedisTemplate.opsForValue().get(cacheKey);
            if (cacheValue == null) {
                return null;
            }
            return objectMapper.readValue(cacheValue, new TypeReference<>() {
            });
        } catch (DataAccessException | JsonProcessingException e) {
            log.warn("读取天气预报缓存失败，cacheKey={}", cacheKey, e);
            deleteQuietly(cacheKey);
            return null;
        }
    }

    private void writeCache(String cacheKey, Object value, long ttlMinutes) {
        try {
            String cacheValue = objectMapper.writeValueAsString(value);
            stringRedisTemplate.opsForValue().set(cacheKey, cacheValue, ttlMinutes, TimeUnit.MINUTES);
        } catch (DataAccessException | JsonProcessingException e) {
            // 外部天气已经查询成功时，写缓存失败不应影响本次用户请求。
            log.warn("写入天气缓存失败，cacheKey={}", cacheKey, e);
        }
    }

    private void deleteQuietly(String cacheKey) {
        try {
            stringRedisTemplate.delete(cacheKey);
        } catch (DataAccessException e) {
            log.debug("删除损坏天气缓存失败，cacheKey={}", cacheKey, e);
        }
    }
}
