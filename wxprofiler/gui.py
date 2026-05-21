from __future__ import annotations

import argparse
import contextlib
import io
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from wxprofiler.cli import command_profile, command_compare, command_batch, parse_date

APP_TITLE = "Airport Weather Profiler"
APP_SUBTITLE = "Universal airport weather statistics / METAR · NOAA ISD · wind rose · reports"


def _default_start(years: int) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today - timedelta(days=365 * years)


class QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue[str]) -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


class WeatherProfilerApp(tk.Tk):
    """Human-facing Tk UI for wxprofiler.

    The CLI remains available internally, but this window is designed so a normal
    user can run airport weather reports without typing commands.
    """

    def __init__(self) -> None:
        super().__init__()
        # Language variables must exist before any localized text is requested.
        self.ui_language_var = tk.StringVar(value="zh")
        self.language_display_var = tk.StringVar(value="中文")

        self.title(self._L("Airport Weather Profiler - 人类用机场天气统计器", "Airport Weather Profiler"))
        self.geometry("1180x820")
        self.minsize(1040, 720)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.preview_images: list[tk.PhotoImage] = []
        self.last_result_path: Path | None = None

        # Core user fields
        self.single_airport_var = tk.StringVar(value="RJCC")
        self.compare_airports_var = tk.StringVar(value="RJCC RJCJ RJTT")
        self.batch_file_var = tk.StringVar(value="")
        self.period_preset_var = tk.StringVar(value="10")
        self.start_var = tk.StringVar(value="")
        self.end_var = tk.StringVar(value=date.today().isoformat())
        self.source_var = tk.StringVar(value="auto")
        self.out_dir_var = tk.StringVar(value="data/weather")
        self.cache_dir_var = tk.StringVar(value="data/weather/cache")
        self.runways_var = tk.StringVar(value="")
        self.local_file_var = tk.StringVar(value="")
        self.wind_sector_var = tk.StringVar(value="20")
        self.force_var = tk.BooleanVar(value=False)
        self.auto_runways_var = tk.BooleanVar(value=True)
        self.merge_all_var = tk.BooleanVar(value=False)
        self.include_iem_var = tk.BooleanVar(value=False)
        self.charts_var = tk.BooleanVar(value=True)
        self.pdf_var = tk.BooleanVar(value=True)
        self.html_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=self._L("就绪", "Ready"))
        self.preview_status_var = tk.StringVar(value=self._L("还没有报告。运行一次统计后，这里会显示图表预览。", "No report yet. Run a profile to show chart previews here."))

        self._setup_style()
        self._build_ui()
        self._poll_log()

    def _L(self, zh: str, en: str) -> str:
        return en if self.ui_language_var.get() == "en" else zh

    def _on_language_change(self, *_args) -> None:
        display = self.language_display_var.get()
        self.ui_language_var.set("en" if display == "English" else "zh")
        self.title(self._L("Airport Weather Profiler - 人类用机场天气统计器", "Airport Weather Profiler"))
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        if self.worker and self.worker.is_alive():
            self._set_running(True)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        with contextlib.suppress(Exception):
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", foreground="#5a5f66")
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("Danger.TButton", padding=(10, 6))
        style.configure("Hint.TLabel", foreground="#69717c")
        style.configure("Small.TLabel", foreground="#69717c", font=("Segoe UI", 9))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 10))
        header_left = ttk.Frame(header)
        header_left.pack(side="left", fill="x", expand=True)
        header_right = ttk.Frame(header)
        header_right.pack(side="right", anchor="ne")
        ttk.Label(header_left, text="Airport Weather Profiler", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header_left, text=self._L("输入机场代码，点按钮，自动生成风玫瑰、柱状图、HTML/PDF报告和模拟器天气 profile。", "Enter an airport code, then generate wind roses, charts, HTML/PDF reports, and simulator-ready weather profiles."), style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(header_right, text=self._L("界面语言", "Language"), style="Small.TLabel").pack(anchor="e")
        lang_box = ttk.Combobox(header_right, textvariable=self.language_display_var, values=["中文", "English"], width=10, state="readonly")
        lang_box.pack(anchor="e", pady=(3, 0))
        lang_box.bind("<<ComboboxSelected>>", self._on_language_change)

        main = ttk.PanedWindow(root, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main, padding=(0, 0, 10, 0))
        right = ttk.Frame(main)
        main.add(left, weight=3)
        main.add(right, weight=2)

        self.workbook = ttk.Notebook(left)
        self.workbook.pack(fill="both", expand=True)

        self.single_tab = ttk.Frame(self.workbook, padding=12)
        self.compare_tab = ttk.Frame(self.workbook, padding=12)
        self.batch_tab = ttk.Frame(self.workbook, padding=12)
        self.settings_tab = ttk.Frame(self.workbook, padding=12)
        self.workbook.add(self.single_tab, text=self._L("单机场统计", "Single Airport"))
        self.workbook.add(self.compare_tab, text=self._L("多机场对比", "Compare Airports"))
        self.workbook.add(self.batch_tab, text=self._L("批量报告", "Batch Reports"))
        self.workbook.add(self.settings_tab, text=self._L("数据与输出设置", "Data & Output"))

        self._build_single_tab(self.single_tab)
        self._build_compare_tab(self.compare_tab)
        self._build_batch_tab(self.batch_tab)
        self._build_settings_tab(self.settings_tab)

        self.rightbook = ttk.Notebook(right)
        self.rightbook.pack(fill="both", expand=True)
        self.preview_tab = ttk.Frame(self.rightbook, padding=10)
        self.log_tab = ttk.Frame(self.rightbook, padding=10)
        self.rightbook.add(self.preview_tab, text=self._L("结果预览", "Preview"))
        self.rightbook.add(self.log_tab, text=self._L("运行日志", "Run Log"))
        self._build_preview(self.preview_tab)
        self._build_log(self.log_tab)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(footer, mode="determinate", length=280, maximum=100)
        self.progress.pack(side="left")
        ttk.Label(footer, textvariable=self.status_var, style="Hint.TLabel").pack(side="left", padx=10)
        self.cancel_button = ttk.Button(footer, text=self._L("取消当前任务", "Cancel Current Job"), command=self._cancel_current_task, state="disabled")
        self.cancel_button.pack(side="right")
        ttk.Button(footer, text=self._L("打开输出文件夹", "Open Output Folder"), command=self._open_output_folder).pack(side="right", padx=8)
        ttk.Button(footer, text=self._L("清空日志", "Clear Log"), command=self._clear_log).pack(side="right", padx=8)

    def _build_single_tab(self, parent: ttk.Frame) -> None:
        self._intro(parent, self._L("单机场统计", "Single Airport Profile"), self._L("适合生成某一个机场过去 10 年或 20 年的完整气象画像，包括风玫瑰、月度天气、小时风险、跑道侧风/顺风统计和报告。", "Generate a complete 10- or 20-year operating weather profile for one airport, including wind rose, monthly weather, hourly risk, runway wind components, and reports."))

        box = ttk.LabelFrame(parent, text=self._L("机场", "Airport"), style="Card.TLabelframe")
        box.pack(fill="x", pady=10)
        ttk.Label(box, text=self._L("ICAO 代码", "ICAO code")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        entry = ttk.Entry(box, textvariable=self.single_airport_var, width=16, font=("Consolas", 13))
        entry.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(box, text=self._L("例：RJCC、RJTT、KLAX、EGLL、EDDF", "Example: RJCC, RJTT, KLAX, EGLL, EDDF"), style="Small.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        box.columnconfigure(2, weight=1)

        self._period_card(parent)
        self._quick_options_card(parent)

        action = ttk.Frame(parent)
        action.pack(fill="x", pady=(16, 0))
        self.single_run_button = ttk.Button(action, text=self._L("生成这个机场的完整天气统计", "Generate Full Airport Weather Profile"), style="Primary.TButton", command=self._run_single)
        self.single_run_button.pack(side="left")
        ttk.Button(action, text=self._L("查看最近报告", "Open Latest Report"), command=self._open_latest_html).pack(side="left", padx=10)

    def _build_compare_tab(self, parent: ttk.Frame) -> None:
        self._intro(parent, self._L("多机场对比", "Airport Comparison"), self._L("适合比较 RJCC/RJCJ/RJTT 或 KLAX/KSFO 这类机场组，输出对比图、对比表和 HTML 报告。", "Compare groups such as RJCC/RJCJ/RJTT or KLAX/KSFO and generate comparison charts, tables, and an HTML report."))

        box = ttk.LabelFrame(parent, text=self._L("机场组", "Airport Group"), style="Card.TLabelframe")
        box.pack(fill="x", pady=10)
        ttk.Label(box, text=self._L("ICAO 列表", "ICAO list")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(box, textvariable=self.compare_airports_var, font=("Consolas", 12)).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(box, text=self._L("用空格分隔，至少两个机场", "Separate with spaces; at least two airports required"), style="Small.TLabel").grid(row=1, column=1, sticky="w", padx=8, pady=(0, 8))
        box.columnconfigure(1, weight=1)

        self._period_card(parent)
        self._quick_options_card(parent)

        action = ttk.Frame(parent)
        action.pack(fill="x", pady=(16, 0))
        self.compare_run_button = ttk.Button(action, text=self._L("生成机场对比报告", "Generate Airport Comparison"), style="Primary.TButton", command=self._run_compare)
        self.compare_run_button.pack(side="left")
        ttk.Button(action, text=self._L("查看最近对比报告", "Open Latest Comparison"), command=self._open_latest_html).pack(side="left", padx=10)

    def _build_batch_tab(self, parent: ttk.Frame) -> None:
        self._intro(parent, self._L("批量报告", "Batch Reports"), self._L("适合一次性给很多机场生成 profile。文本文件里每行一个 ICAO，井号开头的行会被忽略。", "Generate profiles for many airports at once. Use one ICAO per line; lines starting with # are ignored."))

        box = ttk.LabelFrame(parent, text=self._L("机场列表文件", "Airport List File"), style="Card.TLabelframe")
        box.pack(fill="x", pady=10)
        ttk.Label(box, text=self._L("列表文件", "List file")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(box, textvariable=self.batch_file_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(box, text=self._L("选择文件", "Choose File"), command=lambda: self._choose_file(self.batch_file_var, [("Text files", "*.txt"), ("All files", "*.*")])).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(box, text=self._L("创建示例列表", "Create Example List"), command=self._create_sample_batch_file).grid(row=0, column=3, padx=8, pady=8)
        box.columnconfigure(1, weight=1)

        self._period_card(parent)
        self._quick_options_card(parent)

        action = ttk.Frame(parent)
        action.pack(fill="x", pady=(16, 0))
        self.batch_run_button = ttk.Button(action, text=self._L("开始批量生成", "Start Batch Generation"), style="Primary.TButton", command=self._run_batch)
        self.batch_run_button.pack(side="left")
        ttk.Button(action, text=self._L("查看最近报告", "Open Latest Report"), command=self._open_latest_html).pack(side="left", padx=10)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        self._intro(parent, self._L("数据与输出设置", "Data & Output Settings"), self._L("这里是高级设置。默认值已经适合普通使用：自动多源、自动跑道数据库、自动图表、HTML/PDF 输出。", "Advanced settings. The defaults are suitable for normal use: automatic data source, automatic runway database, charts, and HTML/PDF output."))

        source = ttk.LabelFrame(parent, text=self._L("数据源", "Data Source"), style="Card.TLabelframe")
        source.pack(fill="x", pady=10)
        ttk.Label(source, text=self._L("数据源策略", "Source strategy")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Combobox(source, textvariable=self.source_var, values=["auto", "iem", "noaa-isd", "meteostat", "local"], width=14, state="readonly").grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(source, text=self._L("auto 默认 NOAA ISD 优先；IEM 默认不碰；勾选 IEM 后会自动使用 Polite Mode。", "auto uses NOAA ISD first. IEM is disabled by default; when enabled it uses polite mode automatically."), style="Small.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(source, text=self._L("本地 CSV", "Local CSV")).grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(source, textvariable=self.local_file_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Button(source, text=self._L("选择 CSV", "Choose CSV"), command=lambda: self._choose_file(self.local_file_var, [("CSV files", "*.csv"), ("All files", "*.*")])).grid(row=1, column=3, padx=8, pady=8)
        source.columnconfigure(2, weight=1)

        output = ttk.LabelFrame(parent, text=self._L("输出与缓存", "Output & Cache"), style="Card.TLabelframe")
        output.pack(fill="x", pady=10)
        ttk.Label(output, text=self._L("输出目录", "Output folder")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(output, textvariable=self.out_dir_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(output, text=self._L("选择", "Browse"), command=lambda: self._choose_dir(self.out_dir_var)).grid(row=0, column=2, padx=8, pady=8)
        ttk.Label(output, text=self._L("缓存目录", "Cache folder")).grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(output, textvariable=self.cache_dir_var).grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(output, text=self._L("选择", "Browse"), command=lambda: self._choose_dir(self.cache_dir_var)).grid(row=1, column=2, padx=8, pady=8)
        output.columnconfigure(1, weight=1)

        runway = ttk.LabelFrame(parent, text=self._L("跑道与统计", "Runway & Statistics"), style="Card.TLabelframe")
        runway.pack(fill="x", pady=10)
        ttk.Checkbutton(runway, text=self._L("自动读取跑道数据库", "Auto runway database"), variable=self.auto_runways_var).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(runway, text=self._L("强制重新下载源数据", "Force re-download"), variable=self.force_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(runway, text=self._L("整合所有可用来源", "Merge all available sources"), variable=self.merge_all_var).grid(row=0, column=2, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(runway, text=self._L("单独尝试 IEM/METAR（默认 Polite Mode，较慢但少 429）", "Try IEM/METAR with default polite mode (slower, fewer 429s)"), variable=self.include_iem_var).grid(row=0, column=3, sticky="w", padx=8, pady=8)
        ttk.Label(runway, text=self._L("风向扇区", "Wind sector")).grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Combobox(runway, textvariable=self.wind_sector_var, values=["10", "20", "30", "45"], width=8, state="readonly").grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(runway, text=self._L("手工跑道 YAML", "Manual runway YAML")).grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(runway, textvariable=self.runways_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Button(runway, text=self._L("选择 YAML", "Choose YAML"), command=lambda: self._choose_file(self.runways_var, [("YAML files", "*.yaml *.yml"), ("All files", "*.*")])).grid(row=2, column=3, padx=8, pady=8)
        runway.columnconfigure(2, weight=1)

        reports = ttk.LabelFrame(parent, text=self._L("报告输出", "Report Outputs"), style="Card.TLabelframe")
        reports.pack(fill="x", pady=10)
        ttk.Checkbutton(reports, text=self._L("生成图表 PNG", "Generate PNG charts"), variable=self.charts_var).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(reports, text=self._L("生成 HTML 报告", "Generate HTML report"), variable=self.html_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(reports, text=self._L("生成 PDF 报告", "Generate PDF report"), variable=self.pdf_var).grid(row=0, column=2, sticky="w", padx=8, pady=8)

    def _period_card(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=self._L("统计时间", "Time Period"), style="Card.TLabelframe")
        box.pack(fill="x", pady=10)
        ttk.Label(box, text=self._L("快捷范围", "Preset range")).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Radiobutton(box, text=self._L("过去 10 年", "Past 10 years"), value="10", variable=self.period_preset_var, command=self._period_changed).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Radiobutton(box, text=self._L("过去 20 年", "Past 20 years"), value="20", variable=self.period_preset_var, command=self._period_changed).grid(row=0, column=2, sticky="w", padx=8)
        ttk.Radiobutton(box, text=self._L("自定义", "Custom"), value="custom", variable=self.period_preset_var, command=self._period_changed).grid(row=0, column=3, sticky="w", padx=8)
        ttk.Label(box, text=self._L("开始", "Start")).grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(box, textvariable=self.start_var, width=14).grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(box, text=self._L("结束", "End")).grid(row=1, column=2, sticky="e", padx=8, pady=8)
        ttk.Entry(box, textvariable=self.end_var, width=14).grid(row=1, column=3, sticky="w", padx=8, pady=8)
        ttk.Label(box, text=self._L("留空开始日期时，会按快捷范围自动计算。", "Leave Start empty to use the preset range."), style="Small.TLabel").grid(row=1, column=4, sticky="w", padx=8)
        box.columnconfigure(4, weight=1)

    def _quick_options_card(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=self._L("常用输出", "Common Outputs"), style="Card.TLabelframe")
        box.pack(fill="x", pady=10)
        ttk.Checkbutton(box, text=self._L("图表", "Charts"), variable=self.charts_var).grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(box, text=self._L("HTML 报告", "HTML report"), variable=self.html_var).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(box, text=self._L("PDF 报告", "PDF report"), variable=self.pdf_var).grid(row=0, column=2, sticky="w", padx=8, pady=8)
        ttk.Checkbutton(box, text=self._L("自动跑道数据库", "Auto runway database"), variable=self.auto_runways_var).grid(row=0, column=3, sticky="w", padx=8, pady=8)
        ttk.Label(box, text=self._L("默认走 NOAA ISD，不自动尝试 IEM。需要 METAR 细节时勾选 IEM，程序会用 Polite Mode 慢速请求。", "Default source is NOAA ISD. IEM is not tried automatically. Enable IEM for METAR detail; polite mode is used automatically."), style="Small.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))

    def _intro(self, parent: ttk.Frame, title: str, body: str) -> None:
        ttk.Label(parent, text=title, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(parent, text=body, style="Hint.TLabel", wraplength=720, justify="left").pack(anchor="w", pady=(4, 8))

    def _build_preview(self, parent: ttk.Frame) -> None:
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text=self._L("刷新图表预览", "Refresh Preview"), command=self._refresh_preview).pack(side="left")
        ttk.Button(actions, text=self._L("打开最新 HTML", "Open Latest HTML"), command=self._open_latest_html).pack(side="left", padx=8)
        ttk.Button(actions, text=self._L("打开最新 PDF", "Open Latest PDF"), command=self._open_latest_pdf).pack(side="left")
        ttk.Label(parent, textvariable=self.preview_status_var, style="Hint.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(0, 8))

        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(canvas_frame, background="white", highlightthickness=1, highlightbackground="#d8dde3")
        yscroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.preview_canvas.yview)
        self.preview_inner = ttk.Frame(self.preview_canvas, padding=10)
        self.preview_inner.bind("<Configure>", lambda e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        self.preview_canvas.create_window((0, 0), window=self.preview_inner, anchor="nw")
        self.preview_canvas.configure(yscrollcommand=yscroll.set)
        self.preview_canvas.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self._refresh_preview()

    def _build_log(self, parent: ttk.Frame) -> None:
        text_frame = ttk.Frame(parent)
        text_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(text_frame, wrap="word", height=18, font=("Consolas", 9))
        scroll = ttk.Scrollbar(text_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _period_changed(self) -> None:
        if self.period_preset_var.get() != "custom":
            self.start_var.set("")

    def _choose_file(self, variable: tk.StringVar, filetypes) -> None:
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            variable.set(path)

    def _choose_dir(self, variable: tk.StringVar) -> None:
        path = filedialog.askdirectory()
        if path:
            variable.set(path)

    def _create_sample_batch_file(self) -> None:
        target = Path(self.out_dir_var.get().strip() or "data/weather").resolve().parent / "airport_list_example.txt"
        target.write_text("RJCC\nRJCJ\nRJTT\n", encoding="utf-8")
        self.batch_file_var.set(str(target))
        messagebox.showinfo(APP_TITLE, self._L(f"已创建示例机场列表：\n{target}", f"Example airport list created:\n{target}"))

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", "end")

    def _append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def _poll_log(self) -> None:
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _parse_common_args(self) -> dict:
        preset = self.period_preset_var.get()
        years = int(preset) if preset in {"10", "20"} else 10
        start_text = self.start_var.get().strip()
        start = parse_date(start_text) if start_text else _default_start(years)
        end = parse_date(self.end_var.get().strip() or date.today().isoformat())
        if start >= end:
            raise ValueError(self._L("开始日期必须早于结束日期。", "Start date must be earlier than end date."))
        return {
            "years": years,
            "start": start,
            "end": end,
            "source": self.source_var.get(),
            "file": self.local_file_var.get().strip() or None,
            "runways": self.runways_var.get().strip() or None,
            "cache_dir": self.cache_dir_var.get().strip() or "data/weather/cache",
            "out_dir": self.out_dir_var.get().strip() or "data/weather",
            "wind_sector": int(self.wind_sector_var.get()),
            "force": bool(self.force_var.get()),
            "no_charts": not bool(self.charts_var.get()),
            "no_html": not bool(self.html_var.get()),
            "no_pdf": not bool(self.pdf_var.get()),
            "auto_runways": bool(self.auto_runways_var.get()),
            "merge_all_sources": bool(self.merge_all_var.get()),
            "include_iem": bool(self.include_iem_var.get()),
            "fallback_coverage": 0.85,
            "compare_report": True,
        }

    def _run_single(self) -> None:
        airport = self.single_airport_var.get().strip().upper()
        if not airport:
            messagebox.showerror(APP_TITLE, self._L("请输入机场 ICAO 代码。", "Enter an airport ICAO code."))
            return
        try:
            common = self._parse_common_args()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, self._L(f"输入有问题：{exc}", f"Input error: {exc}"))
            return
        args = argparse.Namespace(command="profile", airport=airport, **common)
        self._start_worker(command_profile, args, self._L(f"单机场统计：{airport}", f"Single airport profile: {airport}"))

    def _run_compare(self) -> None:
        airports = [x.strip().upper() for x in self.compare_airports_var.get().replace(",", " ").split() if x.strip()]
        if len(airports) < 2:
            messagebox.showerror(APP_TITLE, self._L("多机场对比至少需要两个 ICAO。", "Airport comparison requires at least two ICAO codes."))
            return
        try:
            common = self._parse_common_args()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, self._L(f"输入有问题：{exc}", f"Input error: {exc}"))
            return
        args = argparse.Namespace(command="compare", airports=airports, **common)
        self._start_worker(command_compare, args, self._L("多机场对比", "Airport comparison"))

    def _run_batch(self) -> None:
        batch_file = self.batch_file_var.get().strip()
        if not batch_file:
            messagebox.showerror(APP_TITLE, self._L("请选择机场列表文件。", "Choose an airport list file."))
            return
        if not Path(batch_file).exists():
            messagebox.showerror(APP_TITLE, self._L("机场列表文件不存在。", "Airport list file does not exist."))
            return
        try:
            common = self._parse_common_args()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, self._L(f"输入有问题：{exc}", f"Input error: {exc}"))
            return
        args = argparse.Namespace(command="batch", airports_file=batch_file, **common)
        self._start_worker(command_batch, args, self._L("批量报告", "Batch reports"))

    def _set_running(self, running: bool) -> None:
        for btn in [getattr(self, "single_run_button", None), getattr(self, "compare_run_button", None), getattr(self, "batch_run_button", None)]:
            if btn:
                btn.configure(state="disabled" if running else "normal")
        if running:
            self.cancel_requested = False
            self.status_var.set(self._L("正在运行：0%", "Running: 0%"))
            self.progress.configure(mode="determinate")
            self.progress["value"] = 0
            self.cancel_button.configure(state="normal")
        else:
            self.current_process = None
            self.cancel_button.configure(state="disabled")
            if self.cancel_requested:
                self.status_var.set(self._L("已取消", "Canceled"))
            else:
                self.status_var.set(self._L("就绪", "Ready"))
            self.progress.stop()

    def _cancel_current_task(self) -> None:
        if not self.current_process or self.current_process.poll() is not None:
            return
        self.cancel_requested = True
        self.status_var.set(self._L("正在取消……", "Canceling..."))
        self.log_queue.put(self._L("\n=== 用户请求取消，正在终止后台任务 ===\n", "\n=== Cancel requested; terminating backend task ===\n"))
        try:
            self.current_process.terminate()
        except Exception as exc:
            self.log_queue.put(self._L(f"取消失败：{exc}\n", f"Cancel failed: {exc}\n"))
        self.after(2500, self._force_kill_if_needed)

    def _force_kill_if_needed(self) -> None:
        proc = self.current_process
        if proc and proc.poll() is None and self.cancel_requested:
            try:
                proc.kill()
                self.log_queue.put(self._L("后台任务已强制结束。\n", "Backend task killed.\n"))
            except Exception as exc:
                self.log_queue.put(self._L(f"强制结束失败：{exc}\n", f"Force kill failed: {exc}\n"))

    def _cli_base_cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--wxprofiler-cli"]
        return [sys.executable, "-m", "wxprofiler.cli"]

    def _common_cli_args(self, args) -> list[str]:
        out = [
            "--start", args.start.isoformat(),
            "--end", args.end.isoformat(),
            "--source", args.source,
            "--cache-dir", args.cache_dir,
            "--out-dir", args.out_dir,
            "--wind-sector", str(args.wind_sector),
            "--fallback-coverage", str(args.fallback_coverage),
        ]
        if args.file:
            out += ["--file", args.file]
        if args.runways:
            out += ["--runways", args.runways]
        if args.force:
            out.append("--force")
        if args.no_charts:
            out.append("--no-charts")
        if args.no_html:
            out.append("--no-html")
        if args.no_pdf:
            out.append("--no-pdf")
        if not args.auto_runways:
            out.append("--no-auto-runways")
        if args.merge_all_sources:
            out.append("--merge-all-sources")
        if getattr(args, "include_iem", False):
            out.append("--include-iem")
        return out

    def _build_cli_command(self, args) -> list[str]:
        cmd = self._cli_base_cmd()
        if args.command == "profile":
            return cmd + ["profile", args.airport] + self._common_cli_args(args)
        if args.command == "compare":
            return cmd + ["compare", *args.airports] + self._common_cli_args(args)
        if args.command == "batch":
            return cmd + ["batch", args.airports_file] + self._common_cli_args(args)
        raise ValueError(f"Unsupported GUI command: {args.command}")

    def _handle_progress_line(self, line: str) -> bool:
        if not line.startswith("WXPROGRESS:"):
            return False
        parts = line.strip().split(":", 2)
        if len(parts) < 3:
            return True
        try:
            pct = max(0, min(100, int(float(parts[1]))))
        except ValueError:
            pct = 0
        msg = parts[2].strip()
        def update() -> None:
            self.progress["value"] = pct
            self.status_var.set(self._L(f"正在运行：{pct}% · {msg}", f"Running: {pct}% · {self._translate_progress_message(msg)}"))
        self.after(0, update)
        return True

    def _translate_progress_message(self, msg: str) -> str:
        mapping = {
            "尝试 IEM ASOS/METAR 数据源（Polite Mode：慢速请求，429 自动退避）": "Trying IEM ASOS/METAR source (polite mode: throttled requests, 429 backoff)",
            "尝试 IEM ASOS/METAR 数据源": "Trying IEM ASOS/METAR source",
            "尝试 NOAA ISD 全球历史数据源": "Trying NOAA ISD global historical source",
            "尝试 Meteostat 备用数据源": "Trying Meteostat fallback source",
            "读取本地 CSV": "Reading local CSV",
            "合并并去重多源观测": "Merging and deduplicating observations",
            "开始统计天气分布": "Analyzing weather distributions",
            "统计 profile 已生成": "Weather profile generated",
            "写入标准化观测 CSV": "Writing normalized observation CSV",
            "写入统计表格": "Writing statistical tables",
            "生成图表": "Generating charts",
            "写入 JSON profile": "Writing JSON profile",
            "写入 Markdown 报告": "Writing Markdown report",
            "写入 HTML 报告": "Writing HTML report",
            "写入 PDF 报告": "Writing PDF report",
            "完成": "Complete",
            "批量完成": "Batch complete",
            "对比完成": "Comparison complete",
            "生成批量对比报告": "Generating batch comparison report",
        }
        for zh, en in mapping.items():
            if msg == zh:
                return en
            if msg.startswith(zh):
                return msg.replace(zh, en, 1)
        if msg.startswith("准备 ") and msg.endswith(" 配置"):
            return msg.replace("准备 ", "Preparing ").replace(" 配置", " configuration")
        if msg.startswith("批量处理 "):
            return msg.replace("批量处理 ", "Batch processing ")
        if msg.startswith("对比处理 "):
            return msg.replace("对比处理 ", "Comparison processing ")
        if "完成：" in msg and "条观测" in msg:
            return msg.replace("完成：", "complete: ").replace("条观测", "observations")
        return msg

    def _translate_label(self, label: str) -> str:
        if label.startswith("单机场统计："):
            return label.replace("单机场统计：", "Single airport profile: ")
        return {"多机场对比": "Airport comparison", "批量报告": "Batch reports"}.get(label, label)

    def _start_worker(self, target, args, label: str) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, self._L("已经有一个任务在运行。", "A task is already running."))
            return
        self.rightbook.select(self.log_tab)
        self._set_running(True)
        self.log_queue.put(self._L(f"\n=== {label} 开始：{date.today().isoformat()} ===\n", f"\n=== {self._translate_label(label)} started: {date.today().isoformat()} ===\n"))
        cmd = self._build_cli_command(args)

        def work() -> None:
            try:
                creationflags = 0
                if sys.platform.startswith("win"):
                    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                env = os.environ.copy()
                env.setdefault("PYTHONUNBUFFERED", "1")
                env.setdefault("PYTHONUTF8", "1")
                env.setdefault("PYTHONIOENCODING", "utf-8")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(Path.cwd()),
                    env=env,
                    creationflags=creationflags,
                )
                self.current_process = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    if self._handle_progress_line(line):
                        continue
                    self.log_queue.put(line)
                code = proc.wait()
                if self.cancel_requested:
                    self.log_queue.put(self._L("\n=== 已取消 ===\n", "\n=== Canceled ===\n"))
                elif code == 0:
                    self.progress["value"] = 100
                    self.status_var.set(self._L("完成：100%", "Done: 100%"))
                    self.last_result_path = Path(args.out_dir).resolve()
                    self.log_queue.put(self._L("\n=== 完成 ===\n", "\n=== Complete ===\n"))
                    self.after(0, self._refresh_preview)
                    self.after(0, lambda: self.rightbook.select(self.preview_tab))
                else:
                    self.log_queue.put(self._L(f"\n任务失败，退出码：{code}\n", f"\nTask failed, exit code: {code}\n"))
                    self.after(0, lambda: messagebox.showerror(APP_TITLE, self._L("任务失败。详细信息在运行日志里。", "Task failed. Details are in the run log.")))
            except Exception:
                tb = traceback.format_exc()
                self.log_queue.put(self._L("\n发生异常：\n", "\nException:\n"))
                self.log_queue.put(tb)
                self.after(0, lambda: messagebox.showerror(APP_TITLE, self._L("任务失败。详细信息在运行日志里。", "Task failed. Details are in the run log.")))
            finally:
                self.after(0, lambda: self._set_running(False))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _reports_root(self) -> Path:
        return Path(self.out_dir_var.get().strip() or "data/weather").resolve() / "reports"

    def _find_latest_file(self, pattern: str) -> Path | None:
        root = self._reports_root()
        if not root.exists():
            return None
        files = list(root.rglob(pattern))
        if not files:
            return None
        return max(files, key=lambda p: p.stat().st_mtime)

    def _open_latest_html(self) -> None:
        path = self._find_latest_file("*.html")
        if not path:
            messagebox.showinfo(APP_TITLE, self._L("还没有 HTML 报告。先运行一次统计。", "No HTML report yet. Run a profile first."))
            return
        webbrowser.open(path.resolve().as_uri())

    def _open_latest_pdf(self) -> None:
        path = self._find_latest_file("*.pdf")
        if not path:
            messagebox.showinfo(APP_TITLE, self._L("还没有 PDF 报告。先运行一次统计，并确认 PDF 输出已勾选。", "No PDF report yet. Run a profile first and make sure PDF output is enabled."))
            return
        self._open_path(path)

    def _refresh_preview(self) -> None:
        for child in self.preview_inner.winfo_children():
            child.destroy()
        self.preview_images.clear()
        root = self._reports_root()
        if not root.exists():
            ttk.Label(self.preview_inner, text=self._L("还没有生成任何报告。", "No reports have been generated yet."), font=("Segoe UI", 11, "bold")).pack(anchor="w")
            ttk.Label(self.preview_inner, text=self._L("在左侧输入机场代码，然后点击生成按钮。", "Enter an airport code on the left, then click Generate."), style="Hint.TLabel").pack(anchor="w", pady=(4, 0))
            self.preview_status_var.set(self._L("未发现报告目录。", "Report folder not found."))
            return
        html_path = self._find_latest_file("*.html")
        pdf_path = self._find_latest_file("*.pdf")
        pngs = sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
        head = ttk.Frame(self.preview_inner)
        head.pack(fill="x", pady=(0, 10))
        if html_path:
            ttk.Label(head, text=self._L(f"最新 HTML：{html_path.name}", f"Latest HTML: {html_path.name}"), font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Button(head, text=self._L("打开 HTML 报告", "Open HTML Report"), command=lambda p=html_path: webbrowser.open(p.resolve().as_uri())).pack(anchor="w", pady=(4, 0))
        if pdf_path:
            ttk.Button(head, text=self._L("打开 PDF 报告", "Open PDF Report"), command=lambda p=pdf_path: self._open_path(p)).pack(anchor="w", pady=(4, 0))
        if not pngs:
            ttk.Label(self.preview_inner, text=self._L("没有找到图表 PNG。确认“图表”已勾选后重新运行。", "No chart PNGs found. Make sure Charts is enabled and run again."), style="Hint.TLabel").pack(anchor="w")
            self.preview_status_var.set(self._L("没有找到图表。", "No charts found."))
            return
        self.preview_status_var.set(self._L(f"已显示最近 {len(pngs)} 张图表。", f"Showing the latest {len(pngs)} charts."))
        for path in pngs:
            card = ttk.LabelFrame(self.preview_inner, text=path.name, padding=8)
            card.pack(fill="x", pady=8)
            try:
                img = tk.PhotoImage(file=str(path))
                w, h = img.width(), img.height()
                factor = max(1, int(max(w / 500, h / 340)))
                if factor > 1:
                    img = img.subsample(factor, factor)
                self.preview_images.append(img)
                ttk.Label(card, image=img).pack(anchor="w")
                ttk.Button(card, text=self._L("打开这张图", "Open This Chart"), command=lambda p=path: self._open_path(p)).pack(anchor="w", pady=(6, 0))
            except Exception as exc:
                ttk.Label(card, text=self._L(f"无法预览：{exc}", f"Preview failed: {exc}"), style="Hint.TLabel").pack(anchor="w")

    def _open_output_folder(self) -> None:
        path = Path(self.out_dir_var.get().strip() or "data/weather").resolve()
        path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, self._L(f"无法打开：{exc}", f"Cannot open: {exc}"))


def main() -> None:
    app = WeatherProfilerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
