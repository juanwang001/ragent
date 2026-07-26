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

package com.nageoffer.ai.ragent.mcp.weather.adapter.inbound.mcp;

import com.nageoffer.ai.ragent.mcp.weather.application.WeatherQueryService;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.AdministrativeLocationQuery;
import com.nageoffer.ai.ragent.mcp.weather.domain.model.WeatherData;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.JsonSchema;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

// 将真实天气查询能力以 MCP Tool 的形式暴露给 Ragent 主应用。
@Slf4j
@Component
@RequiredArgsConstructor
public class WeatherMcpExecutor {

    private static final String TOOL_ID = "weather_query";
    private static final int DEFAULT_FORECAST_DAYS = 3;
    private static final int MAX_FORECAST_DAYS = 7;

    private final WeatherQueryService weatherQueryService;

    @Bean
    public McpServerFeatures.SyncToolSpecification weatherToolSpecification() {
        // 第一个参数声明工具 Schema，第二个参数提供真实调用时的处理函数。
        return new McpServerFeatures.SyncToolSpecification(buildTool(),
                (exchange, request) -> handleCall(request));
    }

    Tool buildTool() {
        Map<String, Object> properties = new LinkedHashMap<>();

        properties.put("province", Map.of(
                "type", "string",
                "description", "省级行政区完整名称。必须根据用户提到的地点补全，"
                        + "例如湖北省、北京市、新疆维吾尔自治区",
                "minLength", 1
        ));

        properties.put("city", Map.of(
                "type", "string",
                "description", "地级市完整名称。普通区县必须补全所属城市；"
                        + "直辖市重复填写省级名称，例如北京市；"
                        + "省直辖县级行政区（如济源市）不填写此参数",
                "minLength", 1
        ));

        properties.put("district", Map.of(
                "type", "string",
                "description", "区、县、县级市完整名称，例如洪山区、海淀区、济源市。"
                        + "查询省级或地级市天气时可以省略",
                "minLength", 1
        ));

        properties.put("queryType", Map.of(
                "type", "string",
                "description", "查询类型：current（当前天气）或 forecast（未来天气预报）",
                "enum", List.of("current", "forecast"),
                "default", "current"
        ));

        properties.put("days", Map.of(
                "type", "integer",
                "description", "预报天数，仅 forecast 模式有效，默认 3 天，最大 7 天",
                "default", DEFAULT_FORECAST_DAYS,
                "minimum", 1,
                "maximum", MAX_FORECAST_DAYS
        ));

        JsonSchema inputSchema = new JsonSchema(
                "object", properties, List.of("province"), null, null, null
        );

        return Tool.builder()
                .name(TOOL_ID)
                .description("按规范的省、市、区县行政层级查询中国大陆真实天气。"
                        + "支持直辖市、省直辖县级行政区、当前天气和最多未来 7 天预报，"
                        + "地点由本地行政区数据解析，天气由 Open-Meteo 提供。")
                .inputSchema(inputSchema)
                .build();
    }

    private CallToolResult handleCall(CallToolRequest request) {
        long startMs = System.currentTimeMillis();
        try {
            Map<String, Object> args = request.arguments() == null ? Map.of() : request.arguments();
            String province = stringArg(args, "province");
            String city = stringArg(args, "city");
            String district = stringArg(args, "district");
            String queryType = stringArg(args, "queryType");
            Integer days = intArg(args, "days");

            if (province == null || province.isBlank()) {
                return errorResult("请提供省级行政区名称");
            }
            if (queryType == null || queryType.isBlank()) {
                queryType = "current";
            }
            if (!"current".equals(queryType) && !"forecast".equals(queryType)) {
                return errorResult("queryType 仅支持 current 或 forecast");
            }
            if (days == null || days <= 0) {
                days = DEFAULT_FORECAST_DAYS;
            }
            if (days > MAX_FORECAST_DAYS) {
                days = MAX_FORECAST_DAYS;
            }

            AdministrativeLocationQuery locationQuery = new AdministrativeLocationQuery(
                    province,
                    city,
                    district
            );
            String result = "forecast".equals(queryType)
                    ? buildForecastResult(locationQuery, days)
                    : buildCurrentResult(locationQuery);

            log.info(
                    "MCP 天气工具调用完成，toolId={}, province={}, city={}, district={}, "
                            + "queryType={}, elapsed={}ms",
                    TOOL_ID,
                    province,
                    city,
                    district,
                    queryType,
                    System.currentTimeMillis() - startMs
            );
            return successResult(result);
        } catch (IllegalArgumentException e) {
            // 参数或地点校验失败属于用户可理解的业务错误，无需暴露堆栈。
            log.info("MCP 天气工具参数校验失败，reason={}", e.getMessage());
            return errorResult(e.getMessage());
        } catch (Exception e) {
            log.error("MCP 天气工具调用失败，toolId={}, elapsed={}ms",
                    TOOL_ID, System.currentTimeMillis() - startMs, e);
            return errorResult("天气查询暂时不可用，请稍后重试");
        }
    }

    private String buildCurrentResult(AdministrativeLocationQuery locationQuery) {
        WeatherData weather = weatherQueryService.queryCurrent(locationQuery);

        return String.format("""
                【%s 当前天气】
                观测时间：%s
                天气：%s
                当前温度：%d℃
                体感温度：%d℃
                最高/最低温：%d℃ / %d℃
                相对湿度：%d%%
                风向风速：%s，%.1f km/h
                降水概率：%d%%
                """,
                weather.city(),
                weather.time(),
                weather.weatherText(),
                weather.currentTemp(),
                weather.apparentTemp(),
                weather.highTemp(),
                weather.lowTemp(),
                weather.humidity(),
                formatWindDirection(weather.windDirection()),
                weather.windSpeed(),
                weather.precipitationProbability()
        ).trim();
    }

    private String buildForecastResult(AdministrativeLocationQuery locationQuery, int days) {
        List<WeatherData> forecast = weatherQueryService.queryForecast(locationQuery, days);
        String displayCity = forecast.get(0).city();
        StringBuilder result = new StringBuilder("【" + displayCity + "未来" + days + "天天气预报】\n");

        for (WeatherData dailyWeather : forecast) {
            result.append(dailyWeather.time())
                    .append("：")
                    .append(dailyWeather.weatherText())
                    .append("，")
                    .append(dailyWeather.lowTemp())
                    .append("~")
                    .append(dailyWeather.highTemp())
                    .append("℃，降水概率 ")
                    .append(dailyWeather.precipitationProbability())
                    .append("%，最大风速 ")
                    .append(String.format("%.1f", dailyWeather.windSpeed()))
                    .append(" km/h\n");
        }
        return result.toString().trim();
    }

    private static String formatWindDirection(int degrees) {
        String[] directions = {"北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"};
        // 以 45 度为一个方位，并在边界处四舍五入到最近方位。
        int index = (int) Math.round((degrees % 360) / 45.0D) % directions.length;
        return directions[index];
    }

    private static String stringArg(Map<String, Object> args, String key) {
        Object value = args.get(key);
        return value == null ? null : value.toString();
    }

    private static Integer intArg(Map<String, Object> args, String key) {
        Object value = args.get(key);
        return value instanceof Number number ? number.intValue() : null;
    }

    private static CallToolResult successResult(String text) {
        return CallToolResult.builder()
                .content(List.of(new TextContent(text)))
                .isError(false)
                .build();
    }

    private static CallToolResult errorResult(String message) {
        return CallToolResult.builder()
                .content(List.of(new TextContent(message)))
                .isError(true)
                .build();
    }
}
