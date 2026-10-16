"""项目文件与命令行批处理测试；不会创建图形窗口。"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import app
from mechanics import Force, ZERO, examples, reduce_system


HERE = Path(__file__).resolve().parent


class ProjectAndCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".test-project-", dir=HERE)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        forces, origin, couple = examples()["空间力系 · 力螺旋"]
        self.valid = app.project_data(forces, origin, couple)

    def write_project(self, data, name="project.json", *, encoding="utf-8"):
        path = self.path / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding=encoding)
        return path

    def run_main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with patch("app.tk.Tk", side_effect=AssertionError("批处理不应创建 GUI")), \
                redirect_stdout(out), redirect_stderr(err):
            code = app.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_all_sample_projects_load_with_expected_results(self):
        expected = {"01_wrench.json": "wrench", "02_parallel_resultant.json": "single",
                    "03_couple.json": "couple", "04_concurrent.json": "single",
                    "05_equilibrium.json": "equilibrium", "06_negative_pitch.json": "wrench"}
        for filename, kind in expected.items():
            with self.subTest(filename=filename):
                forces, origin, couple = app.read_project(HERE / "examples" / filename)
                self.assertEqual(reduce_system(forces, origin, couple).kind, kind)

    def test_project_data_round_trip_preserves_inputs(self):
        forces = [Force("中文名称", (12.3, -45.6, 78.9), (1.2, 3.4, -5.6))]
        origin, couple = (5, 6, 7), (-8, -9, 10)
        data = app.project_data(forces, origin, couple)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["units"], {"force": "N", "length": "m"})
        loaded_forces, loaded_origin, loaded_couple = app.read_project(self.write_project(data))
        self.assertEqual(loaded_forces, forces)
        self.assertEqual(loaded_origin, origin)
        self.assertEqual(loaded_couple, couple)
        self.assertEqual(app.project_data(loaded_forces, loaded_origin, loaded_couple), data)

    def test_utf8_bom_is_accepted(self):
        path = self.write_project(self.valid, encoding="utf-8-sig")
        self.assertEqual(len(app.read_project(path)[0]), 3)

    def test_optional_free_couple_defaults_to_zero(self):
        self.valid.pop("free_couple")
        self.assertEqual(app.read_project(self.write_project(self.valid))[2], ZERO)

    def test_empty_force_list_is_accepted(self):
        self.valid["forces"] = []
        forces, origin, couple = app.read_project(self.write_project(self.valid))
        self.assertEqual(reduce_system(forces, origin, couple).kind, "equilibrium")

    def test_missing_required_fields_are_rejected(self):
        for key in ["schema_version", "units", "origin", "forces"]:
            data = deepcopy(self.valid)
            del data[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                app.read_project(self.write_project(data))
        for key in ["components", "point"]:
            data = deepcopy(self.valid)
            del data["forces"][0][key]
            with self.subTest(force_key=key), self.assertRaises(ValueError):
                app.read_project(self.write_project(data))

    def test_wrong_units_are_rejected(self):
        for units in [{"force": "kN", "length": "m"}, {"force": "N", "length": "mm"},
                      {}, None, "N/m"]:
            self.valid["units"] = units
            with self.subTest(units=units), self.assertRaisesRegex(ValueError, "单位|N 和 m"):
                app.read_project(self.write_project(self.valid))

    def test_invalid_schema_and_root_are_rejected(self):
        for data in [[], None, "project", 42]:
            with self.subTest(root=data), self.assertRaises(ValueError):
                app.read_project(self.write_project(data))
        for version in [None, 2, "1", True]:
            self.valid["schema_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                app.read_project(self.write_project(self.valid))

    def test_invalid_force_list_is_rejected(self):
        for forces in [None, {}, "forces", ["bad"], [None], [1]]:
            self.valid["forces"] = forces
            with self.subTest(forces=forces), self.assertRaises(ValueError):
                app.read_project(self.write_project(self.valid))

    def test_invalid_components_and_points_are_rejected(self):
        for field in ["components", "point"]:
            for value in [None, "123", [], [1, 2], [1, 2, 3, 4], ["bad", 0, 0],
                          [float("nan"), 0, 0], [0, float("inf"), 0],
                          [True, 0, 0], ["1", 0, 0]]:
                data = deepcopy(self.valid)
                data["forces"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    app.read_project(self.write_project(data))

    def test_invalid_origin_and_free_couple_are_rejected(self):
        for field in ["origin", "free_couple"]:
            for value in [None, "123", [], [1, 2], [float("nan"), 0, 0], [True, 0, 0]]:
                data = deepcopy(self.valid)
                data[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    app.read_project(self.write_project(data))

    def test_malformed_json_is_rejected(self):
        path = self.path / "broken.json"
        path.write_text('{"schema_version": 1,', encoding="utf-8")
        with self.assertRaises(ValueError):
            app.read_project(path)

    def test_batch_report_has_values_and_action_line(self):
        project = self.write_project(app.project_data(*examples()["平行力系 · 单一合力"]))
        report = self.path / "结果报告.txt"
        code, out, err = self.run_main(["--input", str(project), "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("报告已保存", out)
        text = report.read_text(encoding="utf-8-sig")
        self.assertIn("主矢 R = (0, 0, -300) N", text)
        self.assertIn("主矩 M_O = (0, 600, 0) N·m", text)
        self.assertIn("最简结果：单一合力", text)
        self.assertIn("A = (2, 0, 0) m", text)
        self.assertIn("方向角", text)
        self.assertIn("矩残差 = 0 N·m", text)

    def test_batch_report_requires_input(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            app.main(["--report", str(self.path / "report.txt")])
        self.assertEqual(exc.exception.code, 2)

    def test_batch_invalid_project_returns_error_without_report(self):
        self.valid["forces"][0]["components"] = [1, 2]
        source, report = self.write_project(self.valid), self.path / "report.txt"
        code, out, err = self.run_main(["--input", str(source), "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("无法运行", err)
        self.assertFalse(report.exists())

    def test_batch_missing_input_and_unwritable_output_are_handled(self):
        report = self.path / "report.txt"
        code, _, err = self.run_main(["--input", str(self.path / "missing.json"), "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("无法运行", err)
        source = self.write_project(self.valid)
        code, _, err = self.run_main(["--input", str(source), "--report", str(self.path / "missing" / "report.txt")])
        self.assertEqual(code, 1)
        self.assertIn("无法运行", err)

    def test_cli_process_success(self):
        source, report = self.write_project(self.valid), self.path / "report.txt"
        result = subprocess.run([sys.executable, str(HERE / "app.py"), "--input", str(source),
                                 "--report", str(report)], cwd=self.path,
                                env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("报告已保存", result.stdout)
        self.assertIn("最简结果：力螺旋", report.read_text(encoding="utf-8-sig"))

    def test_cli_process_invalid_input_exit_status(self):
        self.valid["units"]["length"] = "cm"
        source, report = self.write_project(self.valid), self.path / "report.txt"
        result = subprocess.run([sys.executable, str(HERE / "app.py"), "--input", str(source),
                                 "--report", str(report)], cwd=self.path,
                                env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIn("无法运行", result.stderr)
        self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
