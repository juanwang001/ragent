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

import java.util.Locale;

// Open-Meteo 地理编码后的规范地点。
public record GeoLocation(String name, String countryCode, double latitude, double longitude) {

    public String cacheLocationId() {
        // 以固定精度的经纬度代表地点，避免“北京/北京市”等别名造成天气缓存重复。
        return String.format(Locale.ROOT, "%.4f:%.4f", latitude, longitude);
    }
}
