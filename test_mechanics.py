"""标准库测试：运行 python -m unittest -v test_mechanics.py。"""
import math
import random
import unittest

from mechanics import (
    Force, ZERO, add, cross, direction_info, dot, examples, make_report,
    mul, norm, reduce_system, sub, unit, vector,
)


class MechanicsTests(unittest.TestCase):
    def assertVectorClose(self, actual, expected, *, rel=1e-11, absolute=1e-10):
        self.assertIsNotNone(actual)
        for a, e in zip(actual, expected):
            self.assertTrue(math.isclose(a, e, rel_tol=rel, abs_tol=absolute),
                            f"{actual!r} != {expected!r}")

    def assertReconstruction(self, result, *, absolute=1e-9):
        if result.kind == "equilibrium":
            self.assertLessEqual(result.force_norm, result.force_tolerance)
            self.assertLessEqual(result.moment_norm, result.moment_tolerance)
        elif result.kind == "couple":
            self.assertLessEqual(result.force_norm, result.force_tolerance)
        else:
            self.assertAlmostEqual(norm(result.axis_direction), 1.0, places=12)
            self.assertAlmostEqual(dot(sub(result.axis_point, result.origin),
                                       result.axis_direction), 0.0, delta=absolute)
            reconstructed = cross(sub(result.axis_point, result.origin), result.resultant)
            if result.kind == "wrench":
                reconstructed = add(reconstructed, result.parallel_moment)
            self.assertVectorClose(reconstructed, result.moment, absolute=absolute)

    def test_empty_system_is_equilibrium(self):
        r = reduce_system([])
        self.assertEqual(r.kind, "equilibrium")
        self.assertEqual(r.resultant, ZERO)
        self.assertEqual(r.moment, ZERO)
        self.assertIsNone(r.axis_point)
        self.assertIsNone(r.axis_direction)
        self.assertIsNone(r.pitch)

    def test_collinear_opposite_forces_are_equilibrium(self):
        r = reduce_system([Force("A", (8, 0, 0), (3, 0, 0)),
                           Force("B", (-8, 0, 0), (-6, 0, 0))], (4, 2, 1))
        self.assertEqual(r.kind, "equilibrium")
        self.assertVectorClose(r.moment, ZERO)
        self.assertReconstruction(r)

    def test_couple_is_free_vector(self):
        forces = [Force("A", (100, 0, 0), (0, 1, 0)),
                  Force("B", (-100, 0, 0), (0, -1, 0))]
        for origin in [ZERO, (10, -20, 30)]:
            r = reduce_system(forces, origin)
            self.assertEqual(r.kind, "couple")
            self.assertVectorClose(r.resultant, ZERO)
            self.assertVectorClose(r.moment, (0, 0, -200))
            self.assertIsNone(r.axis_point)
            self.assertReconstruction(r)

    def test_free_couple_without_forces(self):
        r = reduce_system([], (100, 20, -5), (1, 2, 3))
        self.assertEqual(r.kind, "couple")
        self.assertVectorClose(r.moment, (1, 2, 3))

    def test_parallel_forces_have_weighted_action_line(self):
        r = reduce_system([Force("A", (0, 0, -100), ZERO),
                           Force("B", (0, 0, -200), (3, 0, 0))])
        self.assertEqual(r.kind, "single")
        self.assertVectorClose(r.resultant, (0, 0, -300))
        self.assertVectorClose(r.moment, (0, 600, 0))
        self.assertVectorClose(r.axis_point, (2, 0, 0))
        self.assertVectorClose(r.axis_direction, (0, 0, -1))
        self.assertAlmostEqual(r.pitch, 0.0)
        self.assertReconstruction(r)

    def test_single_force_action_line_contains_original_point(self):
        force = Force("A", (2, -3, 5), (7, -4, 6))
        r = reduce_system([force], (-1, 2, 3))
        self.assertEqual(r.kind, "single")
        self.assertVectorClose(cross(sub(force.point, r.axis_point), r.axis_direction), ZERO)
        self.assertReconstruction(r)

    def test_wrench_and_signed_pitch(self):
        for couple, pitch in [((0, 0, 30), 0.3), ((0, 0, -30), -0.3)]:
            with self.subTest(couple=couple):
                r = reduce_system([Force("A", (0, 0, 100), (2, -1, 4))],
                                  ZERO, couple)
                self.assertEqual(r.kind, "wrench")
                self.assertVectorClose(r.axis_point, (2, -1, 0))
                self.assertVectorClose(r.parallel_moment, couple)
                self.assertAlmostEqual(r.pitch, pitch)
                self.assertReconstruction(r)

    def test_perpendicular_free_couple_shifts_action_line(self):
        r = reduce_system([Force("A", (0, 0, 100), ZERO)], ZERO, (0, -200, 0))
        self.assertEqual(r.kind, "single")
        self.assertVectorClose(r.axis_point, (2, 0, 0))
        self.assertReconstruction(r)

    def test_line_reconstruction_at_several_axis_points(self):
        forces, origin, couple = examples()["空间力系 · 力螺旋"]
        r = reduce_system(forces, origin, couple)
        for t in [-100, -1.7, 0, 2.6, 100]:
            point = add(r.axis_point, mul(r.axis_direction, t))
            reconstructed = add(cross(sub(point, origin), r.resultant), r.parallel_moment)
            self.assertVectorClose(reconstructed, r.moment, absolute=1e-8)

    def test_change_reduction_origin(self):
        forces, origin, couple = examples()["空间力系 · 力螺旋"]
        a = reduce_system(forces, origin, couple)
        other = (20.3, -14.7, 6.2)
        b = reduce_system(forces, other, couple)
        self.assertEqual(a.kind, b.kind)
        self.assertVectorClose(a.resultant, b.resultant)
        self.assertVectorClose(b.moment, add(a.moment, cross(sub(origin, other), a.resultant)))
        self.assertVectorClose(a.parallel_moment, b.parallel_moment)
        self.assertAlmostEqual(a.pitch, b.pitch)
        self.assertVectorClose(cross(sub(b.axis_point, a.axis_point), a.axis_direction), ZERO)
        self.assertReconstruction(b)

    def test_translation_invariance(self):
        shift = (100.2, -45.3, 72.4)
        for forces, origin, couple in examples().values():
            a = reduce_system(forces, origin, couple)
            shifted = [Force(f.name, f.components, add(f.point, shift)) for f in forces]
            b = reduce_system(shifted, add(origin, shift), couple)
            self.assertEqual(a.kind, b.kind)
            self.assertVectorClose(a.resultant, b.resultant)
            self.assertVectorClose(a.moment, b.moment)
            self.assertVectorClose(a.parallel_moment, b.parallel_moment)
            if a.axis_point is not None:
                self.assertVectorClose(b.axis_point, add(a.axis_point, shift))

    def test_rotation_covariance(self):
        # 轴角公式产生非特殊姿态，验证空间力和力矩均按右手规则旋转。
        axis, angle = unit((1, 2, 3)), 0.731

        def rotate(v):
            return add(add(mul(v, math.cos(angle)),
                           mul(cross(axis, v), math.sin(angle))),
                       mul(axis, dot(axis, v) * (1 - math.cos(angle))))

        for forces, origin, couple in examples().values():
            a = reduce_system(forces, origin, couple)
            b = reduce_system([Force(f.name, rotate(f.components), rotate(f.point))
                               for f in forces], rotate(origin), rotate(couple))
            self.assertEqual(a.kind, b.kind)
            self.assertVectorClose(b.resultant, rotate(a.resultant))
            self.assertVectorClose(b.moment, rotate(a.moment))
            self.assertVectorClose(b.parallel_moment, rotate(a.parallel_moment))
            self.assertAlmostEqual(a.force_norm, b.force_norm, places=10)
            self.assertAlmostEqual(a.moment_norm, b.moment_norm, places=10)
            if a.axis_point is not None:
                self.assertVectorClose(b.axis_point, rotate(a.axis_point))
                self.assertAlmostEqual(a.pitch, b.pitch, places=10)

    def test_random_equivalent_reconstruction(self):
        rng = random.Random(20261016)
        for case in range(250):
            def rv(limit):
                return tuple(rng.uniform(-limit, limit) for _ in range(3))

            forces = [Force(str(i), rv(1000), rv(20)) for i in range(rng.randrange(1, 18))]
            origin, couple = rv(30), rv(100)
            r = reduce_system(forces, origin, couple)
            with self.subTest(case=case):
                expected_r = tuple(math.fsum(f.components[i] for f in forces) for i in range(3))
                # 独立地在指定 O 点直接求矩，校验内部形心变换。
                direct_moments = [cross(sub(f.point, origin), f.components) for f in forces]
                expected_m = tuple(math.fsum([*(m[i] for m in direct_moments), couple[i]])
                                   for i in range(3))
                self.assertVectorClose(r.resultant, expected_r)
                self.assertVectorClose(r.moment, expected_m, absolute=1e-8)
                self.assertReconstruction(r, absolute=1e-8)
                self.assertLess(r.force_residual, 1e-8)
                self.assertLess(r.moment_residual, 1e-8)

    def test_direction_constructors_and_direction_angles(self):
        f = Force.from_direction("A", 10, (3, 4, 0), ZERO)
        self.assertVectorClose(f.components, (6, 8, 0))
        self.assertVectorClose(Force.from_angles("B", 10, 90, 0, ZERO).components,
                               (0, 10, 0))
        self.assertVectorClose(Force.from_angles("C", 10, 720, 90, ZERO).components,
                               (0, 0, 10))
        info = direction_info((0, 0, -10))
        self.assertVectorClose(info["unit"], (0, 0, -1))
        self.assertVectorClose(info["angles_deg"], (90, 90, 180))
        self.assertEqual(info["elevation_deg"], -90)
        self.assertIsNone(info["azimuth_deg"])
        self.assertIsNone(direction_info(ZERO))

    def test_zero_magnitude_accepts_zero_direction(self):
        self.assertEqual(Force.from_direction("zero", 0, ZERO, ZERO).components, ZERO)

    def test_large_direction_is_normalized_without_overflow(self):
        f = Force.from_direction("A", 10, (1e308, -1e308, 1e308), ZERO)
        self.assertAlmostEqual(norm(f.components), 10)
        self.assertVectorClose(unit((1e-300, 0, 0)), (1, 0, 0))

    def test_invalid_vector_inputs(self):
        for value in [(1, 2), (1, 2, 3, 4), (math.nan, 0, 0),
                      (0, math.inf, 0), ("bad", 0, 0), None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                vector(value)
        with self.assertRaises(ValueError):
            Force("A", (math.inf, 0, 0), ZERO)
        with self.assertRaises(ValueError):
            reduce_system([], (math.nan, 0, 0))

    def test_invalid_force_direction_magnitude_and_angles(self):
        with self.assertRaises(ValueError):
            Force.from_direction("A", 1, ZERO, ZERO)
        for magnitude in [-1, math.nan, math.inf, "bad", None]:
            with self.subTest(magnitude=magnitude), self.assertRaises(ValueError):
                Force.from_direction("A", magnitude, (1, 0, 0), ZERO)
        for azimuth, elevation in [(math.nan, 0), (0, math.inf), (0, 91), (0, -91),
                                    (None, 0), (0, "bad")]:
            with self.subTest(angles=(azimuth, elevation)), self.assertRaises(ValueError):
                Force.from_angles("A", 1, azimuth, elevation, ZERO)

    def test_invalid_tolerances(self):
        for name in ["rtol", "force_atol", "moment_atol"]:
            for value in [-1, math.nan, math.inf, None, "bad"]:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    reduce_system([], **{name: value})

    def test_unrepresentable_result_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "浮点范围"):
            reduce_system([Force("A", (1e308, 0, 0), ZERO),
                           Force("B", (1e308, 0, 0), ZERO)])

    def test_tolerance_preserves_raw_values(self):
        r = reduce_system([Force("tiny", (1e-13, 0, 0), ZERO)])
        self.assertEqual(r.kind, "equilibrium")
        self.assertEqual(r.resultant, (1e-13, 0, 0))
        self.assertEqual(r.force_residual, 1e-13)

    def test_moment_scale_is_invariant_under_origin_change(self):
        forces = [Force("A", (12, 7, -9), (1, 2, 3)),
                  Force("B", (-4, 5, 8), (1, 2, 3))]
        near = reduce_system(forces, ZERO)
        far = reduce_system(forces, (1e12, -2e12, 3e12))
        self.assertEqual(near.kind, "single")
        self.assertEqual(near.kind, far.kind)
        self.assertEqual(near.moment_tolerance, far.moment_tolerance)
        self.assertVectorClose(near.parallel_moment, far.parallel_moment)

    def test_compensated_resultant_sum(self):
        forces = [Force("A", (1e16, 0, 0), ZERO),
                  Force("B", (1, 0, 0), ZERO),
                  Force("C", (-1e16, 0, 0), ZERO)]
        r = reduce_system(forces, rtol=0)
        self.assertVectorClose(r.resultant, (1, 0, 0))
        self.assertEqual(r.kind, "single")

    def test_examples_and_reports(self):
        expected = ["wrench", "single", "couple", "single", "equilibrium", "wrench"]
        for (name, (forces, origin, couple)), kind in zip(examples().items(), expected):
            with self.subTest(name=name):
                r = reduce_system(forces, origin, couple)
                self.assertEqual(r.kind, kind)
                self.assertReconstruction(r)
                report = make_report(forces, r, couple)
                self.assertIn("主矢 R", report)
                self.assertIn("主矩 M_O", report)
                self.assertIn("等效性校验", report)


if __name__ == "__main__":
    unittest.main()
