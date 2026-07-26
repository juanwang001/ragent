# 中国大陆天气地点数据

`china-mainland-divisions-wgs84.csv` 用于天气模块的本地行政区解析，随
`mcp-server` 构建产物一起发布。运行时不再调用 Open-Meteo 地理编码接口。

- 范围：中国大陆 31 个省级行政区，共 3,214 条省、市、区县记录
- 坐标：WGS84（EPSG:4326）行政区中心点
- 数据版本：`xiangyuecn/AreaCity-JsSpider-StatsGov`
  `2025.251231.260403`
- 原始坐标：GCJ-02；通过标准正向变换的迭代逆运算离线转换为 WGS84
- CSV SHA-256：
  `9a5d8763035458f0d2af3d1730edb0d5eb39df6ef164aa3af04e0c9af1f5a5c7`

完整的生成脚本、源文件锁定信息、第三方数据说明、CSV 校验报告和
Open-Meteo 抽样验证报告位于：

`offline/weather-location-data/`

当前范围不包含台湾、香港和澳门。公开分发或商用数据包之前，应重新核对
上游行政区及地图数据的授权条款。
