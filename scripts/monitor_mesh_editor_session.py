"""Watch one real Mesh Editor session from outside and write down what happened.

The app is normally run as the packaged portable build, which cannot be
instrumented from the source tree, so everything here is observed externally:
the diagnostics the app already writes, the helper processes it launches, the
preview packages it builds, and the memory both of them take.

That is enough to see the failures that matter. A single session already showed
the same asset being previewed three times in nine seconds and private bytes
going from 237 MB to 925 MB in four, neither of which is visible from reading
code.

Usage, from the repo root:

    .venv\\Scripts\\python.exe scripts\\monitor_mesh_editor_session.py --launch

It starts the portable build, follows it until it exits, then writes a report
directory and prints the path. Without --launch it attaches to a session you
start yourself, and waits for the app to appear.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - reported, not raised
    psutil = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO_ROOT / "dist"
APP_HINTS = ("crimsondesertmodworkbench",)
HELPER_HINTS = ("cdmw-mesh-dotnet-editor",)
SAMPLE_SECONDS = 1.0
# A gap longer than this between diagnostics events is worth calling out: it is
# usually the app doing something expensive without saying so.
STALL_SECONDS = 2.0


@dataclass
class Session:
    started_at: float
    dist: Path
    events: list[dict] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    helper_starts: list[dict] = field(default_factory=list)
    helper_stops: list[dict] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    interactions: list[dict] = field(default_factory=list)
    blinks: list[dict] = field(default_factory=list)
    hangs: list[dict] = field(default_factory=list)
    capture: dict = field(default_factory=dict)
    protocol: list[dict] = field(default_factory=list)

    def stamp(self, when: float | None = None) -> float:
        return round((when if when is not None else time.time()) - self.started_at, 3)


def _matches(name: str, hints: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in hints)


def _snapshot_processes(launched_pid: int | None = None) -> dict[int, dict]:
    if psutil is None:
        return {}
    found: dict[int, dict] = {}
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            name = proc.info.get("name") or ""
            # A source run is a plain python.exe, so it is recognised by pid
            # rather than by name.
            is_launched = launched_pid is not None and proc.info["pid"] == launched_pid
            if not (is_launched or _matches(name, APP_HINTS) or _matches(name, HELPER_HINTS)):
                continue
            memory = proc.info.get("memory_info")
            found[proc.info["pid"]] = {
                "pid": proc.info["pid"],
                "name": name,
                "kind": "helper"
                if (_matches(name, HELPER_HINTS) and not is_launched)
                else "app",
                "rss_mb": round(memory.rss / 1048576, 1) if memory else 0.0,
                "private_mb": round(getattr(memory, "private", 0) / 1048576, 1)
                if memory
                else 0.0,
                "cpu": proc.info.get("cpu_percent") or 0.0,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    return found


def _follow_jsonl(path: Path, offset: int) -> tuple[list[dict], int]:
    if not path.is_file():
        return [], offset
    try:
        size = path.stat().st_size
        if size < offset:  # rotated or replaced
            offset = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            text = handle.read()
            offset = handle.tell()
    except OSError:
        return [], offset
    rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, offset


def _scan_dir(root: Path, seen: set[str]) -> list[Path]:
    if not root.is_dir():
        return []
    fresh: list[Path] = []
    try:
        for entry in root.iterdir():
            key = entry.name
            if key in seen:
                continue
            try:
                # The app truncates its rolling fault log to zero bytes at
                # startup; an empty file is bookkeeping, not a report. Leaving
                # it out of `seen` means it is still announced the moment it
                # gains content.
                if entry.is_file() and entry.stat().st_size == 0:
                    continue
            except OSError:
                continue
            seen.add(key)
            fresh.append(entry)
    except OSError:
        pass
    return fresh


def _child_environment(record_input: bool) -> dict[str, str]:
    """The environment the app is launched with."""

    child_environment = dict(os.environ)
    if record_input:
        child_environment["CDMW_SESSION_RECORDER"] = "1"
        # Deliberately not inherited: the trail records that keystroke text was
        # withheld, and turning it on has to be a separate, conscious act.
        child_environment.setdefault("CDMW_SESSION_RECORDER_KEYS", "0")
    return child_environment


def _start_frame_capture(out_root: Path, session: Session, duty: float) -> object | None:
    """Watch the pixels beside everything else, in this process but off the loop.

    Capture is what tells a blank-and-repopulate apart from a genuine load, and
    neither the diagnostics trail nor the helper protocol can see the
    difference. It runs on its own thread and holds itself to a share of wall
    clock, because PrintWindow drives the application's own UI thread.
    """

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from window_frame_capture import CaptureThread  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to a session
        print(f"frame capture unavailable: {exc}")
        return None

    out = out_root / f"frame-capture-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def _announce(row: dict) -> None:
        row["_t"] = session.stamp(float(row.get("t", 0.0)) or None)
        if row.get("event") == "app_window_hung":
            # Not a blink. The capture noticed the window stopped answering,
            # which is the moment worth having on the timeline: everything else
            # in the session simply stops there.
            session.hangs.append(row)
            print(f"  [{row['_t']:>7.2f}s] !! app window stopped responding (capture paused)")
            return
        session.blinks.append(row)
        print(f"  [{row['_t']:>7.2f}s] ** blink: {row['region']} {row['tiles']} tiles, magnitude {row['magnitude']}")

    print(f"capturing frames into {out.name} (duty {duty:g})")
    return CaptureThread(out, duty_budget=duty, on_blink=_announce).start()


def monitor(
    dist: Path,
    launch: str,
    idle_timeout: float,
    *,
    capture_frames: bool = False,
    record_input: bool = False,
    capture_dir: Path | None = None,
    capture_duty: float = 0.25,
) -> Session:
    session = Session(started_at=time.time(), dist=dist)
    # A source run writes into the repo's own workspace, not the packaged one.
    workspace = (REPO_ROOT if launch == "source" else dist) / "workspace"
    logs = workspace / "logs"
    diagnostics = logs / "diagnostics_current.jsonl"
    protocol = logs / "dotnet_protocol_current.jsonl"
    interactions = logs / "session-recorder" / "ui_session_current.jsonl"
    packages = workspace / "cache" / "preview" / "models" / "dotnet_vortice" / "packages"
    print(f"watching {workspace}")

    offset = diagnostics.stat().st_size if diagnostics.is_file() else 0
    protocol_offset = 0
    interaction_offset = 0
    seen_reports = {p.name for p in logs.glob("*.log")} if logs.is_dir() else set()
    seen_packages = {p.name for p in packages.iterdir()} if packages.is_dir() else set()

    child_environment = _child_environment(record_input)

    process = None
    if launch == "packaged":
        candidates = sorted(dist.glob("*.exe"))
        if not candidates:
            raise SystemExit(f"No .exe found in {dist}")
        target = candidates[0]
        print(f"launching {target.name}")
        process = subprocess.Popen([str(target)], cwd=str(dist), env=child_environment)
    elif launch == "source":
        entry = REPO_ROOT / "cdmw_app.py"
        python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
        if not entry.is_file():
            raise SystemExit(f"No entry script at {entry}")
        print(f"launching {entry.name} from source ({python.name})")
        process = subprocess.Popen(
            [str(python if python.is_file() else sys.executable), "-u", str(entry)],
            cwd=str(REPO_ROOT),
            env=child_environment,
        )
    elif record_input:
        print("attach mode: set CDMW_SESSION_RECORDER=1 before starting the app,")
        print("             or nothing will record what you did.")

    frame_capture = None
    if capture_frames:
        frame_capture = _start_frame_capture(
            capture_dir or (REPO_ROOT / "workspace" / "evidence"), session, capture_duty
        )

    print("monitoring; close the app when you are done (Ctrl+C also stops)")
    known: dict[int, dict] = {}
    last_seen_app = time.time()
    saw_app = False

    try:
        while True:
            now = time.time()

            rows, offset = _follow_jsonl(diagnostics, offset)
            for row in rows:
                row["_t"] = session.stamp()
                session.events.append(row)
                label = row.get("event", "?")
                extra = row.get("operation") or ""
                print(f"  [{row['_t']:>7.2f}s] {label} {extra}".rstrip())

            protocol_rows, protocol_offset = _follow_jsonl(protocol, protocol_offset)
            for row in protocol_rows:
                row["_t"] = session.stamp()
                session.protocol.append(row)

            interaction_rows, interaction_offset = _follow_jsonl(interactions, interaction_offset)
            for row in interaction_rows:
                # The recorder stamps wall clock so it can be joined against a
                # capture running in another process; convert to session time.
                row["_t"] = session.stamp(float(row.get("t", 0.0)) or None)
                session.interactions.append(row)

            for report in _scan_dir(logs, seen_reports):
                if report.suffix == ".log":
                    session.reports.append(
                        {"t": session.stamp(), "name": report.name}
                    )
                    print(f"  [{session.stamp():>7.2f}s] !! crash/hang report: {report.name}")

            for package in _scan_dir(packages, seen_packages):
                session.packages.append({"t": session.stamp(), "name": package.name})
                print(f"  [{session.stamp():>7.2f}s] preview package built: {package.name[:16]}...")

            current = _snapshot_processes(process.pid if process is not None else None)
            for pid, info in current.items():
                if pid not in known:
                    known[pid] = info
                    if info["kind"] == "helper":
                        session.helper_starts.append({"t": session.stamp(), **info})
                        print(f"  [{session.stamp():>7.2f}s] helper started pid={pid}")
            for pid in list(known):
                if pid not in current:
                    info = known.pop(pid)
                    if info["kind"] == "helper":
                        session.helper_stops.append({"t": session.stamp(), **info})
                        print(f"  [{session.stamp():>7.2f}s] helper exited pid={pid}")

            if current:
                session.samples.append({"t": session.stamp(), "procs": list(current.values())})
                if any(info["kind"] == "app" for info in current.values()):
                    saw_app = True
                    last_seen_app = now

            if saw_app and not any(i["kind"] == "app" for i in current.values()):
                print("app exited")
                break
            # A source run is a plain python.exe, so it never shows up in the
            # name-matched process scan; the launched process is the signal.
            if process is not None and process.poll() is not None:
                print("app exited")
                break
            # The idle timeout only guards an attach, where nothing else says
            # whether an app is ever going to turn up. When we launched it
            # ourselves the process is the signal, above.
            if process is None and not saw_app and (now - last_seen_app) > idle_timeout:
                print(f"no app seen within {idle_timeout:.0f}s; stopping")
                break

            time.sleep(SAMPLE_SECONDS)
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        if frame_capture is not None:
            result = frame_capture.stop()
            if result is not None:
                session.capture = {
                    "frames": result.frames,
                    "dropped": result.dropped,
                    "median_capture_ms": result.median_capture_ms,
                    "effective_fps": result.effective_fps,
                    "stopped_reason": result.stopped_reason,
                }
    return session


def _describe(row: dict, stream: str) -> str:
    """One line a reader can act on, whichever stream it came from."""

    event = str(row.get("event") or row.get("operation") or "?")
    if stream == "input":
        target = str(row.get("target") or "")
        if event.endswith("_burst"):
            worst = row.get("worst") or {}
            head = ", ".join(f"{name} x{count}" for name, count in list(worst.items())[:3])
            return f"{event} total={row.get('total')} {head}"
        return f"{event} {target}".strip()
    if stream == "diagnostics":
        path = str(row.get("path") or "")
        origin = str(row.get("origin") or "")
        parts = [event]
        if path:
            parts.append(path.rsplit("/", 1)[-1])
        if origin:
            parts.append(f"origin={origin}")
        return " ".join(parts)
    return event


def _timeline(session: Session) -> list[tuple[float, str, str]]:
    merged: list[tuple[float, str, str]] = []
    for row in session.interactions:
        merged.append((float(row.get("_t", 0.0)), "input", _describe(row, "input")))
    for row in session.events:
        merged.append((float(row.get("_t", 0.0)), "app", _describe(row, "diagnostics")))
    for row in session.protocol:
        merged.append((float(row.get("_t", 0.0)), "helper", _describe(row, "protocol")))
    for row in session.blinks:
        merged.append(
            (
                float(row.get("_t", 0.0)),
                "BLINK",
                f"{row.get('region')} {row.get('tiles')} tiles, magnitude {row.get('magnitude')}",
            )
        )
    merged.sort(key=lambda item: item[0])
    return merged


def _blink_sections(session: Session, window_seconds: float = 1.5) -> list[str]:
    """What the screen did, and what happened either side of it.

    This is the section the whole capture exists for. A blink on its own says
    the interface flickered; a blink with the click that preceded it and the
    package load that followed says why.
    """

    lines: list[str] = []
    lines.append("## What you did")
    lines.append("")
    if session.interactions:
        kinds = Counter(str(row.get("event") or "?") for row in session.interactions)
        clicks = sum(count for kind, count in kinds.items() if kind.startswith("mouse"))
        lines.append(f"- {len(session.interactions)} recorded UI events, {clicks} of them mouse")
        for kind, count in kinds.most_common(12):
            lines.append(f"  - {count:>5}  {kind}")
        hidden = [row for row in session.interactions if row.get("event") == "hide"]
        if hidden:
            worst = Counter(str(row.get("target") or "?") for row in hidden)
            lines.append("")
            lines.append("- widgets that hid themselves (a pane hiding resizes everything beside it):")
            for target, count in worst.most_common(8):
                lines.append(f"  - {count:>5}  {target}")
        bursts = [row for row in session.interactions if row.get("event") == "paint_burst"]
        if bursts:
            native_paints = 0
            widget_paints = 0
            for row in bursts:
                targets = row.get("worst")
                if not isinstance(targets, dict):
                    continue
                for target, count in targets.items():
                    if str(target).startswith("QWindow#"):
                        native_paints += int(count or 0)
                    else:
                        widget_paints += int(count or 0)
            lines.append("")
            lines.append(
                f"- repaints (sampled from the busiest widgets per burst): "
                f"{widget_paints} widget, {native_paints} native-window"
            )
            if native_paints and session.capture and int(session.capture.get("frames", 0) or 0) > 0:
                lines.append(
                    "  Native-window (`QWindow#...`) repaints here are mostly this monitor's "
                    "own doing: PrintWindow(PW_RENDERFULLCONTENT) forces every native window "
                    "in the app to re-render once per captured frame, so their count tracks "
                    "the capture rate rather than the app. Judge repaint storms by the "
                    "widget repaints and the hide/show churn, not this number."
                )
    else:
        lines.append(
            "- nothing recorded. The in-app recorder is off unless "
            "`CDMW_SESSION_RECORDER=1` is set for the app process; `--record-input` "
            "sets it when this script launches the app itself."
        )
    lines.append("")

    if session.hangs:
        lines.append("## The window stopped responding")
        lines.append("")
        lines.append("Windows reported the app window hung. Everything below stops here.")
        for row in session.hangs:
            lines.append(f"- at {float(row.get('_t', 0.0)):.1f}s, after frame {row.get('frame')}")
        lines.append("")
    lines.append("## Blinks")
    lines.append("")
    if session.capture:
        capture = session.capture
        lines.append(
            f"- captured {capture.get('frames', 0)} frames at {capture.get('effective_fps', 0)} fps "
            f"({capture.get('median_capture_ms', 0)} ms each, {capture.get('dropped', 0)} dropped)"
        )
        lines.append(f"- capture ended: {capture.get('stopped_reason', '')}")
    if not session.blinks:
        lines.append("")
        lines.append(
            "- none detected."
            if session.capture
            else "- no frame capture ran; pass `--capture` to watch the pixels."
        )
        lines.append("")
        return lines
    by_region = Counter(str(row.get("region") or "?") for row in session.blinks)
    lines.append(f"- {len(session.blinks)} detected: " + ", ".join(f"{count} {region}" for region, count in by_region.most_common()))
    lines.append("")
    lines.append("A blink is a region that changed and changed back within a few frames.")
    lines.append("Content that legitimately updated never comes back, so it is not counted.")
    lines.append("")

    merged = _timeline(session)
    for blink in session.blinks[:12]:
        at = float(blink.get("_t", 0.0))
        lines.append(f"### Blink at {at:.2f}s ({blink.get('region')}, magnitude {blink.get('magnitude')})")
        lines.append("")
        lines.append(f"- bounds in the window: {blink.get('bounds')}")
        frames = blink.get("frames") or []
        if frames:
            lines.append(f"- frames: {', '.join(frames)}")
        lines.append("")
        lines.append("```")
        for when, stream, text in merged:
            if abs(when - at) > window_seconds:
                continue
            marker = ">>" if stream == "BLINK" else "  "
            lines.append(f"{marker} {when - at:+6.2f}s  {stream:<7} {text}")
        lines.append("```")
        lines.append("")
    return lines


def _summarize_events(session: Session) -> tuple[Counter, dict[str, list[float]], list[tuple]]:
    """Operation counts, repeats of one asset, and the gaps between events."""

    operations = Counter()
    repeated_paths: defaultdict[str, list[float]] = defaultdict(list)
    for row in session.events:
        op = str(row.get("operation") or row.get("event") or "?")
        operations[op] += 1
        path = str(row.get("path") or "")
        if path:
            repeated_paths[f"{op} :: {path}"].append(row["_t"])

    stalls = []
    for prev, nxt in zip(session.events, session.events[1:]):
        gap = nxt["_t"] - prev["_t"]
        if gap >= STALL_SECONDS:
            stalls.append((prev["_t"], gap, prev.get("operation") or prev.get("event")))
    return operations, repeated_paths, stalls


def _headline_lines(session: Session, stamp: str) -> list[str]:
    peak = {"app": 0.0, "helper": 0.0}
    for sample in session.samples:
        for proc in sample["procs"]:
            peak[proc["kind"]] = max(peak[proc["kind"]], proc["rss_mb"])

    lines = [f"# Mesh Editor session {stamp}", ""]
    # The span actually watched, not the last thing that spoke. Taking this from
    # the final diagnostics event reported 51.8s for a session that ran 89.9s,
    # and a reader comparing "two helper launches" against a duration that
    # stopped early concludes churn where there was none.
    watched = max(
        [float(row.get("t", 0.0)) for row in session.samples]
        + [float(row.get("_t", 0.0)) for row in session.events]
        + [0.0]
    )
    last_event = session.events[-1]["_t"] if session.events else 0.0
    lines.append(f"- duration observed: {watched:.1f}s")
    if session.events and watched - last_event > 1.0:
        lines.append(f"- last diagnostics event: {last_event:.1f}s (the app was quiet after that)")
    lines.append(f"- diagnostics events: {len(session.events)}")
    lines.append(f"- helper launches: {len(session.helper_starts)} (exits: {len(session.helper_stops)})")
    lines.append(f"- preview packages built: {len(session.packages)}")
    lines.append(f"- crash/hang reports: {len(session.reports)}")
    lines.append(f"- peak RSS: app {peak['app']:.0f} MB, helper {peak['helper']:.0f} MB")
    lines.append("")
    return lines


def write_report(session: Session, out_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_root / f"mesh-editor-session-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    (out / "trail.jsonl").write_text(
        "\n".join(json.dumps(row) for row in session.events) + "\n", encoding="utf-8"
    )
    (out / "samples.json").write_text(json.dumps(session.samples, indent=1), encoding="utf-8")

    operations, repeated_paths, stalls = _summarize_events(session)
    lines: list[str] = _headline_lines(session, stamp)
    lines.extend(_blink_sections(session))

    repeats = {k: v for k, v in repeated_paths.items() if len(v) > 1}
    lines.append("## Repeated work on the same asset")
    lines.append("")
    if repeats:
        for key, times in sorted(repeats.items(), key=lambda kv: -len(kv[1])):
            at = ", ".join(f"{t:.1f}s" for t in times)
            lines.append(f"- **{len(times)}x** {key}")
            lines.append(f"  - at {at}")
    else:
        lines.append("- none observed")
    lines.append("")

    # Who asked for each preview. Present only once the app is built with the
    # origin field; older builds simply have nothing to group.
    previews = [
        row for row in session.events if row.get("operation") == "archive_preview_request"
    ]
    origins = Counter(str(row.get("origin") or "") for row in previews)
    origins.pop("", None)
    lines.append("## Who asked for a preview rebuild")
    lines.append("")
    if origins:
        for origin, count in origins.most_common():
            lines.append(f"- **{count}x** `{origin}`")
        forced = [row for row in previews if row.get("force")]
        during_builder = [row for row in previews if row.get("builder_active")]
        lines.append("")
        lines.append(f"- forced (bypassed the builder guard): {len(forced)} of {len(previews)}")
        lines.append(f"- issued while the mesh builder was open: {len(during_builder)}")
    else:
        lines.append(
            "- not recorded; this build predates the origin field. Rebuild the "
            "portable app to capture it."
        )
    lines.append("")

    # What the resident editor itself was doing. This is the trail that shows a
    # preview reloading, because a reload is package_load/activate/presentation
    # traffic that never reaches the host's own diagnostics.
    lines.append("## Resident editor protocol traffic")
    lines.append("")
    if session.protocol:
        kinds = Counter(
            str(row.get("event") or row.get("type") or "?") for row in session.protocol
        )
        lines.append(f"- {len(session.protocol)} events")
        for kind, count in kinds.most_common(25):
            lines.append(f"  - {count:>4}  {kind}")
        reload_shaped = [
            row
            for row in session.protocol
            if str(row.get("event") or "")
            in {
                "package_load_started",
                "package_load_applied",
                "activated",
                "deactivated",
                "embedded_window_revealed",
                "ready",
            }
        ]
        if reload_shaped:
            lines.append("")
            lines.append("- reload-shaped events, in order:")
            for row in reload_shaped:
                lines.append(f"    {row['_t']:>8.2f}s  {row.get('event')}")
    else:
        lines.append(
            "- none captured; this build predates the protocol trail, or the "
            "editor was never opened."
        )
    lines.append("")

    lines.append("## Stalls (gaps between events)")
    lines.append("")
    if stalls:
        for at, gap, what in sorted(stalls, key=lambda s: -s[1])[:15]:
            lines.append(f"- {gap:.1f}s gap after `{what}` (at {at:.1f}s)")
    else:
        lines.append("- none over the threshold")
    lines.append("")

    lines.append("## Operation counts")
    lines.append("")
    for op, count in operations.most_common():
        lines.append(f"- {count:>3}  {op}")
    lines.append("")

    if session.reports:
        lines.append("## Crash / hang reports written during the session")
        lines.append("")
        for report in session.reports:
            lines.append(f"- {report['t']:.1f}s  {report['name']}")
        lines.append("")

    lines.append("## Full event trail")
    lines.append("")
    lines.append("```")
    for row in session.events:
        detail = {
            k: v
            for k, v in row.items()
            if k not in {"_t", "timestamp", "time", "pid", "session_id", "process_memory", "memory_total_private_bytes"}
        }
        lines.append(f"{row['_t']:>8.2f}s  {json.dumps(detail)}")
    lines.append("```")
    lines.append("")

    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default=str(DEFAULT_DIST))
    parser.add_argument(
        "--launch",
        nargs="?",
        const="packaged",
        choices=["packaged", "source"],
        default="",
        help="Start the app too: 'packaged' runs dist\\*.exe, 'source' runs "
        "cdmw_app.py from the repo, which picks up code changes with no rebuild.",
    )
    parser.add_argument("--idle-timeout", type=float, default=180.0)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "workspace" / "evidence"),
        help="Where the session report is written.",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Watch the window's pixels and report every region that blinked. "
        "This is the only stream that can tell a panel blanking and repopulating "
        "apart from one that genuinely loaded something.",
    )
    parser.add_argument(
        "--record-input",
        action="store_true",
        help="Record what you clicked, and which widgets repainted, hid and "
        "showed. Sets CDMW_SESSION_RECORDER for the app this script launches; "
        "keystroke text stays redacted.",
    )
    parser.add_argument(
        "--duty",
        type=float,
        default=0.25,
        help="Share of wall clock the frame capture may spend. The default keeps "
        "the app responsive but caps sampling near 5 fps, too slow to see a blink "
        "that lasts two frames. Use 0.5 for a flicker hunt.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Everything: launch from source, capture frames, record input.",
    )
    args = parser.parse_args(argv)
    if args.all:
        args.capture = True
        args.record_input = True
        args.launch = args.launch or "source"

    if psutil is None:
        print("psutil is required: .venv\\Scripts\\python.exe -m pip install psutil", file=sys.stderr)
        return 1

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"no such directory: {dist}", file=sys.stderr)
        return 1

    session = monitor(
        dist,
        args.launch,
        args.idle_timeout,
        capture_frames=bool(args.capture),
        record_input=bool(args.record_input),
        capture_dir=Path(args.out),
        capture_duty=float(args.duty),
    )
    out = write_report(session, Path(args.out))
    print()
    print(f"report written: {out / 'report.md'}")
    print("Send me that path (or paste report.md) and I will read it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
