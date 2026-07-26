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

package com.nageoffer.ai.ragent.mcp.weather.infrastructure.redis;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nageoffer.ai.ragent.mcp.weather.application.port.out.WeatherCache;
import com.nageoffer.ai.ragent.mcp.weather.config.WeatherCacheProperties;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.WeatherData;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Redis implementation of the WeatherCache outbound port. */
@Slf4j
@Component
@RequiredArgsConstructor
public class RedisWeatherCache implements WeatherCache {

    private static final String CURRENT_CACHE_PREFIX = "ragent:weather:current:cn:";
    private static final String FORECAST_CACHE_PREFIX = "ragent:weather:forecast:cn:";

    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;
    private final WeatherCacheProperties properties;

    @Override
    public Optional<WeatherData> findCurrent(GeoLocation location) {
        String cacheKey = currentCacheKey(location);
        try {
            String cached = stringRedisTemplate.opsForValue().get(cacheKey);
            return cached == null ? Optional.empty() : Optional.of(objectMapper.readValue(cached, WeatherData.class));
        } catch (DataAccessException | JsonProcessingException e) {
            log.warn("Read current weather cache failed, cacheKey={}", cacheKey, e);
            deleteQuietly(cacheKey);
            return Optional.empty();
        }
    }

    @Override
    public void saveCurrent(GeoLocation location, WeatherData weather) {
        write(currentCacheKey(location), weather, properties.getCurrentTtlMinutes());
    }

    @Override
    public Optional<List<WeatherData>> findForecast(GeoLocation location, int days) {
        String cacheKey = forecastCacheKey(location, days);
        try {
            String cached = stringRedisTemplate.opsForValue().get(cacheKey);
            return cached == null ? Optional.empty()
                    : Optional.of(objectMapper.readValue(cached, new TypeReference<>() { }));
        } catch (DataAccessException | JsonProcessingException e) {
            log.warn("Read forecast weather cache failed, cacheKey={}", cacheKey, e);
            deleteQuietly(cacheKey);
            return Optional.empty();
        }
    }

    @Override
    public void saveForecast(GeoLocation location, int days, List<WeatherData> forecast) {
        write(forecastCacheKey(location, days), forecast, properties.getForecastTtlMinutes());
    }

    private void write(String cacheKey, Object value, long ttlMinutes) {
        try {
            String cached = objectMapper.writeValueAsString(value);
            stringRedisTemplate.opsForValue().set(cacheKey, cached, ttlMinutes, TimeUnit.MINUTES);
        } catch (DataAccessException | JsonProcessingException e) {
            log.warn("Write weather cache failed, cacheKey={}", cacheKey, e);
        }
    }

    private void deleteQuietly(String cacheKey) {
        try {
            stringRedisTemplate.delete(cacheKey);
        } catch (DataAccessException e) {
            log.debug("Delete corrupt weather cache failed, cacheKey={}", cacheKey, e);
        }
    }

    private static String currentCacheKey(GeoLocation location) {
        return CURRENT_CACHE_PREFIX + location.cacheLocationId();
    }

    private static String forecastCacheKey(GeoLocation location, int days) {
        return FORECAST_CACHE_PREFIX + location.cacheLocationId() + ":" + days;
    }
}
