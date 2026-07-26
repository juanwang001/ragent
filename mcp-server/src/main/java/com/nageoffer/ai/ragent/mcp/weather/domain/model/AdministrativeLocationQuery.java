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

package com.nageoffer.ai.ragent.mcp.weather.domain.model;

/**
 * Structured Chinese administrative location extracted by the Bootstrap LLM.
 *
 * <p>The MCP server still resolves and validates every field against its local
 * administrative-division index. Empty city values are valid for
 * province-administered counties.
 */
public record AdministrativeLocationQuery(String province, String city, String district) {

    public AdministrativeLocationQuery {
        province = trimToNull(province);
        city = trimToNull(city);
        district = trimToNull(district);
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
