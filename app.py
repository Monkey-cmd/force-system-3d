"""空间力系简化 · Python 标准库桌面程序。

运行：python app.py
批处理：python app.py --input examples/01_wrench.json --report report.txt
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from mechanics import (Force, ZERO, KINDS, vector, reduce_system, direction_info,
                       examples, make_report, fmt, number, norm)
from scene import Scene3D, GREEN, ROSE

HERE = Path(__file__).resolve().parent
BG, INK, MUTED = "#eef2f7", "#20324b", "#738198"
FONT = "Microsoft YaHei UI"
MODES = ("分量 Fx / Fy / Fz", "大小 + 方向向量", "大小 + 方位角 / 仰角")


def prepare_display():
    """在创建窗口前启用 Windows DPI 感知，避免高分屏模糊及尺寸溢出。"""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


def project_data(forces, origin, couple):
    return {"schema_version": 1, "units": {"force": "N", "length": "m"},
            "origin": list(origin), "free_couple": list(couple),
            "forces": [asdict(f) for f in forces]}


def read_project(path):
    def json_vector(value, label):
        if (not isinstance(value, list) or len(value) != 3
                or not all(type(component) in (int, float) for component in value)):
            raise ValueError(f"{label}必须是三个有限实数的 JSON 数组。")
        return vector(value, label)

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1):
            raise ValueError("项目格式不正确，schema_version 应为 1。")
        if data.get("units") != {"force": "N", "length": "m"}:
            raise ValueError("项目必须使用 N 和 m；请先将数据换算为这些单位。")
        items = data["forces"]
        if not isinstance(items, list):
            raise ValueError("forces 必须是数组。")
        forces = []
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {i} 个力的格式不正确。")
            components = json_vector(item.get("components"), f"第 {i} 个力的 components")
            point = json_vector(item.get("point"), f"第 {i} 个力的 point")
            forces.append(Force(item.get("name", f"F{i}"), components, point))
        origin = json_vector(data["origin"], "简化点")
        couple = json_vector(data.get("free_couple", list(ZERO)), "附加力偶")
        reduce_system(forces, origin, couple)
        return forces, origin, couple
    except (KeyError, TypeError, json.JSONDecodeError, OverflowError) as exc:
        raise ValueError(f"项目数据不完整或格式错误：{exc}") from exc


class ScrollPanel(ttk.Frame):
    """仅在指针位于本面板内时滚动，避免抢占三维图的滚轮。"""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, style="White.TFrame", padding=16)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        x, y = self.winfo_pointerxy()
        if (self.winfo_rootx() <= x < self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty() <= y < self.winfo_rooty()+self.winfo_height()):
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


class ForceApp:
    def __init__(self, root):
        self.root = root
        root.title("空间力系简化 · Force System 3D")
        root.configure(background=BG)
        w, h = min(1580, root.winfo_screenwidth()-60), min(1000, root.winfo_screenheight()-80)
        root.geometry(f"{w}x{h}+30+25")
        root.minsize(1120, 720)
        self.forces = []
        self.origin, self.couple = ZERO, ZERO
        self.result = reduce_system([])
        self.selected = None
        self.previous_mode = MODES[0]
        self._updating = False
        self._styles()
        self._build()
        self.load_example(next(iter(examples())))
        root.bind("<Control-s>", lambda e: self.save_project())
        root.bind("<Control-o>", lambda e: self.open_project())

    def _styles(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", font=(FONT, 10), background=BG, foreground=INK)
        s.configure("TButton", padding=(10, 7), background="#ffffff", borderwidth=1)
        s.map("TButton", background=[("active", "#e7edf6")], foreground=[("disabled", "#a4afbe")])
        s.configure("Accent.TButton", background=GREEN, foreground="#ffffff", borderwidth=0)
        s.map("Accent.TButton", background=[("active", "#006d58")], foreground=[("disabled", "#bfd3cc")])
        s.configure("Small.TButton", padding=(7, 4), font=(FONT, 9))
        s.configure("White.TFrame", background="#ffffff")
        s.configure("White.TLabel", background="#ffffff")
        s.configure("Muted.TLabel", foreground=MUTED, background="#ffffff", font=(FONT, 9))
        s.configure("Section.TLabel", foreground=INK, background="#ffffff", font=(FONT, 11, "bold"))
        s.configure("TEntry", fieldbackground="#f8fafc", padding=6)
        s.configure("TCombobox", padding=5, fieldbackground="#f8fafc")
        s.configure("Treeview", rowheight=30, background="#ffffff", fieldbackground="#ffffff", borderwidth=0, font=(FONT, 9))
        s.configure("Treeview.Heading", background="#edf2f7", font=(FONT, 9, "bold"), padding=(4, 6))
        s.map("Treeview", background=[("selected", "#dceee8")], foreground=[("selected", "#006e59")])
        s.configure("TRadiobutton", padding=(6, 6))
        s.configure("TCheckbutton", padding=(4, 3))

    def _build(self):
        header = tk.Frame(self.root, background="#153a40", padx=22, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="空间力系简化", font=(FONT, 20, "bold"),
                 foreground="#ffffff", background="#153a40").pack(side="left")
        tk.Label(header, text="FORCE SYSTEM 3D  /  三维静力分析", font=(FONT, 10),
                 foreground="#a3c7c6", background="#153a40").pack(side="left", padx=20, pady=(8, 0))
        tk.Label(header, text="Python · 无第三方依赖", font=(FONT, 9),
                 foreground="#c1d8d4", background="#153a40").pack(side="right")
        tools = ttk.Frame(self.root, padding=(16, 10))
        tools.pack(fill="x")
        ttk.Label(tools, text="典型算例").pack(side="left", padx=(0, 8))
        self.example_var = tk.StringVar()
        box = ttk.Combobox(tools, textvariable=self.example_var, values=list(examples()),
                           state="readonly", width=26)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.load_example(self.example_var.get()))
        for text, command in (("打开 JSON", self.open_project), ("保存 JSON", self.save_project),
                              ("导出报告", self.export_report), ("导出图像 SVG", self.export_scene)):
            ttk.Button(tools, text=text, command=command, style="Small.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(tools, text="使用说明", command=self.show_help, style="Small.TButton").pack(side="right")
        self.status = tk.StringVar(value="就绪")
        footer = ttk.Frame(self.root, padding=(16, 7))
        footer.pack(side="bottom", fill="x")
        ttk.Label(footer, textvariable=self.status, font=(FONT, 9), foreground=MUTED).pack(side="left")
        ttk.Label(footer, text="右手坐标系   ·   N / m / N·m", font=(FONT, 9), foreground=MUTED).pack(side="right")
        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        left = ScrollPanel(panes, width=370)
        center = ttk.Frame(panes, padding=(12, 0))
        right = ttk.Frame(panes, style="White.TFrame", width=340)
        panes.add(left, weight=0)
        panes.add(center, weight=1)
        panes.add(right, weight=0)
        self._build_inputs(left.body)
        self._build_scene(center)
        self._build_results(right)
        self.root.after(50, lambda: self._initial_sashes(panes))

    def _initial_sashes(self, panes):
        try:
            width = panes.winfo_width()
            panes.sashpos(0, min(370, int(width*.28)))
            panes.sashpos(1, max(700, width-340))
        except tk.TclError:
            pass

    def _section(self, parent, title, subtitle=""):
        frame = ttk.Frame(parent, style="White.TFrame")
        frame.pack(fill="x", pady=(0, 9))
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(frame, text=subtitle, style="Muted.TLabel", wraplength=330).pack(anchor="w", pady=(4, 0))
        return frame

    def _triple(self, parent, labels, variables):
        frame = ttk.Frame(parent, style="White.TFrame")
        frame.pack(fill="x", pady=(1, 8))
        entries = []
        for i, (label, variable) in enumerate(zip(labels, variables)):
            frame.columnconfigure(i, weight=1)
            ttk.Label(frame, text=label, style="Muted.TLabel").grid(row=0, column=i, sticky="w", padx=(0, 5))
            entry = ttk.Entry(frame, textvariable=variable, width=8)
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 5))
            entries.append(entry)
        return frame, entries

    def _build_inputs(self, parent):
        tabs = ttk.Notebook(parent)
        tabs.pack(fill="x")
        force_page = ttk.Frame(tabs, style="White.TFrame", padding=(5, 12))
        settings_page = ttk.Frame(tabs, style="White.TFrame", padding=(8, 16))
        tabs.add(force_page, text="力与作用点")
        tabs.add(settings_page, text="简化点 / 力偶")
        parent = force_page
        self._section(parent, "01  定义力系", "选中表格中的力，可在下方编辑或从图中点选。")
        table_frame = ttk.Frame(parent, style="White.TFrame")
        table_frame.pack(fill="x")
        columns = ("name", "fx", "fy", "fz", "x", "y", "z")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=5, selectmode="browse")
        for col, label in zip(columns, ("名称", "Fx", "Fy", "Fz", "x", "y", "z")):
            self.table.heading(col, text=label)
            self.table.column(col, width=55, minwidth=45, anchor="center", stretch=True)
        self.table.column("name", width=65)
        self.table.pack(fill="x")
        scrollbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        scrollbar.pack(fill="x")
        self.table.configure(xscrollcommand=scrollbar.set)
        self.table.bind("<<TreeviewSelect>>", self._on_table_select)
        self.table.bind("<Delete>", lambda e: self.delete_force())
        row = ttk.Frame(parent, style="White.TFrame")
        row.pack(fill="x", pady=(6, 12))
        self.count_var = tk.StringVar()
        ttk.Label(row, textvariable=self.count_var, style="Muted.TLabel").pack(side="left")
        ttk.Button(row, text="删除选中", width=8, command=self.delete_force, style="Small.TButton").pack(side="right")
        ttk.Button(row, text="清空力系", width=8, command=self.clear_system, style="Small.TButton").pack(side="right", padx=5)
        ttk.Separator(parent).pack(fill="x", pady=(0, 12))
        self.editor_title = tk.StringVar(value="新建力")
        ttk.Label(parent, textvariable=self.editor_title, style="Section.TLabel").pack(anchor="w")
        self.name_var = tk.StringVar(value="F1")
        row = ttk.Frame(parent, style="White.TFrame")
        row.pack(fill="x", pady=(8, 6))
        ttk.Label(row, text="名称", style="White.TLabel").pack(side="left", padx=(0, 12))
        ttk.Entry(row, textvariable=self.name_var, width=13).pack(side="left", fill="x", expand=True)
        self.mode_var = tk.StringVar(value=MODES[0])
        mode = ttk.Combobox(parent, values=MODES, textvariable=self.mode_var, state="readonly")
        mode.pack(fill="x", pady=(0, 8))
        mode.bind("<<ComboboxSelected>>", self._switch_input_mode)
        self.mag_var = tk.StringVar(value="100")
        self.mag_frame = ttk.Frame(parent, style="White.TFrame")
        self.mag_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(self.mag_frame, text="力的大小 / N", style="White.TLabel").pack(side="left")
        ttk.Entry(self.mag_frame, textvariable=self.mag_var, width=14).pack(side="right")
        self.values = [tk.StringVar(value="0") for _ in range(3)]
        self.value_labels = [tk.StringVar(value=s) for s in ("Fx / N", "Fy / N", "Fz / N")]
        self.values_frame = ttk.Frame(parent, style="White.TFrame")
        self.values_frame.pack(fill="x")
        self.value_entries = []
        for i in range(3):
            self.values_frame.columnconfigure(i, weight=1)
            ttk.Label(self.values_frame, textvariable=self.value_labels[i], style="Muted.TLabel").grid(row=0, column=i, sticky="w")
            entry = ttk.Entry(self.values_frame, textvariable=self.values[i], width=8)
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 5))
            self.value_entries.append(entry)
        self.mode_help = tk.StringVar()
        ttk.Label(parent, textvariable=self.mode_help, style="Muted.TLabel", wraplength=330).pack(anchor="w", pady=(5, 8))
        ttk.Label(parent, text="作用点 P / m", style="White.TLabel").pack(anchor="w")
        self.point_vars = [tk.StringVar(value="0") for _ in range(3)]
        self._triple(parent, ("x", "y", "z"), self.point_vars)
        row = ttk.Frame(parent, style="White.TFrame")
        row.pack(fill="x", pady=(3, 4))
        ttk.Button(row, text="新增并计算", command=self.add_force, style="Accent.TButton").pack(side="left", fill="x", expand=True)
        self.update_button = ttk.Button(row, text="更新选中", command=self.update_force)
        self.update_button.pack(side="left", padx=(6, 0), fill="x", expand=True)
        ttk.Button(parent, text="清空编辑区 / 取消选择", command=self.reset_editor,
                   style="Small.TButton").pack(fill="x", pady=(2, 6))
        ttk.Label(parent, text="编辑后请点“新增并计算”或“更新选中”应用。",
                  style="Muted.TLabel", wraplength=330).pack(anchor="w")
        parent = settings_page
        self._section(parent, "02  选择简化点", "坐标与所有力的作用点使用同一坐标系。")
        self.origin_vars = [tk.StringVar(value="0") for _ in range(3)]
        self._triple(parent, ("Ox / m", "Oy / m", "Oz / m"), self.origin_vars)
        ttk.Label(parent, text="附加自由力偶 C（可选）", style="White.TLabel").pack(anchor="w", pady=(4, 2))
        self.couple_vars = [tk.StringVar(value="0") for _ in range(3)]
        self._triple(parent, ("Cx / N·m", "Cy / N·m", "Cz / N·m"), self.couple_vars)
        ttk.Button(parent, text="应用简化点 / 力偶", command=self.apply_settings,
                   style="Accent.TButton").pack(fill="x", pady=(2, 4))
        self.pending_var = tk.StringVar()
        ttk.Label(parent, textvariable=self.pending_var, style="Muted.TLabel", wraplength=330).pack(anchor="w")
        for var in (*self.origin_vars, *self.couple_vars):
            var.trace_add("write", self._settings_changed)
        self._update_mode_widgets()

    def _build_scene(self, parent):
        stats = tk.Frame(parent, background="#ffffff", padx=14, pady=10)
        stats.pack(fill="x", pady=(0, 10))
        self.r_metric = tk.StringVar()
        self.m_metric = tk.StringVar()
        tk.Label(stats, text="主矢 |R|", font=(FONT, 9), foreground=MUTED, background="#ffffff").grid(row=0, column=0, sticky="w")
        tk.Label(stats, text="主矩 |Mₒ|", font=(FONT, 9), foreground=MUTED, background="#ffffff").grid(row=0, column=1, sticky="w", padx=(30, 0))
        tk.Label(stats, textvariable=self.r_metric, font=(FONT, 18, "bold"), foreground=GREEN, background="#ffffff").grid(row=1, column=0, sticky="w")
        tk.Label(stats, textvariable=self.m_metric, font=(FONT, 18, "bold"), foreground=ROSE, background="#ffffff").grid(row=1, column=1, sticky="w", padx=(30, 0))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        modes = ttk.Frame(parent)
        modes.pack(fill="x", pady=(0, 6))
        self.scene_mode = tk.StringVar(value="对照")
        for name in ("原力系", "简化到 O", "最简结果", "对照"):
            ttk.Radiobutton(modes, text=name, variable=self.scene_mode, value=name,
                            command=lambda: self.scene.set_mode(self.scene_mode.get())).pack(side="left")
        self.scene = Scene3D(parent, on_select=self.select_force, width=570, height=400)
        self.scene.pack(fill="both", expand=True)
        controls = ttk.Frame(parent, padding=(0, 8))
        controls.pack(fill="x")
        for name in ("3D", "XY", "XZ", "YZ"):
            ttk.Button(controls, text=name, width=4, style="Small.TButton",
                       command=lambda n=name: self.scene.set_view(n)).pack(side="left", padx=(0, 4))
        ttk.Button(controls, text="复位", width=5, style="Small.TButton", command=self.scene.reset_view).pack(side="left")
        self.labels_var, self.positions_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="标签", variable=self.labels_var, command=self.update_scene_options).pack(side="right")
        ttk.Checkbutton(controls, text="位置连线", variable=self.positions_var, command=self.update_scene_options).pack(side="right")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="箭长", font=(FONT, 9)).pack(side="left")
        self.arrow_var = tk.DoubleVar(value=1.)
        ttk.Scale(row, variable=self.arrow_var, from_=.35, to=1.8,
                  command=lambda value: self.update_scene_options()).pack(side="left", fill="x", expand=True, padx=10)
        ttk.Label(parent, text="绿：合力 / 作用线    红：力矩（双箭头）    彩色：原始力",
                  font=(FONT, 9), foreground=MUTED, wraplength=620).pack(anchor="w", pady=(3, 3))
        ttk.Label(parent, text="位置按 m 绘制；力与力矩分别按比例缩放，箭长不用于读取空间距离。",
                  font=(FONT, 9), foreground=MUTED, wraplength=620).pack(anchor="w")

    def _build_results(self, parent):
        head = tk.Frame(parent, background="#ffffff", padx=16, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="03  计算结果", background="#ffffff", foreground=INK,
                 font=(FONT, 12, "bold")).pack(anchor="w")
        self.kind_var = tk.StringVar()
        tk.Label(head, textvariable=self.kind_var, background="#e5f2ec", foreground=GREEN,
                 font=(FONT, 13, "bold"), padx=10, pady=8).pack(fill="x", pady=(12, 0))
        frame = tk.Frame(parent, background="#ffffff")
        frame.pack(fill="both", expand=True, padx=(14, 0))
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        self.output = tk.Text(frame, wrap="word", width=31, borderwidth=0,
                              background="#ffffff", foreground=INK, font=(FONT, 10),
                              padx=2, pady=4, spacing1=3, spacing3=4, cursor="arrow",
                              yscrollcommand=scrollbar.set)
        self.output.pack(fill="both", expand=True)
        scrollbar.configure(command=self.output.yview)
        self.output.tag_configure("heading", foreground=GREEN, font=(FONT, 11, "bold"), spacing1=13)
        self.output.tag_configure("muted", foreground=MUTED, font=(FONT, 9))
        self.output.tag_configure("value", foreground="#183453", font=("Consolas", 11))
        self.output.configure(state="disabled")
        ttk.Button(parent, text="复制完整计算报告", command=self.copy_report).pack(fill="x", padx=16, pady=14)

    def _settings_changed(self, *args):
        if not self._updating:
            self.pending_var.set("参数有改动，请点击“应用简化点 / 力偶”。")

    def _settings(self):
        return (vector([v.get() for v in self.origin_vars], "简化点 O"),
                vector([v.get() for v in self.couple_vars], "附加自由力偶 C"))

    def _read_editor(self, mode=None):
        mode = mode or self.mode_var.get()
        name = self.name_var.get().strip() or f"F{len(self.forces)+1}"
        point = vector([v.get() for v in self.point_vars], "作用点")
        if mode == MODES[0]:
            return Force(name, vector([v.get() for v in self.values], "力分量"), point)
        if mode == MODES[1]:
            return Force.from_direction(name, self.mag_var.get(), [v.get() for v in self.values], point)
        return Force.from_angles(name, self.mag_var.get(), self.values[0].get(), self.values[1].get(), point)

    def _switch_input_mode(self, event=None):
        try:
            force = self._read_editor(self.previous_mode)
        except ValueError:
            force = Force(self.name_var.get(), (100, 0, 0), ZERO)
        self._fill_force(force, preserve_mode=True)
        self.previous_mode = self.mode_var.get()
        self._update_mode_widgets()

    def _update_mode_widgets(self):
        mode = self.mode_var.get()
        if mode == MODES[0]:
            self.mag_frame.pack_forget()
            labels = ("Fx / N", "Fy / N", "Fz / N")
            help_text = "直接输入三个带正负号的力分量。"
        else:
            self.mag_frame.pack(before=self.values_frame, fill="x", pady=(0, 6))
            if mode == MODES[1]:
                labels = ("dx", "dy", "dz")
                help_text = "方向向量会自动归一化，例如 (1, 1, 0)。"
            else:
                labels = ("方位角 φ / °", "仰角 θ / °", "—")
                help_text = "φ：XY 平面内由 +X 向 +Y；θ：与 XY 平面夹角，范围 ±90°。"
        for var, label in zip(self.value_labels, labels):
            var.set(label)
        self.value_entries[2].configure(state="disabled" if mode == MODES[2] else "normal")
        self.mode_help.set(help_text)

    def _fill_force(self, force, preserve_mode=False):
        if not preserve_mode:
            self.mode_var.set(MODES[0])
            self.previous_mode = MODES[0]
        self.name_var.set(force.name)
        for var, value in zip(self.point_vars, force.point):
            var.set(number(value, 15))
        magnitude = norm(force.components)
        self.mag_var.set(number(magnitude, 15))
        mode = self.mode_var.get()
        if mode == MODES[0]:
            values = force.components
        elif mode == MODES[1]:
            values = direction_info(force.components)["unit"] if magnitude else (1., 0., 0.)
        else:
            info = direction_info(force.components)
            values = (info["azimuth_deg"] or 0., info["elevation_deg"], 0.) if info else ZERO
        for var, value in zip(self.values, values):
            var.set(number(value, 15))
        self._update_mode_widgets()

    def reset_editor(self):
        self.selected = None
        if self.table.selection():
            self.table.selection_remove(*self.table.selection())
        self.editor_title.set("新建力")
        self.update_button.configure(state="disabled")
        self._fill_force(Force(f"F{len(self.forces)+1}", ZERO, ZERO))
        self.scene.selected = None
        self.scene._build()
        self.scene.draw()

    def _on_table_select(self, event=None):
        selected = self.table.selection()
        if selected:
            index = int(selected[0])
            if 0 <= index < len(self.forces):
                self.selected = index
                self._fill_force(self.forces[index])
                self.editor_title.set(f"编辑 {self.forces[index].name}  ·  第 {index+1} 个力")
                self.update_button.configure(state="normal")
                self.scene.selected = index
                self.scene._build()
                self.scene.draw()

    def select_force(self, index):
        if 0 <= index < len(self.forces):
            self.table.selection_set(str(index))
            self.table.see(str(index))
            self._on_table_select()

    def _commit(self, forces, origin, couple, *, selection=None, message="计算已更新"):
        # 先完整计算再替换状态，非法输入不会部分覆盖现有项目。
        result = reduce_system(forces, origin, couple)
        self.forces, self.origin, self.couple, self.result = list(forces), origin, couple, result
        self._updating = True
        try:
            for variables, values in ((self.origin_vars, origin), (self.couple_vars, couple)):
                for var, value in zip(variables, values):
                    var.set(number(value, 15))
        finally:
            self._updating = False
        self.pending_var.set("当前结果已应用上述参数。")
        self.table.delete(*self.table.get_children())
        for i, f in enumerate(self.forces):
            self.table.insert("", "end", iid=str(i), values=(f.name, *(number(v, 5) for v in (*f.components, *f.point))))
        self.count_var.set(f"共 {len(self.forces)} 个力  ·  N / m")
        self.scene.selected = selection
        self.scene.set_system(self.forces, self.result, self.couple)
        self._render_results()
        if selection is None:
            self.reset_editor()
        else:
            self.select_force(selection)
        self.status.set(message)

    def _error(self, error):
        self.status.set(str(error))
        messagebox.showerror("输入有误", str(error), parent=self.root)

    def add_force(self):
        try:
            force, (origin, couple) = self._read_editor(), self._settings()
            self._commit([*self.forces, force], origin, couple, selection=len(self.forces),
                         message=f"已添加 {force.name}，计算与 3D 图已更新。")
        except ValueError as exc:
            self._error(exc)

    def update_force(self):
        if self.selected is None:
            return
        try:
            force, (origin, couple) = self._read_editor(), self._settings()
            forces = self.forces.copy()
            forces[self.selected] = force
            self._commit(forces, origin, couple, selection=self.selected, message=f"已更新 {force.name}。")
        except ValueError as exc:
            self._error(exc)

    def delete_force(self):
        if self.selected is None:
            self.status.set("请先在表格或图中选中一个力。")
            return
        try:
            origin, couple = self._settings()
            forces = [f for i, f in enumerate(self.forces) if i != self.selected]
            self._commit(forces, origin, couple, message="已删除选中的力。")
        except ValueError as exc:
            self._error(exc)

    def clear_system(self):
        self._commit([], ZERO, ZERO, message="已清空力系，可从编辑区添加力。")
        self.example_var.set("")

    def apply_settings(self):
        try:
            origin, couple = self._settings()
            result = reduce_system(self.forces, origin, couple)
            self.origin, self.couple, self.result = origin, couple, result
            self.scene.set_system(self.forces, result, couple)
            self._render_results()
            self.pending_var.set("当前结果已应用上述参数。")
            self.status.set("简化点与力偶已应用，计算与 3D 图已更新。")
            return True
        except ValueError as exc:
            self._error(exc)
            return False

    def load_example(self, name):
        forces, origin, couple = examples()[name]
        self.example_var.set(name)
        self._commit(forces, origin, couple, message=f"已加载：{name}")

    def update_scene_options(self):
        self.scene.show_labels = self.labels_var.get()
        self.scene.show_positions = self.positions_var.get()
        self.scene.arrow_size = self.arrow_var.get()
        self.scene._build()
        self.scene.draw()

    def _render_results(self):
        r = self.result
        self.r_metric.set(f"{number(r.force_norm, 6)} N")
        self.m_metric.set(f"{number(r.moment_norm, 6)} N·m")
        self.kind_var.set(KINDS[r.kind])
        out = self.output
        out.configure(state="normal")
        out.delete("1.0", "end")
        def write(text, tag=None):
            out.insert("end", text + "\n", tag)
        write(f"当前简化点 O = {fmt(r.origin, 5)} m", "muted")
        for title, v, tolerance, units in (("主矢 R", r.resultant, r.force_tolerance, "N"),
                                          ("主矩 Mₒ", r.moment, r.moment_tolerance, "N·m")):
            write(title, "heading")
            write(f"{fmt(v, 6)} {units}", "value")
            write(f"大小  {number(norm(v), 7)} {units}")
            info = direction_info(v, tolerance)
            if info:
                write(f"单位方向  {fmt(info['unit'], 5)}")
                write("方向角 α / β / γ（°）", "muted")
                write(fmt(info["angles_deg"], 6), "value")
            else:
                write("在零值容差内，方向未定义。", "muted")
        write("最简等效结果", "heading")
        if r.kind == "equilibrium":
            write("主矢、主矩均为零（在容差内）。力系与零力系等效。")
        elif r.kind == "couple":
            write(f"力偶矩  {fmt(r.moment, 6)} N·m")
            write("力偶矩是自由矢量，无固定作用点和作用线。")
        else:
            write("定位矢量：合力 R" if r.kind == "single" else "中心轴上的合力 + 平行力偶")
            write("轴上一点 A / m", "muted")
            write(fmt(r.axis_point, 7), "value")
            write("单位轴方向 u", "muted")
            write(fmt(r.axis_direction, 6), "value")
            write("作用线：P(t) = A + t u")
            write("t 为任意实数（m）；A 为轴上距 O 最近的点。", "muted")
            if r.kind == "wrench":
                write("剩余力偶 M∥ / N·m", "muted")
                write(fmt(r.parallel_moment, 6), "value")
                write(f"|M∥| = {number(norm(r.parallel_moment), 7)} N·m")
                write(f"螺距 h = {number(r.pitch, 7)} m")
                write("力偶与合力同向。" if r.pitch > 0 else "力偶与合力反向。", "muted")
            else:
                write("剩余力偶为零（在容差内）。")
        write("等效性校验", "heading")
        write(f"力残差  {number(r.force_residual, 4)} N", "muted")
        write(f"矩残差  {number(r.moment_residual, 4)} N·m", "muted")
        write("数值判定阈值", "heading")
        write(f"力  {number(r.force_tolerance, 4)} N", "muted")
        write(f"矩  {number(r.moment_tolerance, 4)} N·m", "muted")
        write("零值分类采用相应量纲的绝对与相对容差；分量保留实际计算值。", "muted")
        write("α、β、γ 分别为与 +X、+Y、+Z 轴的夹角，范围 0°–180°。", "muted")
        out.configure(state="disabled")
        out.yview_moveto(0)

    def open_project(self):
        path = filedialog.askopenfilename(parent=self.root, title="打开力系项目", initialdir=HERE/"examples",
                                          filetypes=[("力系项目", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            forces, origin, couple = read_project(path)
            self._commit(forces, origin, couple, message=f"已打开 {Path(path).name}")
            self.example_var.set("")
        except (OSError, ValueError) as exc:
            self._error(exc)

    def _export_ready(self):
        # 导出当前可见的已应用结果；编辑区独立，避免无提示地覆盖选中力。
        try:
            origin, couple = self._settings()
            if origin != self.origin or couple != self.couple:
                return self.apply_settings()
            return True
        except ValueError as exc:
            self._error(exc)
            return False

    def save_project(self):
        if not self._export_ready():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="保存已应用的力系", defaultextension=".json",
                                            initialfile="force_system.json", filetypes=[("JSON", "*.json")])
        if path:
            try:
                Path(path).write_text(json.dumps(project_data(self.forces, self.origin, self.couple),
                                                ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                self.status.set(f"项目已保存：{Path(path).name}")
            except (OSError, ValueError) as exc:
                self._error(exc)

    def export_report(self):
        if not self._export_ready():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="导出计算报告", defaultextension=".txt",
                                            initialfile="力系简化计算报告.txt", filetypes=[("文本报告", "*.txt")])
        if path:
            try:
                Path(path).write_text(make_report(self.forces, self.result, self.couple), encoding="utf-8-sig")
                self.status.set(f"报告已导出：{Path(path).name}")
            except OSError as exc:
                self._error(exc)

    def copy_report(self):
        if self._export_ready():
            self.root.clipboard_clear()
            self.root.clipboard_append(make_report(self.forces, self.result, self.couple))
            self.status.set("完整计算报告已复制到剪贴板。")

    def export_scene(self):
        if not self._export_ready():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="导出当前 3D 视图", defaultextension=".svg",
                                            initialfile="force_system_3d.svg", filetypes=[("SVG 矢量图", "*.svg")])
        if path:
            try:
                self.scene.export_svg(path)
                self.status.set(f"当前视图已导出：{Path(path).name}")
            except OSError as exc:
                self._error(exc)

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用说明与计算原理")
        win.geometry("760x680")
        text = tk.Text(win, wrap="word", font=(FONT, 11), padx=24, pady=20, spacing3=7)
        bar = ttk.Scrollbar(win, command=text.yview)
        bar.pack(side="right", fill="y")
        text.configure(yscrollcommand=bar.set)
        text.pack(fill="both", expand=True)
        text.insert("end", (HERE/"README.md").read_text(encoding="utf-8"))
        text.configure(state="disabled")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Python 空间力系简化及三维交互程序")
    parser.add_argument("--input", type=Path, help="加载 JSON 项目；与 --report 配合时无须图形窗口")
    parser.add_argument("--report", type=Path, help="将计算报告写到指定 TXT 文件并退出")
    parser.add_argument("--export-svg", type=Path, help="导出当前初始视图并退出（需要图形显示环境）")
    args = parser.parse_args(argv)
    try:
        if args.report:
            if not args.input:
                parser.error("--report 需要同时提供 --input")
            forces, origin, couple = read_project(args.input)
            result = reduce_system(forces, origin, couple)
            args.report.write_text(make_report(forces, result, couple), encoding="utf-8-sig")
            print(f"报告已保存：{args.report.resolve()}")
            return 0
        prepare_display()
        root = tk.Tk()
        app = ForceApp(root)
        if args.input:
            app._commit(*read_project(args.input), message=f"已加载 {args.input.name}")
            app.example_var.set("")
        if args.export_svg:
            def export_and_quit():
                try:
                    app.scene.export_svg(args.export_svg)
                finally:
                    root.destroy()
            root.after(300, export_and_quit)
        root.mainloop()
        return 0
    except (ValueError, OSError, tk.TclError) as exc:
        print(f"无法运行：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
