# 天气地点离线数据构建工具

该目录负责把可审计的行政区数据离线处理成天气模块可以直接加载的
WGS84 地点 CSV。当前已完成的构建从 AreaCity 同版本行政区表和中心点表
生成中国大陆 31 个省级行政区的省、市、区县索引；同时保留了以后换成
国家基础地理信息中心公众版矢量的通用构建入口。

下载和解压是一次性准备动作。构建脚本本身不访问网络，也不按名称模糊
匹配行政区。原始压缩包和 167 MB 边界表只保存在本地，运行时产物不包含
边界，只保留六位行政代码、层级、完整名称和 WGS84 中心点。

目录约定：

```text
offline/weather-location-data/
├─ scripts/       离线构建程序
├─ tests/         单元与矢量集成测试
├─ source/        原始下载文件，不提交 Git
├─ metadata/      行政区代码和层级元数据
├─ work/          解压、转换和临时文件，不提交 Git
└─ output/        离线构建产物和验证报告
```

## 当前成品

```text
output/china-mainland-divisions-wgs84.csv
output/china-mainland-divisions-wgs84.csv.metadata.json
output/china-mainland-divisions-wgs84.csv.validation.json
output/open-meteo-sample-validation.json
```

本次结果：

- 3,214 条、363,231 字节；
- 省级 31 条、市级 338 条、区县级 2,845 条；
- 32 个省直辖县级节点直接挂在省级节点下；
- CSV SHA-256：
  `9a5d8763035458f0d2af3d1730edb0d5eb39df6ef164aa3af04e0c9af1f5a5c7`。

范围明确为中国大陆。源发布包中台湾省下级 378 条记录没有中心点，脚本
没有拿台湾省中心点冒充各市区县；香港、澳门和“国外”辅助节点也没有混入
本次大陆索引。若下一阶段要求港澳台完整覆盖，应分别接入当地公开界线数据。
另外，上游发布说明明确指出尚未包含新疆新设的和康县、和安县，因为发布时
高德地图还没有对应数据；本产物保留该事实，不伪造两县中心点。

## 当前输入

数据版本为 `2025.251231.260403`，下载地址、大小和哈希全部锁定在
[`metadata/source-lock.json`](metadata/source-lock.json)。行政区表整合
国家地名信息库、高德地图和腾讯地图；坐标表原始坐标为 GCJ-02。

脚本按真实六位行政代码关联两张表，并执行以下处理：

1. 排除不在本次大陆口径内的记录；
2. 折叠 AreaCity 为固定三级选择器人为补齐的重复市/区节点；
3. 保留省直辖县级行政区并直接挂在省级节点下；
4. 用标准 GCJ-02 正向变换的迭代逆解反算 WGS84；
5. 生成 CSV、来源清单和独立验收报告。

第三方数据和再分发边界见
[`metadata/THIRD_PARTY_NOTICES.md`](metadata/THIRD_PARTY_NOTICES.md)。

## 可选输入：官方行政区矢量

### 行政区矢量

支持 GeoJSON、Shapefile、GeoPackage 和 FileGDB 等 GeoPandas /
Pyogrio 可读取格式。国家基础地理信息中心 1:100 万公众版数据中，
“行政境界（面）”的标准图层缩写是 `BOUA`；实际下载包的文件布局、
图层名和行政区代码字段必须先检查，不能直接猜测。

官方 CGCS2000 经纬度数据应声明为 `EPSG:4490`。工具会将其转换为
`EPSG:4326`，再为每个行政区生成保证位于其几何内部的代表点。

### 行政区元数据 CSV

元数据负责提供稳定的层级和行政区划代码，表头固定为：

```csv
adcode,parent_adcode,level,province,city,district,full_name
420000,,PROVINCE,湖北省,,,湖北省
420100,420000,CITY,湖北省,武汉市,,湖北省武汉市
420111,420100,COUNTY,湖北省,武汉市,洪山区,湖北省武汉市洪山区
```

`level` 只允许：

- `PROVINCE`
- `CITY`
- `COUNTY`

元数据应覆盖最终需要输出的全部省、市、区县记录。不要在这里填写
未经核验的经纬度，坐标统一从矢量数据生成。

## 环境准备

在 PowerShell 7 中执行：

```powershell
python -m venv .venv-weather-data
.\.venv-weather-data\Scripts\python.exe -m pip install `
  -r .\offline\weather-location-data\requirements.txt
```

## 复现当前成品

先用一键脚本按 `source-lock.json` 下载、校验并只解压需要的两个 CSV：

```powershell
.\offline\weather-location-data\scripts\prepare_areacity_source.ps1
```

脚本会复用哈希正确的已有文件，下载中断不会覆盖正式压缩包。准备完成后执行：

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\build_location_csv.py `
  build-areacity `
  --admin-source `
    .\offline\weather-location-data\work\raw\ok_data_level3.csv `
  --geo-source .\offline\weather-location-data\work\raw\ok_geo.csv `
  --source-version 2025.251231.260403 `
  --output `
    .\offline\weather-location-data\output\china-mainland-divisions-wgs84.csv
```

独立重跑验收：

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\build_location_csv.py validate `
  --input `
    .\offline\weather-location-data\output\china-mainland-divisions-wgs84.csv
```

## Open-Meteo 在线抽样验收

在线验收使用和 `mcp-server` 中 `OpenMeteoWeatherProvider` 完全相同的
current、daily、时区和预报天数参数：

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\validate_open_meteo_samples.py `
  --csv `
    .\offline\weather-location-data\output\china-mainland-divisions-wgs84.csv `
  --output `
    .\offline\weather-location-data\output\open-meteo-sample-validation.json
```

默认抽取 12 个跨地域样本，包含北京海淀、哈尔滨南岗、上海浦东、杭州
西湖、武汉洪山、深圳南山、三亚吉阳、成都武侯、拉萨城关、乌鲁木齐
天山、河南济源和甘肃嘉峪关。判定标准包括：

- Open-Meteo 返回 HTTP 2xx；
- 项目适配器读取的 current 和 daily 字段完整；
- 时区为 `Asia/Shanghai`，UTC 偏移为 28,800 秒；
- Open-Meteo 实际采用的模型网格中心距 CSV 请求坐标不超过 15 km。

2026-07-25 的实际验收为 12/12 通过，平均网格距离 3.830 km，最大
6.196 km。Open-Meteo 官方说明返回坐标是实际采用的天气模型网格中心，
本来就可能和请求坐标相差数公里。该验收证明 CSV 坐标能够正确驱动
Open-Meteo 并返回项目需要的完整数据结构；一次在线抽样不能代替气象站
观测对预报准确率的长期评估。

## 检查官方矢量输入

下载官方文件后，先检查图层、坐标系和字段：

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\build_location_csv.py inspect `
  --input .\offline\weather-location-data\source\ngcc-1m-2021\示例文件.gpkg
```

如果一个文件包含多个图层：

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\build_location_csv.py inspect `
  --input .\offline\weather-location-data\source\ngcc-1m-2021\示例文件.gpkg `
  --layer BOUA
```

确认实际行政区代码字段后再执行构建。下例中的 `ADCODE` 只是参数示例，
必须替换为原始数据中的真实字段名。

## 使用官方矢量构建

```powershell
.\.venv-weather-data\Scripts\python.exe `
  .\offline\weather-location-data\scripts\build_location_csv.py build `
  --input '.\offline\weather-location-data\source\ngcc-1m-2021\**\BOUA.shp' `
  --geometry-code-field ADCODE `
  --source-crs EPSG:4490 `
  --admin-metadata .\offline\weather-location-data\metadata\admin-divisions-2026.csv `
  --source-name NGCC-1M-Public-2021 `
  --source-version 2021-currentness-2019 `
  --output `
    .\offline\weather-location-data\output\china-mainland-divisions-wgs84.csv
```

如果输入是带图层的 GeoPackage 或 FileGDB，再增加：

```text
--layer BOUA
```

成功后生成：

```text
offline/weather-location-data/output/china-mainland-divisions-wgs84.csv
offline/weather-location-data/output/china-mainland-divisions-wgs84.csv.metadata.json
```

元数据清单记录输入文件哈希、行政区元数据哈希、数据源版本、输出哈希
和记录数量，用于后续复现与审计。

## 构建时校验

脚本默认执行以下检查：

- `adcode` 必须是六位数字且不能重复；
- 非省级记录的父级 `adcode` 必须存在且层级关系有效；
- 元数据必须包含固定字段；
- 输入必须显式声明 CRS，或通过 `--source-crs` 指定；
- 已声明 CRS 与 `--source-crs` 不一致时终止；
- 每个元数据行政区都必须存在矢量几何；
- 经纬度必须落在中国宽松边界内；
- 最终记录数必须在 2,500～4,000 之间；
- CSV 使用临时文件生成，完成校验后再原子替换正式文件。
- 当前大陆成品必须包含 31 个省级节点；
- 海淀区、西湖区、洪山区、南山区、济源市和嘉峪关市等关键节点必须存在；
- 输出坐标系必须逐行标记为 `WGS84`。

小范围调试时可通过 `--minimum-records` 和 `--maximum-records`
调整记录数范围，正式全国构建不建议降低默认下限。

## 测试

```powershell
.\.venv-weather-data\Scripts\python.exe -m unittest `
  .\offline\weather-location-data\tests\test_build_location_csv.py
```
