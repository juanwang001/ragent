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

package com.nageoffer.ai.ragent.mcp.weather.infrastructure.openmeteo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nageoffer.ai.ragent.mcp.weather.application.port.out.WeatherProvider;
import com.nageoffer.ai.ragent.mcp.weather.config.OpenMeteoProperties;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.GeoLocation;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.WeatherData;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/** Open-Meteo implementation of the WeatherProvider outbound port. */
@Slf4j
@Component
@RequiredArgsConstructor
public class OpenMeteoWeatherProvider implements WeatherProvider {

    private final HttpClient openMeteoHttpClient;
    private final ObjectMapper objectMapper;
    private final OpenMeteoProperties properties;

    @Override
    public WeatherData queryCurrent(GeoLocation location) {
        JsonNode response = queryForecastResponse(location, 1);
        JsonNode current = response.path("current");
        JsonNode daily = response.path("daily");
        if (current.isMissingNode() || daily.isMissingNode()) {
            throw new IllegalStateException("天气服务返回的数据不完整");
        }

        int weatherCode = requiredInt(current, "weather_code");
        return new WeatherData(
                location.name(), current.path("time").asText(),
                requiredInt(current, "temperature_2m"), requiredInt(current, "apparent_temperature"),
                arrayInt(daily, "temperature_2m_max", 0), arrayInt(daily, "temperature_2m_min", 0),
                requiredInt(current, "relative_humidity_2m"), weatherCode, WeatherCodeMapper.toText(weatherCode),
                requiredDouble(current, "wind_speed_10m"), requiredInt(current, "wind_direction_10m"),
                arrayInt(daily, "precipitation_probability_max", 0)
        );
    }

    @Override
    public List<WeatherData> queryForecast(GeoLocation location, int days) {
        JsonNode daily = queryForecastResponse(location, days).path("daily");
        JsonNode dates = daily.path("time");
        if (!dates.isArray() || dates.isEmpty()) {
            throw new IllegalStateException("天气服务未返回预报数据");
        }

        List<WeatherData> forecast = new ArrayList<>(dates.size());
        for (int index = 0; index < dates.size(); index++) {
            int weatherCode = arrayInt(daily, "weather_code", index);
            forecast.add(new WeatherData(
                    location.name(), dates.get(index).asText(), null, null,
                    arrayInt(daily, "temperature_2m_max", index), arrayInt(daily, "temperature_2m_min", index),
                    null, weatherCode, WeatherCodeMapper.toText(weatherCode),
                    arrayDouble(daily, "wind_speed_10m_max", index), null,
                    arrayInt(daily, "precipitation_probability_max", index)
            ));
        }
        return forecast;
    }

    private JsonNode queryForecastResponse(GeoLocation location, int days) {
        String url = properties.getForecastBaseUrl()
                + "/v1/forecast?latitude=" + location.latitude()
                + "&longitude=" + location.longitude()
                + "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m"
                + "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"
                + "&timezone=Asia%2FShanghai&forecast_days=" + days;
        return getJson(url);
    }

    private JsonNode getJson(String url) {
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                    .GET().header("Accept", "application/json")
                    .timeout(Duration.ofSeconds(properties.getRequestTimeoutSeconds())).build();
            HttpResponse<String> response = openMeteoHttpClient.send(
                    request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                log.warn("Open-Meteo request failed, status={}, url={}", response.statusCode(), url);
                throw new IllegalStateException("天气服务暂时不可用");
            }
            return objectMapper.readTree(response.body());
        } catch (IOException e) {
            log.warn("Open-Meteo network request failed, url={}", url, e);
            throw new IllegalStateException("天气服务暂时不可用", e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("天气服务请求被中断", e);
        }
    }

    private static int requiredInt(JsonNode node, String field) {
        if (!node.hasNonNull(field)) {
            throw new IllegalStateException("天气服务缺少字段：" + field);
        }
        return node.path(field).asInt();
    }

    private static double requiredDouble(JsonNode node, String field) {
        return requiredDouble(node, field, null);
    }

    private static double requiredDouble(JsonNode node, String field, String location) {
        if (!node.hasNonNull(field)) {
            String suffix = location == null ? "" : "，地点：" + location;
            throw new IllegalStateException("天气服务缺少字段：" + field + suffix);
        }
        return node.path(field).asDouble();
    }

    private static int arrayInt(JsonNode object, String field, int index) {
        JsonNode value = object.path(field).path(index);
        if (value.isMissingNode() || value.isNull()) {
            throw new IllegalStateException("天气服务缺少数组字段：" + field);
        }
        return value.asInt();
    }

    private static double arrayDouble(JsonNode object, String field, int index) {
        JsonNode value = object.path(field).path(index);
        if (value.isMissingNode() || value.isNull()) {
            throw new IllegalStateException("天气服务缺少数组字段：" + field);
        }
        return value.asDouble();
    }
}
