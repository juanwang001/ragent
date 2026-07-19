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

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

// Open-Meteo 和天气缓存的可配置参数。
@Data
@ConfigurationProperties(prefix = "weather.open-meteo")
public class WeatherProperties {

    // Open-Meteo 的城市名称转经纬度服务地址。
    private String geocodingBaseUrl;

    // Open-Meteo 的实时天气和预报服务地址。
    private String forecastBaseUrl;

    // 建立 TCP 连接的最长等待时间。
    private int connectTimeoutSeconds = 3;

    // 单次 Open-Meteo 请求的最长等待时间。
    private int requestTimeoutSeconds = 5;

    // 当前天气变化较快，因此只缓存 30 分钟。
    private long currentCacheMinutes = 30;

    // 预报变化相对较慢，缓存 1 小时即可。
    private long forecastCacheMinutes = 60;
}
