"""空间任意力系的静力等效简化；只使用 Python 标准库。

坐标采用右手直角坐标系，长度 m、力 N、力矩 N·m。
中心轴：A = O + (R × M_O) / |R|²，方向为 R。
最简力偶：M_parallel = (M_O · u) u，其中 u = R / |R|。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

Vec3 = tuple[float, float, float]
ZERO: Vec3 = (0.0, 0.0, 0.0)


def _finite_scalar(value, label: str) -> float:
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有限实数。") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label}必须是有限实数。")
    return value


def vector(values: Iterable[float], label: str = "向量") -> Vec3:
    try:
        result = tuple(float(v) for v in values)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}必须是三个有限实数。") from exc
    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise ValueError(f"{label}必须是三个有限实数，不能含 NaN 或无穷大。")
    return result  # type: ignore[return-value]


def add(a: Vec3, b: Vec3) -> Vec3:
    return tuple(x + y for x, y in zip(a, b))  # type: ignore[return-value]


def sub(a: Vec3, b: Vec3) -> Vec3:
    return tuple(x - y for x, y in zip(a, b))  # type: ignore[return-value]


def mul(a: Vec3, scale: float) -> Vec3:
    return tuple(x * scale for x in a)  # type: ignore[return-value]


def norm(a: Vec3) -> float:
    return math.hypot(*a)


def dot(a: Vec3, b: Vec3) -> float:
    return math.fsum(x * y for x, y in zip(a, b))


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])


def total(vectors: Iterable[Vec3]) -> Vec3:
    items = list(vectors)
    return tuple(math.fsum(v[i] for v in items) for i in range(3))  # type: ignore[return-value]


def unit(a: Vec3) -> Vec3:
    # 先缩放，避免极大方向向量求长度时溢出。
    a = vector(a)
    scale = max(abs(x) for x in a)
    if scale == 0:
        raise ValueError("非零力的方向向量不能为 (0, 0, 0)。")
    scaled = tuple(x / scale for x in a)
    return mul(scaled, 1 / norm(scaled))


@dataclass(frozen=True)
class Force:
    name: str
    components: Vec3
    point: Vec3

    def __post_init__(self):
        object.__setattr__(self, "name", str(self.name).strip() or "F")
        object.__setattr__(self, "components", vector(self.components, "力分量"))
        object.__setattr__(self, "point", vector(self.point, "作用点"))

    @classmethod
    def from_direction(cls, name, magnitude, direction, point):
        magnitude = _finite_scalar(magnitude, "力的大小")
        if magnitude < 0:
            raise ValueError("力的大小必须是非负的有限实数。")
        direction = vector(direction, "方向向量")
        components = ZERO if magnitude == 0 else mul(unit(direction), magnitude)
        return cls(name, components, point)

    @classmethod
    def from_angles(cls, name, magnitude, azimuth, elevation, point):
        azimuth = _finite_scalar(azimuth, "方位角")
        elevation = _finite_scalar(elevation, "仰角")
        if not -90 <= elevation <= 90:
            raise ValueError("仰角必须在 -90° 到 90° 之间。")
        phi, theta = math.radians(azimuth % 360), math.radians(elevation)
        direction = (math.cos(theta)*math.cos(phi),
                     math.cos(theta)*math.sin(phi), math.sin(theta))
        return cls.from_direction(name, magnitude, direction, point)


KINDS = {"equilibrium": "平衡力系", "couple": "纯力偶",
         "single": "单一合力", "wrench": "力螺旋"}


@dataclass(frozen=True)
class Reduction:
    origin: Vec3
    resultant: Vec3
    moment: Vec3
    kind: str
    force_norm: float
    moment_norm: float
    axis_point: Vec3 | None
    axis_direction: Vec3 | None
    parallel_moment: Vec3
    pitch: float | None
    force_tolerance: float
    moment_tolerance: float
    individual_moments: tuple[Vec3, ...]
    force_residual: float
    moment_residual: float


def reduce_system(forces: Iterable[Force], origin=ZERO, free_couple=ZERO,
                  *, rtol=1e-10, force_atol=1e-12, moment_atol=1e-12) -> Reduction:
    """返回主矢、主矩和最简结果。

    零值判据使用各物理量自己的量纲与尺度。力矩尺度取力的作用点
    形心处各力矩长度之和，避免更换简化点改变单力/力螺旋判定。
    容差只影响分类；resultant / moment 始终保留实际浮点计算结果。
    free_couple 是可选的附加自由力偶矩。
    """
    forces = tuple(forces)
    origin, free_couple = vector(origin, "简化点"), vector(free_couple, "自由力偶")
    rtol, force_atol, moment_atol = (
        _finite_scalar(t, "计算容差") for t in (rtol, force_atol, moment_atol))
    if not all(t >= 0 for t in (rtol, force_atol, moment_atol)):
        raise ValueError("计算容差必须是非负有限数。")
    try:
        resultant = total(f.components for f in forces)
        # 在载荷附近求矩，再移到 O，提高远距离简化点下的求和稳定性。
        if forces:
            anchor = forces[0].point
            center = add(anchor, total(mul(sub(f.point, anchor), 1/len(forces))
                                       for f in forces))
        else:
            center = origin
        local_moments = tuple(cross(sub(f.point, center), f.components) for f in forces)
        local_moment = total((*local_moments, free_couple))
        moment = add(local_moment, cross(sub(center, origin), resultant))
        moments_o = tuple(cross(sub(f.point, origin), f.components) for f in forces)
        force_scale = math.fsum(norm(f.components) for f in forces)
        moment_scale = math.fsum([*(norm(m) for m in local_moments), norm(free_couple)])
        ftol, mtol = force_atol + rtol*force_scale, moment_atol + rtol*moment_scale
        fn, mn = norm(resultant), norm(moment)
        axis_point = axis_direction = pitch = None
        parallel = ZERO
        if fn <= ftol:
            kind = "equilibrium" if mn <= mtol else "couple"
        else:
            axis_direction = tuple(x / fn for x in resultant)
            signed_parallel = dot(local_moment, axis_direction)
            parallel = mul(axis_direction, signed_parallel)
            pitch = signed_parallel / fn
            # 写成 u×M/|R|，避免直接计算 |R|² 产生不必要的溢出。
            axis_point = add(origin, tuple(x/fn for x in cross(axis_direction, moment)))
            kind = "single" if norm(parallel) <= mtol else "wrench"
        if kind == "equilibrium":
            reconstructed_force, reconstructed_moment = ZERO, ZERO
        elif kind == "couple":
            reconstructed_force, reconstructed_moment = ZERO, moment
        else:
            reconstructed_force = resultant
            reconstructed_moment = add(cross(sub(axis_point, origin), resultant),
                                       parallel if kind == "wrench" else ZERO)
        scalars = [*resultant, *moment, fn, mn, ftol, mtol, *parallel,
                   *(axis_point or ()), *(axis_direction or ())]
        if pitch is not None:
            scalars.append(pitch)
        if not all(math.isfinite(x) for x in scalars):
            raise ValueError("数值范围过大，计算超出浮点范围；请调整输入的数量级。")
        return Reduction(origin, resultant, moment, kind, fn, mn, axis_point,
                         axis_direction, parallel, pitch, ftol, mtol, moments_o,
                         norm(sub(reconstructed_force, resultant)),
                         norm(sub(reconstructed_moment, moment)))
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("数值范围过大，计算超出浮点范围；请调整输入的数量级。") from exc


def direction_info(v: Vec3, tolerance=0.0) -> dict | None:
    length = norm(v)
    if length <= tolerance:
        return None
    u = tuple(x/length for x in v)
    angles = tuple(math.degrees(math.acos(max(-1., min(1., c)))) for c in u)
    return {"unit": u, "angles_deg": angles,
            "azimuth_deg": math.degrees(math.atan2(v[1], v[0])) % 360
            if math.hypot(v[0], v[1]) > tolerance else None,
            "elevation_deg": math.degrees(math.atan2(v[2], math.hypot(v[0], v[1])))}


def number(value: float, digits=7) -> str:
    return "0" if value == 0 else f"{value:.{digits}g}"


def fmt(v: Vec3, digits=7) -> str:
    return "(" + ", ".join(number(x, digits) for x in v) + ")"


def examples() -> dict[str, tuple[list[Force], Vec3, Vec3]]:
    return {
        "空间力系 · 力螺旋": ([Force("F1", (80, 0, 0), (0, 1, 0)),
                              Force("F2", (0, 60, 0), (0, 0, 1)),
                              Force("F3", (0, 0, 40), (1, 0, 0))], ZERO, ZERO),
        "平行力系 · 单一合力": ([Force("F1", (0, 0, -100), (0, 0, 0)),
                                Force("F2", (0, 0, -200), (3, 0, 0))], ZERO, ZERO),
        "等大反向 · 纯力偶": ([Force("F1", (100, 0, 0), (0, 1, 0)),
                              Force("F2", (-100, 0, 0), (0, -1, 0))], ZERO, ZERO),
        "共点力系 · 单一合力": ([Force("F1", (30, 0, 0), (1, 2, 1)),
                                Force("F2", (0, 40, 0), (1, 2, 1)),
                                Force("F3", (0, 0, 50), (1, 2, 1))], (1, 2, 1), ZERO),
        "共线反向 · 平衡": ([Force("F1", (100, 0, 0), (1, 0, 0)),
                            Force("F2", (-100, 0, 0), (-1, 0, 0))], ZERO, ZERO),
        "负螺距 · 力螺旋": ([Force("F1", (0, 0, 100), ZERO)], ZERO, (0, 0, -30)),
    }


def make_report(forces, result: Reduction, free_couple=ZERO) -> str:
    r = result
    lines = ["空间任意力系简化计算报告", "="*48,
             "单位：力 N；坐标 m；力矩 N·m。右手直角坐标系。",
             f"简化点 O = {fmt(r.origin)} m", "", "输入载荷"]
    for i, f in enumerate(forces, 1):
        lines += [f"{i}. {f.name}: F = {fmt(f.components)} N，|F| = {number(norm(f.components))} N",
                  f"   P = {fmt(f.point)} m，M_Oi = {fmt(r.individual_moments[i-1])} N·m"]
    lines += [f"附加自由力偶 C = {fmt(free_couple)} N·m", ""]
    for name, value, tolerance, units in (("主矢 R", r.resultant, r.force_tolerance, "N"),
                                          ("主矩 M_O", r.moment, r.moment_tolerance, "N·m")):
        lines += [f"{name} = {fmt(value)} {units}", f"大小 = {number(norm(value))} {units}"]
        info = direction_info(value, tolerance)
        if info:
            lines += [f"单位方向向量 = {fmt(info['unit'])}",
                      f"与 +x、+y、+z 的方向角 (α, β, γ) = {fmt(info['angles_deg'])} °"]
        else:
            lines += ["方向：零向量（在容差内），方向未定义。"]
        lines += [""]
    lines += ["最简结果：" + KINDS[r.kind]]
    if r.kind == "equilibrium":
        lines += ["主矢、主矩均为零（在容差内），与零力系等效。"]
    elif r.kind == "couple":
        lines += [f"自由力偶矩 = {fmt(r.moment)} N·m。自由矢量，无固定作用点或作用线。"]
    else:
        lines += [f"合力 R = {fmt(r.resultant)} N", f"作用线/中心轴上一点 A = {fmt(r.axis_point)} m",
                  f"单位轴方向 u = {fmt(r.axis_direction)}", "作用线/中心轴的参数方程：",
                  f"  (x, y, z) = {fmt(r.axis_point)} + t {fmt(r.axis_direction)}，t ∈ R，单位 m。",
                  "A 是轴上距简化点 O 最近的点。"]
        if r.kind == "wrench":
            lines += [f"轴上剩余自由力偶 M_parallel = {fmt(r.parallel_moment)} N·m",
                      f"剩余力偶大小 = {number(norm(r.parallel_moment))} N·m",
                      f"螺距 h = {number(r.pitch)} m；正值同向，负值反向。"]
        else:
            lines += ["轴上力偶为零（在容差内），仅需该单一合力。"]
    lines += ["", "等效性校验（最简结果重构原主矢、主矩）",
              f"力残差 = {number(r.force_residual)} N",
              f"矩残差 = {number(r.moment_residual)} N·m", "", "计算依据",
              "R = ΣF_i；M_O = Σ[(P_i - O) × F_i] + C",
              "u = R/|R|；A = O + (R × M_O)/|R|²",
              "M_parallel = (M_O · u)u；h = (M_O · u)/|R|",
              "轴线：P(t) = A + t u；零向量方向未定义。",
              "容差：绝对容差 + 1e-10 × 对应输入尺度（默认值）。",
              f"本次力零值阈值 = {number(r.force_tolerance)} N",
              f"本次矩零值阈值 = {number(r.moment_tolerance)} N·m",
              "输出保留原始浮点值；分类及最简结果允许上述容差。",
              "该简化保持刚体的外部静力效应。"]
    return "\n".join(lines) + "\n"
