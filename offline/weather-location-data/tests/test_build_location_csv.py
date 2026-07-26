import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_location_csv.py"
)
SPEC = importlib.util.spec_from_file_location("build_location_csv", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
HAS_GEOPANDAS = importlib.util.find_spec("geopandas") is not None


class BuildLocationCsvTest(unittest.TestCase):

    def test_gcj02_to_wgs84_reverses_known_beijing_example(self):
        # Widely used GCJ-02 reference pair:
        # WGS84 (116.404, 39.915) -> GCJ-02
        converted = MODULE.gcj02_to_wgs84(
            MODULE.Coordinate(
                longitude=116.41024449916938,
                latitude=39.91640428150164,
            )
        )

        self.assertAlmostEqual(116.404, converted.longitude, places=6)
        self.assertAlmostEqual(39.915, converted.latitude, places=6)

    def test_load_areacity_mainland_collapses_synthetic_hierarchy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            admin = root / "ok_data_level3.csv"
            geo = root / "ok_geo.csv"
            admin.write_text(
                "id,pid,deep,name,pinyin_prefix,pinyin,ext_id,ext_name\n"
                '11,0,0,"北京",b,"bei jing",110000000000,"北京市"\n'
                '1101,11,1,"北京",b,"bei jing",110100000000,"北京市"\n'
                '110101,1101,2,"东城",d,"dong cheng",110101000000,"东城区"\n'
                '41,0,0,"河南",h,"he nan",410000000000,"河南省"\n'
                '419001,41,1,"济源",j,"ji yuan",419001000000,"济源市"\n'
                '419001000,419001,2,"济源",j,"ji yuan",419001000000,"济源市"\n'
                '44,0,0,"广东",g,"guang dong",440000000000,"广东省"\n'
                '4419,44,1,"东莞",d,"dong guan",441900000000,"东莞市"\n'
                '441900,4419,2,"东莞",d,"dong guan",441900000000,"东莞市"\n'
                '91,0,0,"国外",x,"wai",0,"国外"\n',
                encoding="utf-8",
            )
            geo.write_text(
                "id,pid,deep,name,ext_path,geo,polygon\n"
                '11,0,0,"北京市","北京市","116.407387 39.904179","EMPTY"\n'
                '1101,11,1,"北京市","北京市 北京市","116.407387 39.904179","EMPTY"\n'
                '110101,1101,2,"东城区","北京市 北京市 东城区","116.416334 39.928359","EMPTY"\n'
                '41,0,0,"河南省","河南省","113.665412 34.757975","EMPTY"\n'
                '419001,41,1,"济源市","河南省 济源市","112.602347 35.069057","EMPTY"\n'
                '419001000,419001,2,"济源市","河南省 济源市 济源市","112.602347 35.069057","EMPTY"\n'
                '44,0,0,"广东省","广东省","113.280637 23.125178","EMPTY"\n'
                '4419,44,1,"东莞市","广东省 东莞市","113.751765 23.020536","EMPTY"\n'
                '441900,4419,2,"东莞市","广东省 东莞市 东莞市","113.751765 23.020536","EMPTY"\n',
                encoding="utf-8",
            )

            metadata, coordinates, stats = MODULE.load_areacity_mainland(
                admin,
                geo,
            )

        self.assertEqual(
            {
                "110000",
                "110100",
                "110101",
                "410000",
                "419001",
                "440000",
                "441900",
            },
            set(metadata),
        )
        self.assertEqual("COUNTY", metadata["419001"].level)
        self.assertEqual("410000", metadata["419001"].parent_adcode)
        self.assertEqual("", metadata["419001"].city)
        self.assertEqual("CITY", metadata["441900"].level)
        self.assertEqual("440000", metadata["441900"].parent_adcode)
        self.assertNotEqual(113.751765, coordinates["441900"].longitude)
        self.assertEqual(2, stats.collapsed_synthetic_records)

    def test_normalize_adcode_accepts_spreadsheet_number_format(self):
        self.assertEqual("420111", MODULE.normalize_adcode(" 420111.0 "))

    def test_normalize_adcode_rejects_non_six_digit_value(self):
        with self.assertRaisesRegex(ValueError, "6 位数字"):
            MODULE.normalize_adcode("42011")

    def test_load_admin_metadata_rejects_duplicate_adcode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "admin.csv"
            source.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,湖北省武汉市洪山区\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,湖北省武汉市洪山区\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "重复"):
                MODULE.load_admin_metadata(source)

    def test_load_admin_metadata_rejects_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "admin.csv"
            source.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,湖北省武汉市洪山区\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "父级"):
                MODULE.load_admin_metadata(source)

    def test_write_location_csv_orders_by_adcode_and_writes_wgs84(self):
        metadata = {
            "420111": MODULE.AdminDivision(
                adcode="420111",
                parent_adcode="420100",
                level="COUNTY",
                province="湖北省",
                city="武汉市",
                district="洪山区",
                full_name="湖北省武汉市洪山区",
            ),
            "110108": MODULE.AdminDivision(
                adcode="110108",
                parent_adcode="110100",
                level="COUNTY",
                province="北京市",
                city="北京市",
                district="海淀区",
                full_name="北京市海淀区",
            ),
        }
        coordinates = {
            "420111": MODULE.Coordinate(longitude=114.34, latitude=30.50),
            "110108": MODULE.Coordinate(longitude=116.30, latitude=39.96),
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "china-divisions.csv"
            MODULE.write_location_csv(
                output=output,
                metadata=metadata,
                coordinates=coordinates,
                minimum_records=2,
                maximum_records=2,
            )

            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(["110108", "420111"], [row["adcode"] for row in rows])
        self.assertEqual("WGS84", rows[0]["coordinate_system"])
        self.assertEqual("116.300000", rows[0]["longitude"])
        self.assertEqual("39.960000", rows[0]["latitude"])

    def test_write_location_csv_rejects_missing_geometry(self):
        metadata = {
            "420111": MODULE.AdminDivision(
                adcode="420111",
                parent_adcode="420100",
                level="COUNTY",
                province="湖北省",
                city="武汉市",
                district="洪山区",
                full_name="湖北省武汉市洪山区",
            )
        }

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "china-divisions.csv"
            with self.assertRaisesRegex(ValueError, "缺少坐标"):
                MODULE.write_location_csv(
                    output=output,
                    metadata=metadata,
                    coordinates={},
                    minimum_records=1,
                    maximum_records=1,
                )

    def test_validate_location_csv_checks_hierarchy_and_level_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "locations.csv"
            source.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name,"
                "longitude,latitude,coordinate_system\n"
                "420000,,PROVINCE,湖北省,,,湖北省,112.1,30.9,WGS84\n"
                "420100,420000,CITY,湖北省,武汉市,,湖北省武汉市,"
                "114.3,30.6,WGS84\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,"
                "湖北省武汉市洪山区,114.3,30.5,WGS84\n",
                encoding="utf-8",
            )

            report = MODULE.validate_location_csv_file(
                source,
                expected_province_count=1,
                required_adcodes={"420111": "洪山区"},
            )

        self.assertEqual(3, report["recordCount"])
        self.assertEqual(
            {"PROVINCE": 1, "CITY": 1, "COUNTY": 1},
            report["levelCounts"],
        )
        self.assertEqual("洪山区", report["requiredLocations"]["420111"]["district"])

    def test_validate_location_csv_rejects_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "locations.csv"
            source.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name,"
                "longitude,latitude,coordinate_system\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,"
                "湖北省武汉市洪山区,114.3,30.5,WGS84\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "父级"):
                MODULE.validate_location_csv_file(
                    source,
                    expected_province_count=0,
                )

    @unittest.skipUnless(HAS_GEOPANDAS, "需要安装离线地理处理依赖")
    def test_build_command_converts_vector_layer_to_csv_and_manifest(self):
        import geopandas
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vector = root / "admin.gpkg"
            metadata = root / "admin.csv"
            output = root / "china-divisions.csv"

            frame = geopandas.GeoDataFrame(
                {
                    "ADCODE": [
                        "110000",
                        "110100",
                        "110108",
                        "420000",
                        "420100",
                        "420111",
                    ],
                    "geometry": [
                        box(115.70, 39.40, 117.40, 41.10),
                        box(115.80, 39.50, 117.30, 41.00),
                        box(116.20, 39.80, 116.40, 40.00),
                        box(108.30, 29.00, 116.20, 33.30),
                        box(113.60, 29.90, 115.10, 31.40),
                        box(114.20, 30.40, 114.50, 30.70),
                    ],
                },
                crs="EPSG:4490",
            )
            frame.to_file(vector, layer="BOUA", driver="GPKG")
            metadata.write_text(
                "adcode,parent_adcode,level,province,city,district,full_name\n"
                "110000,,PROVINCE,北京市,,,北京市\n"
                "110100,110000,CITY,北京市,北京市,,北京市\n"
                "110108,110100,COUNTY,北京市,北京市,海淀区,北京市海淀区\n"
                "420000,,PROVINCE,湖北省,,,湖北省\n"
                "420100,420000,CITY,湖北省,武汉市,,湖北省武汉市\n"
                "420111,420100,COUNTY,湖北省,武汉市,洪山区,湖北省武汉市洪山区\n",
                encoding="utf-8",
            )

            exit_code = MODULE.main(
                [
                    "build",
                    "--input",
                    str(vector),
                    "--layer",
                    "BOUA",
                    "--geometry-code-field",
                    "ADCODE",
                    "--source-crs",
                    "EPSG:4490",
                    "--admin-metadata",
                    str(metadata),
                    "--source-name",
                    "synthetic-test",
                    "--source-version",
                    "1",
                    "--minimum-records",
                    "6",
                    "--maximum-records",
                    "6",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue(output.exists())
            self.assertTrue(
                output.with_suffix(".csv.metadata.json").exists()
            )

            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(6, len(rows))
            self.assertEqual("WGS84", rows[0]["coordinate_system"])


if __name__ == "__main__":
    unittest.main()
