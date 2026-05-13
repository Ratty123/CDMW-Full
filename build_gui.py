from __future__ import annotations

import argparse
import os
import queue
import re
import subprocess
import sys
import threading
import textwrap
from dataclasses import dataclass
from pathlib import Path
from tkinter import END, DISABLED, NORMAL, BooleanVar, StringVar, Tk, messagebox
import tkinter as tk


ROOT = Path(__file__).resolve().parent
APP_NAME = "CrimsonDesertModWorkbench"

COLORS = {
    "bg": "#050808",
    "panel": "#081010",
    "panel_alt": "#0c1514",
    "void": "#020404",
    "line": "#28433d",
    "line_hot": "#78ff9e",
    "text": "#d7ffe6",
    "muted": "#789089",
    "green": "#61ff92",
    "green_dim": "#173b27",
    "cyan": "#93fff6",
    "red": "#ff4d6d",
    "amber": "#ffe08a",
    "disabled": "#27302c",
}

FONT_TITLE = ("Consolas", 21, "bold")
FONT_HEAD = ("Consolas", 10, "bold")
FONT_BODY = ("Consolas", 10)
FONT_SMALL = ("Consolas", 8)
FONT_LOG = ("Consolas", 9)

MODES = {
    "onefile": {
        "title": "ONEFILE",
        "subtitle": "EXE",
        "description": "Single EXE for sharing. Slower build and first launch.",
    },
    "onedir": {
        "title": "ONEDIR",
        "subtitle": "DIR",
        "description": "Loose app folder for testing. Faster build and launch.",
    },
}

PROFILES = {
    "release": {
        "title": "RELEASE",
        "subtitle": "PUB",
        "description": "Clean, windowed, validated publishing build.",
    },
    "fast": {
        "title": "FAST",
        "subtitle": "RUN",
        "description": "Incremental cache reuse for quick local iteration.",
    },
    "debug": {
        "title": "DEBUG",
        "subtitle": "LOG",
        "description": "Clean console build with verbose PyInstaller logs.",
    },
}

PROGRESS_MARKERS = (
    (re.compile(r"Build selection:"), 3),
    (re.compile(r"Building .* in .* mode", re.IGNORECASE), 8),
    (re.compile(r"Running Analysis|Analyzing .*cdmw_app\.py", re.IGNORECASE), 18),
    (re.compile(r"Processing standard module hook 'hook-PySide6\.QtCore", re.IGNORECASE), 32),
    (re.compile(r"Processing standard module hook 'hook-PySide6\.QtGui", re.IGNORECASE), 44),
    (re.compile(r"Processing standard module hook 'hook-PySide6\.QtWidgets", re.IGNORECASE), 56),
    (re.compile(r"Processing standard module hook 'hook-cv2", re.IGNORECASE), 64),
    (re.compile(r"Performing binary vs\. data reclassification", re.IGNORECASE), 70),
    (re.compile(r"Building PYZ", re.IGNORECASE), 76),
    (re.compile(r"Building PKG", re.IGNORECASE), 84),
    (re.compile(r"Building EXE", re.IGNORECASE), 91),
    (re.compile(r"Building COLLECT", re.IGNORECASE), 95),
    (re.compile(r"Validated all .* archive members", re.IGNORECASE), 98),
    (re.compile(r"Build complete\.", re.IGNORECASE), 100),
)


@dataclass(frozen=True)
class BuildSelection:
    mode: str
    profile: str

    @property
    def label(self) -> str:
        return f"{MODES[self.mode]['title']} / {PROFILES[self.profile]['title']}"


def get_python_executable() -> Path | str:
    local_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if local_python.exists():
        return local_python
    return sys.executable


def get_app_version() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from cdmw.constants import APP_VERSION

        return str(APP_VERSION)
    except Exception:
        return "unknown-version"
    finally:
        try:
            sys.path.remove(str(ROOT))
        except ValueError:
            pass


def expected_output_path(selection: BuildSelection) -> Path:
    version = get_app_version()
    if selection.profile == "release":
        onefile_name = f"{APP_NAME}-{version}-windows-portable.exe"
        onedir_name = f"{APP_NAME}-{version}-windows"
    else:
        onefile_name = f"{APP_NAME}-{version}-{selection.profile}-windows-portable.exe"
        onedir_name = f"{APP_NAME}-{version}-{selection.profile}-windows"
    return ROOT / "dist" / (onefile_name if selection.mode == "onefile" else onedir_name)


def display_output_path(selection: BuildSelection) -> str:
    path = expected_output_path(selection)
    try:
        display = str(path.relative_to(ROOT))
    except ValueError:
        display = str(path)
    return "OUTPUT\n" + textwrap.fill(display, width=42, break_long_words=True, break_on_hyphens=True)


def build_command(selection: BuildSelection) -> list[str]:
    return [
        "powershell",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "build_pyside6_app.ps1"),
        "-Mode",
        selection.mode,
        "-BuildProfile",
        selection.profile,
    ]


def progress_from_line(current: int, line: str) -> int:
    for pattern, value in PROGRESS_MARKERS:
        if pattern.search(line):
            return max(current, value)

    validation_match = re.search(r"Validated\s+(\d+)/(\d+)", line)
    if validation_match:
        done = int(validation_match.group(1))
        total = max(1, int(validation_match.group(2)))
        return max(current, min(99, 96 + int((done / total) * 3)))

    if "Processing standard module hook" in line:
        return min(68, current + 1)
    return current


class PixelChoice(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        subtitle: str,
        description: str,
        command,
        compact: bool = False,
    ) -> None:
        super().__init__(
            master,
            bg=COLORS["panel_alt"],
            highlightthickness=2,
            highlightbackground=COLORS["line"],
            bd=0,
        )
        self.command = command
        self.selected = False
        self.disabled = False
        self.compact = compact

        self.marker = tk.Canvas(self, width=18, height=18, bg=COLORS["panel_alt"], highlightthickness=0, bd=0)
        self.marker.grid(
            row=0,
            column=0,
            rowspan=1 if compact else 2,
            sticky="n",
            padx=(10, 8),
            pady=(8, 8 if compact else 0),
        )

        self.title_label = tk.Label(
            self,
            text=title,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=FONT_HEAD,
            anchor="w",
        )
        self.title_label.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 10),
            pady=(8, 8) if compact else (8, 0),
        )

        self.subtitle_label = tk.Label(
            self,
            text=subtitle,
            bg=COLORS["panel_alt"],
            fg=COLORS["cyan"],
            font=FONT_SMALL,
            anchor="w",
        )
        if compact:
            if subtitle:
                self.subtitle_label.grid(row=0, column=2, sticky="e", padx=(0, 10), pady=(8, 8))
            else:
                self.title_label.grid_configure(columnspan=2)
        else:
            self.subtitle_label.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 5))

        if not compact:
            self.description_label = tk.Label(
                self,
                text=description,
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=FONT_SMALL,
                anchor="w",
                justify="left",
                wraplength=255,
            )
            self.description_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        else:
            self.description_label = None

        self.columnconfigure(1, weight=1)
        if compact:
            self.columnconfigure(2, weight=0)
        self._bind_clicks(self)
        self.render(False)

    def _bind_clicks(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._clicked)
        widget.bind("<Enter>", lambda _event: self._hover(True))
        widget.bind("<Leave>", lambda _event: self._hover(False))
        for child in widget.winfo_children():
            self._bind_clicks(child)

    def _clicked(self, _event: tk.Event) -> None:
        if not self.disabled:
            self.command()

    def _hover(self, active: bool) -> None:
        if self.disabled or self.selected:
            return
        self.configure(highlightbackground=COLORS["cyan"] if active else COLORS["line"])

    def set_disabled(self, disabled: bool) -> None:
        self.disabled = disabled
        self.render(self.selected)

    def render(self, selected: bool) -> None:
        self.selected = selected
        border = COLORS["line_hot"] if selected else COLORS["line"]
        bg = "#0d1d17" if selected else COLORS["panel_alt"]
        fg = COLORS["green"] if selected else COLORS["text"]
        if self.disabled and not selected:
            fg = COLORS["disabled"]

        self.configure(bg=bg, highlightbackground=border)
        for widget in (self.marker, self.title_label, self.subtitle_label, self.description_label):
            if widget is not None:
                widget.configure(bg=bg)
        self.title_label.configure(fg=fg)
        self.subtitle_label.configure(fg=COLORS["cyan"] if selected else COLORS["muted"])
        if self.description_label is not None:
            self.description_label.configure(fg=COLORS["text"] if selected else COLORS["muted"])

        self.marker.delete("all")
        self.marker.configure(bg=bg)
        self.marker.create_rectangle(2, 2, 15, 15, outline=border, fill=COLORS["void"], width=2)
        if selected:
            self.marker.create_rectangle(5, 5, 12, 12, outline="", fill=COLORS["green"])
            self.marker.create_rectangle(8, 2, 15, 5, outline="", fill=COLORS["cyan"])


class PixelProgress(tk.Canvas):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, height=38, bg=COLORS["panel"], highlightthickness=0, bd=0)
        self.value = 0
        self.running = False
        self.phase = 0
        self.bind("<Configure>", lambda _event: self.draw())

    def set(self, value: int, *, running: bool | None = None) -> None:
        self.value = max(0, min(100, int(value)))
        if running is not None:
            self.running = running
        self.draw()

    def tick(self) -> None:
        if self.running:
            self.phase = (self.phase + 1) % 240
            self.draw()

    def draw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        x0, y0 = 3, 9
        x1, y1 = width - 3, height - 7
        track_width = max(1, x1 - x0)
        fill_width = int(track_width * (self.value / 100))

        self.create_rectangle(x0, y0, x1, y1, outline=COLORS["line"], fill=COLORS["void"], width=2)
        if fill_width > 0:
            self.create_rectangle(x0 + 2, y0 + 2, x0 + fill_width, y1 - 2, outline="", fill=COLORS["green_dim"])
            block = 10
            for x in range(x0 + 4, x0 + fill_width, block):
                shade = COLORS["green"] if ((x // block) + self.phase) % 3 else COLORS["cyan"]
                self.create_rectangle(x, y0 + 5, min(x + 6, x0 + fill_width), y1 - 5, outline="", fill=shade)

        if self.running:
            usable = max(16, track_width - 20)
            runner_x = x0 + 10 + int(((self.phase * 7) % usable))
            for offset, color in ((-18, "#143328"), (-11, "#1f6840"), (-5, COLORS["green"]), (2, COLORS["cyan"])):
                left = runner_x + offset
                if x0 + 4 <= left <= x1 - 10:
                    self.create_rectangle(left, y0 - 5, left + 8, y0 - 1, outline="", fill=color)
            self.create_polygon(
                runner_x,
                y1 + 2,
                runner_x + 8,
                y1 + 2,
                runner_x + 4,
                y1 + 7,
                outline="",
                fill=COLORS["amber"],
            )
        elif self.value >= 100:
            self.create_text(width - 10, y0 - 3, text="OK", fill=COLORS["green"], font=FONT_SMALL, anchor="ne")


class BuilderGui:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Crimson Builder")
        self.root.geometry("1080x640")
        self.root.minsize(960, 600)
        self.root.configure(bg=COLORS["bg"])
        self._set_window_icon()

        self.mode = StringVar(value="onefile")
        self.profile = StringVar(value="release")
        self.status = StringVar(value="READY")
        self.output_path = StringVar(value="")
        self.running = BooleanVar(value=False)

        self._queue: queue.Queue[tuple[str, str | int]] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._progress = 0
        self._mode_cards: dict[str, PixelChoice] = {}
        self._profile_cards: dict[str, PixelChoice] = {}

        self._build_layout()
        self._refresh_summary()
        self.root.after(70, self._animate)
        self.root.after(80, self._drain_queue)

    def _set_window_icon(self) -> None:
        ico = ROOT / "assets" / "cdmw.ico"
        png = ROOT / "assets" / "cdmw.png"
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except tk.TclError:
                pass
        if png.exists():
            try:
                image = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, image)
                self.root._crimson_icon = image
            except tk.TclError:
                pass

    def _pixel_logo(self, master: tk.Misc) -> tk.Canvas:
        canvas = tk.Canvas(master, width=46, height=42, bg=COLORS["bg"], highlightthickness=0, bd=0)
        pixels = (
            (1, 2, COLORS["red"]),
            (2, 1, COLORS["red"]),
            (2, 2, COLORS["red"]),
            (2, 3, COLORS["amber"]),
            (3, 1, COLORS["red"]),
            (3, 2, COLORS["amber"]),
            (3, 3, COLORS["green"]),
            (4, 2, COLORS["green"]),
            (4, 3, COLORS["cyan"]),
            (5, 3, COLORS["cyan"]),
        )
        size = 6
        for x, y, color in pixels:
            canvas.create_rectangle(x * size, y * size, x * size + size - 1, y * size + size - 1, outline="", fill=color)
        canvas.create_rectangle(5, 6, 40, 34, outline=COLORS["line"], width=2)
        return canvas

    def _build_layout(self) -> None:
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True, padx=18, pady=10)

        header = tk.Frame(shell, bg=COLORS["bg"])
        header.pack(fill="x", pady=(0, 10))
        self._pixel_logo(header).pack(side="left", padx=(0, 12))

        title_block = tk.Frame(header, bg=COLORS["bg"])
        title_block.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_block,
            text="CRIMSON BUILDER",
            bg=COLORS["bg"],
            fg=COLORS["green"],
            font=FONT_TITLE,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="PyInstaller build deck // choose target, profile, launch",
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self.status_chip = tk.Label(
            header,
            textvariable=self.status,
            bg=COLORS["void"],
            fg=COLORS["cyan"],
            font=FONT_HEAD,
            padx=14,
            pady=8,
            highlightthickness=2,
            highlightbackground=COLORS["line"],
        )
        self.status_chip.pack(side="right", anchor="n")

        body = tk.Frame(shell, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=390)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        controls = self._panel(body)
        controls.configure(width=390)
        controls.grid_propagate(False)
        controls.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(4, weight=1)

        self._section_label(controls, "PACKAGE").grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        modes_frame = tk.Frame(controls, bg=COLORS["panel"])
        modes_frame.grid(row=1, column=0, sticky="ew", padx=14)
        modes_frame.columnconfigure(0, weight=1)
        modes_frame.columnconfigure(1, weight=1)
        for index, (key, data) in enumerate(MODES.items()):
            card = PixelChoice(
                modes_frame,
                title=data["title"],
                subtitle=data["subtitle"],
                description=data["description"],
                command=lambda key=key: self._set_mode(key),
                compact=True,
            )
            card.grid(row=0, column=index, sticky="ew", padx=(0, 6) if index == 0 else (6, 0))
            self._mode_cards[key] = card

        self._section_label(controls, "PROFILE").grid(row=2, column=0, sticky="ew", padx=16, pady=(14, 6))
        profile_frame = tk.Frame(controls, bg=COLORS["panel"])
        profile_frame.grid(row=3, column=0, sticky="ew", padx=14)
        for index in range(3):
            profile_frame.columnconfigure(index, weight=1)
        for index, (key, data) in enumerate(PROFILES.items()):
            card = PixelChoice(
                profile_frame,
                title=data["title"],
                subtitle="",
                description="",
                command=lambda key=key: self._set_profile(key),
                compact=True,
            )
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0 if index == 2 else 4))
            self._profile_cards[key] = card

        summary_frame = tk.Frame(controls, bg=COLORS["panel"], highlightthickness=2, highlightbackground=COLORS["line"])
        summary_frame.grid(row=4, column=0, sticky="nsew", padx=14, pady=(14, 10))
        summary_frame.columnconfigure(0, weight=1)
        self.summary_title = tk.Label(
            summary_frame,
            text="",
            bg=COLORS["panel"],
            fg=COLORS["green"],
            font=FONT_HEAD,
            anchor="w",
        )
        self.summary_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.summary = tk.Label(
            summary_frame,
            text="",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=FONT_SMALL,
            anchor="nw",
            justify="left",
            wraplength=350,
        )
        self.summary.grid(row=1, column=0, sticky="ew", padx=12, pady=(7, 0))
        self.path_label = tk.Label(
            summary_frame,
            textvariable=self.output_path,
            bg=COLORS["panel"],
            fg=COLORS["cyan"],
            font=FONT_SMALL,
            anchor="nw",
            justify="left",
            wraplength=350,
        )
        self.path_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 10))

        action_frame = tk.Frame(controls, bg=COLORS["panel"])
        action_frame.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 12))
        action_frame.columnconfigure(0, weight=1)
        self.build_button = tk.Button(
            action_frame,
            text="BUILD",
            command=self.start_build,
            bg=COLORS["green"],
            fg=COLORS["void"],
            activebackground=COLORS["cyan"],
            activeforeground=COLORS["void"],
            disabledforeground=COLORS["disabled"],
            font=FONT_HEAD,
            relief="flat",
            bd=0,
            padx=18,
            pady=11,
            cursor="hand2",
        )
        self.build_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.cancel_button = tk.Button(
            action_frame,
            text="STOP",
            command=self.cancel_build,
            bg=COLORS["void"],
            fg=COLORS["red"],
            activebackground="#221015",
            activeforeground=COLORS["red"],
            disabledforeground=COLORS["disabled"],
            font=FONT_HEAD,
            relief="flat",
            bd=0,
            padx=18,
            pady=11,
            cursor="hand2",
            state=DISABLED,
            highlightthickness=2,
            highlightbackground=COLORS["line"],
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew")

        terminal = self._panel(body)
        terminal.grid(row=0, column=1, sticky="nsew")
        terminal.columnconfigure(0, weight=1)
        terminal.rowconfigure(3, weight=1)

        top_line = tk.Frame(terminal, bg=COLORS["panel"])
        top_line.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        tk.Label(
            top_line,
            text="BUILD STREAM",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=FONT_HEAD,
            anchor="w",
        ).pack(side="left")
        self.percent_label = tk.Label(
            top_line,
            text="0%",
            bg=COLORS["panel"],
            fg=COLORS["green"],
            font=FONT_HEAD,
            anchor="e",
        )
        self.percent_label.pack(side="right")

        self.progress = PixelProgress(terminal)
        self.progress.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 7))
        self.stage_label = tk.Label(
            terminal,
            text="STANDBY",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=FONT_SMALL,
            anchor="w",
        )
        self.stage_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))

        log_frame = tk.Frame(terminal, bg=COLORS["void"], highlightthickness=2, highlightbackground=COLORS["line"])
        log_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 14))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame,
            bg=COLORS["void"],
            fg="#9cffb8",
            insertbackground=COLORS["green"],
            selectbackground="#164b2b",
            relief="flat",
            borderwidth=0,
            font=FONT_LOG,
            wrap="word",
            padx=10,
            pady=10,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        self.log.tag_configure("prompt", foreground=COLORS["cyan"])
        self.log.tag_configure("error", foreground=COLORS["red"])
        self.log.tag_configure("done", foreground=COLORS["green"])
        self._append_log("> builder online\n> waiting for target selection\n\n", "prompt")

    def _panel(self, master: tk.Misc) -> tk.Frame:
        return tk.Frame(
            master,
            bg=COLORS["panel"],
            highlightthickness=2,
            highlightbackground=COLORS["line"],
            bd=0,
        )

    def _section_label(self, master: tk.Misc, text: str) -> tk.Label:
        return tk.Label(master, text=f"// {text}", bg=COLORS["panel"], fg=COLORS["cyan"], font=FONT_HEAD, anchor="w")

    def _selection(self) -> BuildSelection:
        return BuildSelection(self.mode.get(), self.profile.get())

    def _set_mode(self, mode: str) -> None:
        if self.running.get():
            return
        self.mode.set(mode)
        self._refresh_summary()

    def _set_profile(self, profile: str) -> None:
        if self.running.get():
            return
        self.profile.set(profile)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        selection = self._selection()
        mode = MODES[selection.mode]
        profile = PROFILES[selection.profile]

        for key, card in self._mode_cards.items():
            card.render(key == selection.mode)
            card.set_disabled(self.running.get())
        for key, card in self._profile_cards.items():
            card.render(key == selection.profile)
            card.set_disabled(self.running.get())

        self.summary_title.configure(text=selection.label)
        self.summary.configure(text=f"{mode['description']}\n{profile['description']}")
        self.output_path.set(display_output_path(selection))

    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state=NORMAL)
        self.log.insert(END, text, tag)
        self.log.see(END)
        self.log.configure(state=DISABLED)

    def start_build(self) -> None:
        if self.running.get():
            return
        selection = self._selection()
        self.running.set(True)
        self.build_button.configure(state=DISABLED, bg="#122018")
        self.cancel_button.configure(state=NORMAL)
        self._refresh_summary()
        self._set_progress(0)
        self.status.set(f"RUNNING :: {selection.label}")
        self.stage_label.configure(text="SPAWNING POWERSHELL BUILD PROCESS", fg=COLORS["amber"])
        self.progress.set(0, running=True)
        self._append_log(f"\n> launch {selection.mode}/{selection.profile}\n", "prompt")

        worker = threading.Thread(target=self._run_build, args=(selection,), daemon=True)
        worker.start()

    def cancel_build(self) -> None:
        if self._process and self._process.poll() is None:
            self._append_log("\n> stop requested\n", "error")
            self._process.terminate()
            self.status.set("STOPPING")
            self.stage_label.configure(text="STOP REQUESTED", fg=COLORS["red"])

    def _run_build(self, selection: BuildSelection) -> None:
        command = build_command(selection)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            assert self._process.stdout is not None
            for line in self._process.stdout:
                self._queue.put(("line", line))
            return_code = self._process.wait()
            self._queue.put(("done", return_code))
        except Exception as exc:
            self._queue.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            self._process = None

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "line":
                    line = str(payload)
                    self._append_log(line)
                    next_progress = progress_from_line(self._progress, line)
                    self._set_progress(next_progress)
                    self._update_stage(line, next_progress)
                elif kind == "done":
                    return_code = int(payload)
                    if return_code == 0:
                        self._set_progress(100)
                        self.status.set("DONE")
                        self.stage_label.configure(text="BUILD COMPLETE", fg=COLORS["green"])
                        self._append_log("> build finished successfully\n", "done")
                    else:
                        self.status.set(f"FAILED :: exit {return_code}")
                        self.stage_label.configure(text=f"BUILD FAILED :: EXIT {return_code}", fg=COLORS["red"])
                        self._append_log(f"> build failed with exit code {return_code}\n", "error")
                    self._finish_build()
                elif kind == "error":
                    self.status.set("FAILED")
                    self.stage_label.configure(text="BUILDER ERROR", fg=COLORS["red"])
                    self._append_log(f"> {payload}\n", "error")
                    self._finish_build()
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _update_stage(self, line: str, progress: int) -> None:
        lower = line.lower()
        stage = None
        if "running analysis" in lower or "analyzing" in lower:
            stage = "ANALYZING PYTHON IMPORT GRAPH"
        elif "processing standard module hook" in lower:
            stage = "COLLECTING PYINSTALLER HOOKS"
        elif "looking for dynamic libraries" in lower:
            stage = "SCANNING DYNAMIC LIBRARIES"
        elif "building pyz" in lower:
            stage = "PACKING PYTHON ARCHIVE"
        elif "building pkg" in lower:
            stage = "PACKING ONEFILE PAYLOAD"
        elif "building exe" in lower:
            stage = "WRITING WINDOWS EXECUTABLE"
        elif "building collect" in lower:
            stage = "ASSEMBLING ONEDIR FOLDER"
        elif "validated" in lower:
            stage = "VALIDATING EMBEDDED ARCHIVE"
        elif progress > 0:
            stage = "BUILDING"
        if stage:
            self.stage_label.configure(text=stage, fg=COLORS["amber"] if self.running.get() else COLORS["muted"])

    def _set_progress(self, value: int) -> None:
        value = max(0, min(100, value))
        if value < self._progress:
            return
        self._progress = value
        self.percent_label.configure(text=f"{value}%")
        self.progress.set(value, running=self.running.get())

    def _finish_build(self) -> None:
        self.running.set(False)
        self.progress.set(self._progress, running=False)
        self.build_button.configure(state=NORMAL, bg=COLORS["green"])
        self.cancel_button.configure(state=DISABLED)
        self._refresh_summary()

    def _animate(self) -> None:
        self.progress.tick()
        self.root.after(70, self._animate)

    def on_close(self) -> None:
        if self.running.get():
            if not messagebox.askyesno("Build running", "Stop the current build and close?"):
                return
            self.cancel_build()
        self.root.destroy()


def run_gui() -> int:
    root = Tk()
    app = BuilderGui(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0


def self_test() -> int:
    checks = [
        ROOT.exists(),
        (ROOT / "build_pyside6_app.ps1").exists(),
        build_command(BuildSelection("onedir", "fast"))[-4:] == ["-Mode", "onedir", "-BuildProfile", "fast"],
        expected_output_path(BuildSelection("onefile", "release")).name.endswith("windows-portable.exe"),
        progress_from_line(0, "Building EXE from EXE-00.toc") >= 90,
    ]
    if not all(checks):
        print("builder GUI self-test failed", file=sys.stderr)
        return 1
    print("builder GUI self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crimson Desert Mod Workbench build GUI")
    parser.add_argument("--self-test", action="store_true", help="run non-GUI checks and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
