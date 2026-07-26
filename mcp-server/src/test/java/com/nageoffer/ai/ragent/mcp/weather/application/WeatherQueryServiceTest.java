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

package com.nageoffer.ai.ragent.mcp.weather.application;

import com.nageoffer.ai.ragent.mcp.weather.application.port.out.WeatherCache;
import com.nageoffer.ai.ragent.mcp.weather.application.port.out.LocationResolver;
import com.nageoffer.ai.ragent.mcp.weather.application.port.out.WeatherProvider;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.AdministrativeLocationQuery;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.WeatherData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class WeatherQueryServiceTest {

    @Mock
    private WeatherProvider weatherProvider;
    @Mock
    private WeatherCache weatherCache;
    @Mock
    private LocationResolver locationResolver;

    private GeoLocation beijing;
    private AdministrativeLocationQuery beijingQuery;

    @BeforeEach
    void setUp() {
        beijing = new GeoLocation("110000", "北京市", "CN", 39.9042, 116.4074);
        beijingQuery = new AdministrativeLocationQuery("北京市", null, null);
    }

    @Test
    void shouldResolveLocationBeforeLookingUpCurrentWeatherCache() {
        WeatherData cached = weather("北京", "2026-07-18T10:00");
        when(locationResolver.resolve(beijingQuery)).thenReturn(beijing);
        when(weatherCache.findCurrent(beijing)).thenReturn(Optional.of(cached));

        WeatherQueryService service = new WeatherQueryService(locationResolver, weatherProvider, weatherCache);

        assertEquals(cached, service.queryCurrent(beijingQuery));
        verify(weatherProvider, never()).queryCurrent(any());
        InOrder order = inOrder(locationResolver, weatherCache);
        order.verify(locationResolver).resolve(beijingQuery);
        order.verify(weatherCache).findCurrent(beijing);
    }

    @Test
    void shouldCacheCurrentWeatherAfterProviderCacheMiss() {
        WeatherData fetched = weather("北京", "2026-07-18T10:00");
        when(locationResolver.resolve(beijingQuery)).thenReturn(beijing);
        when(weatherCache.findCurrent(beijing)).thenReturn(Optional.empty());
        when(weatherProvider.queryCurrent(beijing)).thenReturn(fetched);

        WeatherQueryService service = new WeatherQueryService(locationResolver, weatherProvider, weatherCache);

        assertEquals(fetched, service.queryCurrent(beijingQuery));
        verify(weatherCache).saveCurrent(beijing, fetched);
    }

    private WeatherData weather(String city, String time) {
        return new WeatherData(city, time, 25, 26, 28, 20, 60,
                0, "晴", 10.5, 90, 0);
    }
}
