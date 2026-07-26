# 第三方数据说明

当前离线产物使用
[`xiangyuecn/AreaCity-JsSpider-StatsGov`](https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov)
的 `2025.251231.260403` 发布包。该仓库代码和文档声明为 MIT License。

发布包说明其行政区信息整合自国家地名信息库、高德地图和腾讯地图，
中心点来自高德地图并使用 GCJ-02 坐标系。本目录中的脚本只在本地提取
中心点、折叠人为补齐的选择器节点，并反算为 WGS84。

本说明不把仓库的 MIT License 扩张解释为上游地图数据的再分发授权。
在把生成 CSV 发布到公开制品库、商业数据包或第三方服务之前，应重新
核对国家地名信息库、高德地图和腾讯地图届时适用的条款。当前产物用于
本项目内部的离线地点解析和天气查询适配。

可复现版本、下载地址、文件大小和 SHA-256 见
[`source-lock.json`](source-lock.json)。
