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

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nageoffer.ai.ragent.mcp.weather.config.WeatherCacheProperties;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.WeatherData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.util.concurrent.TimeUnit;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RedisWeatherCacheTest {

    @Mock
    private StringRedisTemplate stringRedisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;

    private RedisWeatherCache weatherCache;
    private GeoLocation beijing;

    @BeforeEach
    void setUp() {
        WeatherCacheProperties properties = new WeatherCacheProperties();
        properties.setCurrentTtlMinutes(30);
        properties.setForecastTtlMinutes(60);
        when(stringRedisTemplate.opsForValue()).thenReturn(valueOperations);
        weatherCache = new RedisWeatherCache(stringRedisTemplate, new ObjectMapper(), properties);
        beijing = new GeoLocation("110000", "北京市", "CN", 39.9042, 116.4074);
    }

    @Test
    void shouldCacheCurrentWeatherByResolvedAdcodeForThirtyMinutes() {
        WeatherData weather = new WeatherData("北京", "2026-07-18T10:00", 25, 26, 28, 20,
                60, 0, "晴", 10.5, 90, 0);

        weatherCache.saveCurrent(beijing, weather);

        verify(valueOperations).set(
                eq("ragent:weather:current:cn:110000"),
                any(String.class), eq(30L), eq(TimeUnit.MINUTES));
    }
}
