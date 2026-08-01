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
            if key not in seen:
                seen.add(key)
                fresh.append(entry)
    except OSError:
        pass
    return fresh


def monitor(dist: Path, launch: str, idle_timeout: float) -> Session:
    session = Session(started_at=time.time(), dist=dist)
    # A source run writes into the repo's own workspace, not the packaged one.
    workspace = (REPO_ROOT if launch == "source" else dist) / "workspace"
    logs = workspace / "logs"
    diagnostics = logs / "diagnostics_current.jsonl"
    packages = workspace / "cache" / "preview" / "models" / "dotnet_vortice" / "packages"
    print(f"watching {workspace}")

    offset = diagnostics.stat().st_size if diagnostics.is_file() else 0
    seen_reports = {p.name for p in logs.glob("*.log")} if logs.is_dir() else set()
    seen_packages = {p.name for p in packages.iterdir()} if packages.is_dir() else set()

    process = None
    if launch == "packaged":
        candidates = sorted(dist.glob("*.exe"))
        if not candidates:
            raise SystemExit(f"No .exe found in {dist}")
        target = candidates[0]
        print(f"launching {target.name}")
        process = subprocess.Popen([str(target)], cwd=str(dist))
    elif launch == "source":
        entry = REPO_ROOT / "cdmw_app.py"
        python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
        if not entry.is_file():
            raise SystemExit(f"No entry script at {entry}")
        print(f"launching {entry.name} from source ({python.name})")
        process = subprocess.Popen(
            [str(python if python.is_file() else sys.executable), "-u", str(entry)],
            cwd=str(REPO_ROOT),
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
    return session


def write_report(session: Session, out_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_root / f"mesh-editor-session-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    (out / "trail.jsonl").write_text(
        "\n".join(json.dumps(row) for row in session.events) + "\n", encoding="utf-8"
    )
    (out / "samples.json").write_text(json.dumps(session.samples, indent=1), encoding="utf-8")

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

    peak = {"app": 0.0, "helper": 0.0}
    for sample in session.samples:
        for proc in sample["procs"]:
            peak[proc["kind"]] = max(peak[proc["kind"]], proc["rss_mb"])

    lines: list[str] = []
    lines.append(f"# Mesh Editor session {stamp}")
    lines.append("")
    duration = session.events[-1]["_t"] if session.events else 0.0
    lines.append(f"- duration observed: {duration:.1f}s")
    lines.append(f"- diagnostics events: {len(session.events)}")
    lines.append(f"- helper launches: {len(session.helper_starts)} (exits: {len(session.helper_stops)})")
    lines.append(f"- preview packages built: {len(session.packages)}")
    lines.append(f"- crash/hang reports: {len(session.reports)}")
    lines.append(f"- peak RSS: app {peak['app']:.0f} MB, helper {peak['helper']:.0f} MB")
    lines.append("")

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
    args = parser.parse_args(argv)

    if psutil is None:
        print("psutil is required: .venv\\Scripts\\python.exe -m pip install psutil", file=sys.stderr)
        return 1

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"no such directory: {dist}", file=sys.stderr)
        return 1

    session = monitor(dist, args.launch, args.idle_timeout)
    out = write_report(session, Path(args.out))
    print()
    print(f"report written: {out / 'report.md'}")
    print("Send me that path (or paste report.md) and I will read it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
