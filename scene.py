"""Tk Canvas 三维正交投影：旋转、缩放、平移、拾取及 SVG 导出。

所有输入和静力计算都保留三维坐标；只在绘制时做相机投影。
只依赖 Python 标准库，不需要 OpenGL、浏览器或第三方包。
"""
from __future__ import annotations

from html import escape
import math
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

from mechanics import ZERO, add, sub, mul, dot, cross, norm, unit, number

PALETTE = ("#2d6cdf", "#e89132", "#8b5cc2", "#13a38b", "#db6382", "#4b8b9b")
GREEN = "#00856a"
ROSE = "#cf426c"


class Scene3D(tk.Canvas):
    def __init__(self, master, on_select=None, **kwargs):
        super().__init__(master, background="#f9fbfd", highlightthickness=0, **kwargs)
        self.on_select = on_select
        self.forces = []
        self.result = None
        self.free_couple = ZERO
        self.mode = "对照"
        self.show_positions = True
        self.show_labels = True
        self.arrow_size = 1.0
        self.selected = None
        self.azimuth, self.elevation = -55., 27.
        self.zoom = 1.
        self.pan = [0., 0.]
        self.center, self.radius = ZERO, 1.
        self._drag = None
        self._moved = False
        self._primitives = []
        self._vector_directions = {}
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonPress-3>", self._press)
        self.bind("<B1-Motion>", self._rotate)
        self.bind("<B3-Motion>", self._pan)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self.zoom_by(1.12))
        self.bind("<Button-5>", lambda e: self.zoom_by(1/1.12))
        self.bind("<Double-Button-1>", lambda e: self.reset_view())

    def set_system(self, forces, result, free_couple=ZERO, *, fit=True):
        self.forces, self.result, self.free_couple = list(forces), result, free_couple
        self._build()
        if fit:
            self.fit()
        self.draw()

    def set_mode(self, mode):
        self.mode = mode
        self._build()
        self.fit()
        self.draw()

    def reset_view(self):
        self.azimuth, self.elevation = -55., 27.
        self.fit()
        self.draw()

    def set_view(self, view):
        self.azimuth, self.elevation = {
            "3D": (-55., 27.), "XY": (-90., 90.),
            "XZ": (-90., 0.), "YZ": (0., 0.)}[view]
        self.pan = [0., 0.]
        self.draw()

    def fit(self):
        points = [p for obj in self._primitives for p in obj[1]] or [ZERO]
        mins = tuple(min(p[i] for p in points) for i in range(3))
        maxs = tuple(max(p[i] for p in points) for i in range(3))
        self.center = tuple((a/2 + b/2) for a, b in zip(mins, maxs))
        self.radius = max((norm(sub(p, self.center)) for p in points), default=1.)
        if self.radius < 1e-15:
            self.radius = 1.
        self.zoom, self.pan = 1., [0., 0.]

    def _press(self, event):
        self._drag = (event.x, event.y)
        self._moved = False

    def _rotate(self, event):
        if self._drag:
            dx, dy = event.x-self._drag[0], event.y-self._drag[1]
            self.azimuth -= dx*.45
            self.elevation = max(-89.9, min(89.9, self.elevation + dy*.4))
            self._moved = self._moved or abs(dx)+abs(dy) > 2
            self._drag = (event.x, event.y)
            self.draw()

    def _pan(self, event):
        if self._drag:
            self.pan[0] += event.x-self._drag[0]
            self.pan[1] += event.y-self._drag[1]
            self._drag = (event.x, event.y)
            self.draw()

    def _release(self, event):
        if not self._moved and self.on_select:
            for item in reversed(self.find_overlapping(event.x-6, event.y-6, event.x+6, event.y+6)):
                tags = self.gettags(item)
                for tag in tags:
                    if tag.startswith("force:"):
                        self.on_select(int(tag.split(":")[1]))
                        return
        self._drag = None

    def _wheel(self, event):
        if event.delta:
            self.zoom_by(1.12 if event.delta > 0 else 1/1.12)

    def zoom_by(self, factor):
        self.zoom = max(.08, min(20., self.zoom*factor))
        self.draw()

    def _basis(self):
        a, e = math.radians(self.azimuth), math.radians(self.elevation)
        return ((-math.sin(a), math.cos(a), 0.),
                (-math.sin(e)*math.cos(a), -math.sin(e)*math.sin(a), math.cos(e)),
                (math.cos(e)*math.cos(a), math.cos(e)*math.sin(a), math.sin(e)))

    def project(self, point):
        right, up, eye = self._basis()
        v = sub(point, self.center)
        scale = min(max(self.winfo_width(), 10), max(self.winfo_height(), 10))*.40/self.radius*self.zoom
        return (self.winfo_width()/2 + dot(v, right)*scale + self.pan[0],
                self.winfo_height()/2 - dot(v, up)*scale + self.pan[1], dot(v, eye))

    def _primitive(self, kind, points, color, width=1., label="", tag=""):
        self._primitives.append((kind, tuple(points), color, width, label, tag))

    def _arrow(self, start, value, scale, color, label, tag="", moment=False, width=2.6,
               reference=None):
        if norm(value) == 0:
            return
        # Normalize before multiplying by the drawing length.  Dividing the
        # drawing length by a subnormal force first would produce infinity.
        displacement = (mul(tuple(component/reference for component in value), scale)
                        if reference else mul(value, scale))
        tip = add(start, displacement)
        self._primitive("moment" if moment else "arrow", (start, tip), color, width, label, tag)
        # Keep the actual vector direction even when adding a very short arrow
        # to a distant point rounds both of its endpoints to the same float.
        self._vector_directions[len(self._primitives)-1] = unit(value)
        if moment:
            # 绕矩向量的右手旋向弧线；双箭头轴仍表示矩向量本身。
            u = unit(value)
            helper = (0., 0., 1.) if abs(u[2]) < .9 else (1., 0., 0.)
            p, q = unit(cross(u, helper)), ZERO
            q = cross(u, p)
            radius = norm(sub(tip, start))*.16
            arc = [add(add(start, mul(p, radius*math.cos(t))), mul(q, radius*math.sin(t)))
                   for t in [(-.2 + i*1.65/26)*math.pi for i in range(27)]]
            self._primitive("arc", arc, color, 1.5)

    def _build(self):
        self._primitives = []
        self._vector_directions = {}
        r = self.result
        if r is None:
            return
        anchors = [r.origin, *(f.point for f in self.forces)]
        if r.axis_point is not None and self.mode in ("最简结果", "对照"):
            anchors.append(r.axis_point)
        spans = [max(p[i] for p in anchors)-min(p[i] for p in anchors) for i in range(3)]
        span = max(spans)
        if span == 0:
            span = 2.
        self.spatial_span = span
        fmax = max([r.force_norm, *(norm(f.components) for f in self.forces)], default=0)
        mmax = max(r.moment_norm, norm(self.free_couple), norm(r.parallel_moment))
        fs = .42*span*self.arrow_size if fmax else 0.
        ms = .36*span*self.arrow_size if mmax else 0.
        self.force_scale, self.moment_scale = fs, ms
        self._primitive("point", [r.origin], "#172b45", 6, "O")
        original = self.mode in ("原力系", "对照")
        for i, f in enumerate(self.forces):
            color = PALETTE[i % len(PALETTE)] if original else "#bdc8d6"
            tag = f"force:{i}"
            self._primitive("point", [f.point], color, 5, f"P{i+1}" if original else "", tag)
            if self.show_positions and original:
                self._primitive("dashed", [r.origin, f.point], "#c4cdd9", .9)
            if original:
                self._arrow(f.point, f.components, fs, color,
                            f"{f.name} · {number(norm(f.components), 5)} N", tag,
                            width=4.2 if self.selected == i else 2.6, reference=fmax)
        if original and norm(self.free_couple):
            self._arrow(r.origin, self.free_couple, ms, "#9d6ac1", "C (N·m)",
                        moment=True, reference=mmax)
        if self.mode == "简化到 O":
            self._arrow(r.origin, r.resultant, fs, GREEN, "R (N)", width=3.5, reference=fmax)
            self._arrow(r.origin, r.moment, ms, ROSE, "M_O (N·m)", moment=True,
                        width=3.2, reference=mmax)
        if self.mode in ("最简结果", "对照"):
            if r.kind in ("single", "wrench"):
                a, u = r.axis_point, r.axis_direction
                self._primitive("axis", [sub(a, mul(u, span*.7)), add(a, mul(u, span*.9))],
                                GREEN, 1.5)
                self._primitive("dashed", [r.origin, a], "#92b8ac", 1.1)
                self._primitive("point", [a], GREEN, 6, "A")
                self._arrow(a, r.resultant, fs, GREEN, "R (N)", width=3.8, reference=fmax)
                if r.kind == "wrench":
                    self._arrow(a, r.parallel_moment, ms, ROSE, "M_parallel (N·m)",
                                moment=True, width=3.2, reference=mmax)
            elif r.kind == "couple":
                self._arrow(r.origin, r.moment, ms, ROSE, "M (N·m)", moment=True,
                            width=3.4, reference=mmax)

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20 or self.result is None:
            return
        self._draw_grid()
        objects = sorted(enumerate(self._primitives),
                         key=lambda entry: sum(self.project(p)[2] for p in entry[1][1])/len(entry[1][1]))
        labels = []
        right, up, eye = self._basis()
        for primitive_index, (kind, points, color, width, label, tag) in objects:
            coords = [self.project(p) for p in points]
            xy = [v for p in coords for v in p[:2]]
            tags = (tag,) if tag else ()
            if kind == "point":
                x, y, _ = coords[0]
                self.create_oval(x-width, y-width, x+width, y+width,
                                 fill=color, outline="#ffffff", width=1.5, tags=tags)
                if label:
                    labels.append((x, y, label, color, tags))
            elif kind in ("arrow", "moment"):
                x1, y1, x2, y2 = xy
                length = math.hypot(x2-x1, y2-y1)
                direction = self._vector_directions[primitive_index]
                screen_direction = (dot(direction, right), -dot(direction, up))
                screen_fraction = math.hypot(*screen_direction)
                axial = screen_fraction <= 1e-6
                if not axial:
                    # A weak in-plane force is still in-plane.  A minimum
                    # arrow length preserves its direction when zoomed out.
                    if length < 12:
                        x2 = x1 + 12*screen_direction[0]/screen_fraction
                        y2 = y1 + 12*screen_direction[1]/screen_fraction
                        xy = [x1, y1, x2, y2]
                    self.create_line(*xy, fill=color, width=width,
                                     arrow="last", arrowshape=(7, 9, 4) if length < 12 else (11, 13, 5),
                                     tags=tags)
                    if kind == "moment":
                        p1 = (x1+.68*(x2-x1), y1+.68*(y2-y1))
                        p2 = (x1+.84*(x2-x1), y1+.84*(y2-y1))
                        self.create_line(*p1, *p2, fill=color, width=width,
                                         arrow="last", arrowshape=(9, 10, 4), tags=tags)
                else:
                    # 正对相机的矢量投影成点；圆点/叉表示出屏/入屏。
                    self.create_oval(x2-6, y2-6, x2+6, y2+6, outline=color, width=2, tags=tags)
                    self.create_text(x2, y2, text="•" if dot(direction, eye) > 0 else "×",
                                     fill=color, font=("Segoe UI", 11), tags=tags)
                labels.append((x2, y2, label, color, tags))
            else:
                options = {"fill": color, "width": width, "tags": tags}
                if kind in ("dashed", "axis"):
                    options["dash"] = (5, 5) if kind == "axis" else (3, 5)
                if kind == "arc":
                    options.update(arrow="last", arrowshape=(6, 8, 3), smooth=True)
                self.create_line(*xy, **options)
        if self.show_labels:
            self._draw_labels(labels, w, h)
        self._draw_compass(w-60, h-65)
        self.create_text(18, 18, text="ORTHOGRAPHIC  /  三维正交视图", anchor="nw",
                         fill="#8190a6", font=("Microsoft YaHei UI", 9))
        if self.result.kind == "equilibrium" and self.mode in ("最简结果", "简化到 O"):
            self.create_text(w/2, h*.30, text="平衡力系  ·  R ≈ 0，M ≈ 0",
                             fill=GREEN, font=("Microsoft YaHei UI", 14, "bold"))
        self.create_text(18, h-16, text="左键旋转  ·  滚轮缩放  ·  右键平移  ·  双击复位",
                         anchor="sw", fill="#76859a", font=("Microsoft YaHei UI", 9))

    @staticmethod
    def _overlap_area(a, b):
        return max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))

    def _draw_labels(self, labels, width, height):
        """Place labels in screen space, with leaders when they move away."""
        occupied = [(width-108, height-113, width-12, height-17)]
        markers = [(x-7, y-7, x+7, y+7) for x, y, *_ in labels]
        for x, y, text, color, tags in labels:
            item = self.create_text(0, 0, text=text, anchor="nw", fill=color,
                                    font=("Microsoft YaHei UI", 10, "bold"),
                                    width=max(60, min(260, width-28)),
                                    tags=(*tags, "scene-label"))
            bbox = self.bbox(item)
            tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
            candidates = []
            for ring in range(9):
                for left in (x+12+ring*10, x-tw-12-ring*10, x-tw/2):
                    for top in (y-th-9-ring*(th+8), y+9+ring*(th+8)):
                        left = max(12, min(max(12, width-tw-12), left))
                        top = max(44, min(max(44, height-th-42), top))
                        rect = (left, top, left+tw, top+th)
                        overlap = sum(self._overlap_area(rect, other) for other in (*occupied, *markers))
                        distance = math.hypot(max(left-x, 0, x-rect[2]), max(top-y, 0, y-rect[3]))
                        candidates.append((overlap*10000+distance, rect))
            _, rect = min(candidates, key=lambda entry: entry[0])
            self.move(item, rect[0]-bbox[0], rect[1]-bbox[1])
            actual = self.bbox(item)
            occupied.append((actual[0]-4, actual[1]-3, actual[2]+4, actual[3]+3))
            nearest = (max(actual[0], min(actual[2], x)), max(actual[1], min(actual[3], y)))
            if math.hypot(nearest[0]-x, nearest[1]-y) > 20:
                leader = self.create_line(x, y, *nearest, fill=color, width=1,
                                          tags=(*tags, "label-leader"))
                self.tag_lower(leader, item)

    def _draw_grid(self):
        span = max(self.radius*1.5, 1e-100)
        raw = span/5
        power = 10**math.floor(math.log10(raw))
        tick = next((x*power for x in (1, 2, 5, 10) if x*power >= raw), 10*power)
        bounds = [(math.floor((self.center[i]-span*.5)/tick)*tick,
                   math.ceil((self.center[i]+span*.5)/tick)*tick) for i in range(3)]
        z = bounds[2][0]
        for index in (0, 1):
            lo, hi = bounds[index]
            for j in range(min(15, round((hi-lo)/tick)+1)):
                v = lo+j*tick
                p = (v, bounds[1][0], z) if index == 0 else (bounds[0][0], v, z)
                q = (v, bounds[1][1], z) if index == 0 else (bounds[0][1], v, z)
                a, b = self.project(p), self.project(q)
                self.create_line(*a[:2], *b[:2], fill="#e2e8f0", width=1)
                self.create_text(a[0], a[1]+10, text=number(v, 3), fill="#9aa8ba",
                                 font=("Segoe UI", 8))
        for i, color in enumerate(("#d88c8c", "#86b79c", "#85a6d5")):
            if all(bounds[k][0] <= 0 <= bounds[k][1] for k in range(3) if k != i):
                p, q = [0., 0., 0.], [0., 0., 0.]
                p[i], q[i] = bounds[i]
                a, b = self.project(tuple(p)), self.project(tuple(q))
                self.create_line(*a[:2], *b[:2], fill=color, width=1.2,
                                 arrow="last", arrowshape=(5, 7, 3))
                self.create_text(b[0]+10, b[1]-5, text="XYZ"[i], fill=color,
                                 font=("Segoe UI", 10, "bold"))

    def _draw_compass(self, x, y):
        right, up, _ = self._basis()
        self.create_oval(x-45, y-45, x+45, y+45, fill="#ffffff", outline="#e5ebf2")
        for v, label, color in (((1., 0., 0.), "X", "#d36969"),
                                ((0., 1., 0.), "Y", "#389c73"),
                                ((0., 0., 1.), "Z", "#4385cd")):
            dx, dy = dot(v, right)*30, -dot(v, up)*30
            self.create_line(x, y, x+dx, y+dy, fill=color, width=2, arrow="last")
            self.create_text(x+dx*1.25, y+dy*1.25, text=label, fill=color,
                             font=("Segoe UI", 9, "bold"))

    @staticmethod
    def _wrapped_text_lines(text, width, measure):
        """Match Canvas word wrapping without depending on SVG text wrapping."""
        lines = []
        for paragraph in text.split("\n"):
            remaining = paragraph
            while width > 0 and measure(remaining) > width:
                lo, hi = 1, len(remaining)
                while lo < hi:
                    middle = (lo+hi+1)//2
                    if measure(remaining[:middle]) <= width:
                        lo = middle
                    else:
                        hi = middle-1
                split = max(remaining.rfind(" ", 0, lo+1), remaining.rfind("\t", 0, lo+1))
                split = split if split > 0 else max(1, lo)
                lines.append(remaining[:split].rstrip())
                remaining = remaining[split:].lstrip(" \t")
            lines.append(remaining)
        return lines

    def export_svg(self, path):
        """导出当前相机和图层；保留可编辑的矢量线条与文字。"""
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                  '<defs><marker id="head" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto-start-reverse" markerUnits="strokeWidth"><path d="M0,0 L8,3 L0,6 Z" fill="context-stroke"/></marker></defs>',
                  '<rect width="100%" height="100%" fill="#f9fbfd"/>']
        for item in self.find_all():
            kind, coords = self.type(item), self.coords(item)
            fill = self.itemcget(item, "fill") or "none"
            if kind == "line":
                pts = " ".join(f"{coords[i]:.3f},{coords[i+1]:.3f}" for i in range(0, len(coords), 2))
                style = f'fill="none" stroke="{fill}" stroke-width="{self.itemcget(item, "width")}" stroke-linecap="round"'
                if self.itemcget(item, "dash"):
                    style += ' stroke-dasharray="4,5"'
                if self.itemcget(item, "arrow") in ("last", "both"):
                    style += ' marker-end="url(#head)"'
                pieces.append(f'<polyline points="{pts}" {style}/>')
            elif kind == "oval":
                x1, y1, x2, y2 = coords
                pieces.append(f'<ellipse cx="{(x1+x2)/2}" cy="{(y1+y2)/2}" rx="{(x2-x1)/2}" ry="{(y2-y1)/2}" fill="{fill}" stroke="{self.itemcget(item, "outline") or "none"}"/>')
            elif kind == "text":
                bbox = self.bbox(item)
                font = tkfont.Font(root=self, font=self.itemcget(item, "font"))
                size = font.actual("size")
                size = abs(size) if size < 0 else size*self.winfo_fpixels("1p")
                family = escape(font.actual("family"), quote=True)
                bold = ' font-weight="bold"' if font.actual("weight") == "bold" else ""
                italic = ' font-style="italic"' if font.actual("slant") == "italic" else ""
                lines = self._wrapped_text_lines(self.itemcget(item, "text"),
                                                 float(self.itemcget(item, "width")), font.measure)
                x, baseline = bbox[0]+1, bbox[1]+font.metrics("ascent")
                pieces.append(f'<text x="{x}" y="{baseline}" fill="{fill}" font-family="{family}, sans-serif" font-size="{size}"{bold}{italic}>')
                for index, line in enumerate(lines):
                    dy = 0 if index == 0 else font.metrics("linespace")
                    pieces.append(f'<tspan x="{x}" dy="{dy}">{escape(line)}</tspan>')
                pieces.append('</text>')
        pieces.append("</svg>")
        Path(path).write_text("\n".join(pieces), encoding="utf-8")
