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
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Application service that coordinates location resolution, cache lookup, and
 * weather-provider access. It has no knowledge of MCP, Redis, HTTP, or JSON.
 */
@Service
@RequiredArgsConstructor
public class WeatherQueryService {

    private final LocationResolver locationResolver;
    private final WeatherProvider weatherProvider;
    private final WeatherCache weatherCache;

    public WeatherData queryCurrent(AdministrativeLocationQuery query) {
        GeoLocation location = locationResolver.resolve(query);
        return weatherCache.findCurrent(location)
                .orElseGet(() -> queryAndCacheCurrent(location));
    }

    public List<WeatherData> queryForecast(AdministrativeLocationQuery query, int days) {
        GeoLocation location = locationResolver.resolve(query);
        return weatherCache.findForecast(location, days)
                .orElseGet(() -> queryAndCacheForecast(location, days));
    }

    private WeatherData queryAndCacheCurrent(GeoLocation location) {
        WeatherData weather = weatherProvider.queryCurrent(location);
        weatherCache.saveCurrent(location, weather);
        return weather;
    }

    private List<WeatherData> queryAndCacheForecast(GeoLocation location, int days) {
        List<WeatherData> forecast = weatherProvider.queryForecast(location, days);
        weatherCache.saveForecast(location, days, forecast);
        return forecast;
    }
}
