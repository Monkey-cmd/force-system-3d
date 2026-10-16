"""Renderer regression checks. Run with: python -m unittest test_scene -v"""
from pathlib import Path
import math
import tempfile
import tkinter as tk
import unittest
import xml.etree.ElementTree as ET

from mechanics import Force, ZERO, examples, reduce_system
from scene import Scene3D


class SceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"A Tk display is required: {exc}")
        cls.root.geometry("640x540")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.scene = Scene3D(self.root, width=640, height=540)
        self.scene.pack(fill="both", expand=True)
        self.root.update()

    def tearDown(self):
        self.scene.destroy()
        self.root.update()

    def test_small_in_plane_force_keeps_in_plane_arrow(self):
        forces = [Force("large", (1000, 0, 0), ZERO),
                  Force("small", (0, 1, 0), (0, 1, 0))]
        self.scene.mode = "原力系"
        self.scene.set_system(forces, reduce_system(forces))
        self.scene.set_view("XY")
        items = self.scene.find_withtag("force:1")
        symbols = [self.scene.itemcget(item, "text") for item in items
                   if self.scene.type(item) == "text"]
        self.assertNotIn("×", symbols)
        self.assertNotIn("•", symbols)
        arrows = [item for item in items if self.scene.type(item) == "line"
                  and self.scene.itemcget(item, "arrow") == "last"]
        self.assertEqual(len(arrows), 1)
        x1, y1, x2, y2 = self.scene.coords(arrows[0])
        self.assertAlmostEqual(x1, x2)
        self.assertLess(y2, y1)  # +Y points upward in the XY view.

    def test_subnormal_force_and_couple_remain_finite(self):
        forces = [Force("tiny", (1e-320, 0, 0), ZERO)]
        couple = (0, 0, 1e-320)
        self.scene.mode = "原力系"
        self.scene.set_system(forces, reduce_system(forces, free_couple=couple), couple)
        self.assertTrue(math.isfinite(self.scene.radius))
        for primitive in self.scene._primitives:
            for point in primitive[1]:
                self.assertTrue(all(math.isfinite(value) for value in point))
        self.assertGreater(len(self.scene.find_all()), 0)

    def test_default_labels_do_not_overlap(self):
        forces, origin, couple = next(iter(examples().values()))
        self.scene.set_system(forces, reduce_system(forces, origin, couple), couple)
        boxes = [self.scene.bbox(item) for item in self.scene.find_withtag("scene-label")]
        self.assertGreaterEqual(len(boxes), 7)
        for index, first in enumerate(boxes):
            for second in boxes[index+1:]:
                self.assertEqual(self.scene._overlap_area(first, second), 0)

    def test_svg_is_parseable_in_all_named_views(self):
        forces, origin, couple = next(iter(examples().values()))
        self.scene.set_system(forces, reduce_system(forces, origin, couple), couple)
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir, prefix="scene_test_") as directory:
            self.assertEqual(Path(directory).resolve().parent, project_dir)
            for view in ("3D", "XY", "XZ", "YZ"):
                with self.subTest(view=view):
                    self.scene.set_view(view)
                    path = Path(directory) / f"{view}.svg"
                    self.scene.export_svg(path)
                    root = ET.parse(path).getroot()
                    self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
                    self.assertTrue(root.findall("{http://www.w3.org/2000/svg}polyline"))
                    self.assertNotIn("nan", path.read_text(encoding="utf-8").lower())

    def test_svg_preserves_wrapped_and_escaped_labels(self):
        name = "Very long force name & <direction> " * 4
        forces = [Force(name, (10, 0, 0), ZERO)]
        self.scene.set_system(forces, reduce_system(forces))
        project_dir = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=project_dir, prefix="scene_test_") as directory:
            self.assertEqual(Path(directory).resolve().parent, project_dir)
            path = Path(directory) / "wrapped.svg"
            self.scene.export_svg(path)
            root = ET.parse(path).getroot()
            ns = "{http://www.w3.org/2000/svg}"
            labels = root.findall(f"{ns}text")
            wrapped = [item for item in labels if "Very long" in "".join(item.itertext())]
            self.assertEqual(len(wrapped), 1)
            self.assertGreater(len(wrapped[0].findall(f"{ns}tspan")), 1)
            self.assertIn("&", "".join(wrapped[0].itertext()))


if __name__ == "__main__":
    unittest.main()
