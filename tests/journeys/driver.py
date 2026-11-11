"""Shared steps for the journeys: profiles, selection, waiting, captures.

A journey profile is a fresh folder with a copy of a base profile's settings
file (``CDMW_JOURNEY_BASE_PROFILE``), its paths moved to the new folder. The
archive catalogue index, gigabytes that only the archives change, is shared
with the base profile through a directory junction; everything else starts
empty, so every journey runs a first view from a known state.
"""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cdmw.automation.client import AutomatedApp, AutomationClient

ROOT = Path(__file__).resolve().parents[2]
BASE_PROFILE_ENV = "CDMW_JOURNEY_BASE_PROFILE"
OUTPUT_ENV = "CDMW_JOURNEY_OUTPUT"
DEFAULT_BASE_PROFILE = ROOT / ".work" / "tests" / "2026-11-11-p0-full-profile"
SETTINGS_NAME = "CrimsonDesertModWorkbench.cfg"

SWORD = "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015.pac"
SCABBARD = "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0015_in.pac"
UPPER = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_0374.pac"
WYVERN = "character/model/2_mon/cd_m0004_00_dragon/cd_m0004_00_wyvern/cd_m0004_00_wyvern_00_0001.pac"
HEAD = "character/model/1_pc/2_phw/head/head/phw_00_head_00_0045.pac"
OTHER = "character/model/1_pc/1_phm/weapon/3_shield/cd_phm_03_kiteshield_0030.pac"
HONOR_GUARD_SET = (
    UPPER,
    "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_belt_00_0001.pac",
    "character/model/1_pc/1_phm/armor/10_lowerbody/cd_phm_00_lb_00_0374.pac",
    "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_acc_00_0374.pac",
    "character/model/1_pc/1_phm/armor/14_sho/cd_phm_00_sho_under_00_0374.pac",
)
CASES = {"sword": SWORD, "upper": UPPER, "set": HONOR_GUARD_SET, "wyvern": WYVERN}


def base_profile() -> Path | None:
    text = os.environ.get(BASE_PROFILE_ENV, "").strip()
    folder = Path(text) if text else DEFAULT_BASE_PROFILE
    return folder if (folder / SETTINGS_NAME).is_file() else None


def skip_reason() -> str:
    if os.name != "nt":
        return "journeys drive the Windows app"
    if base_profile() is None:
        return (f"no game profile: set {BASE_PROFILE_ENV} to a profile folder whose "
                f"{SETTINGS_NAME} names the game folder")
    return ""


def output_root() -> Path:
    text = os.environ.get(OUTPUT_ENV, "").strip()
    root = Path(text) if text else ROOT / ".work" / "tests" / f"{time.strftime('%Y-%m-%d')}-journeys"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _escaped(path: Path) -> str:
    return str(path).replace("\\", "\\\\")


def make_profile(name: str) -> Path:
    """A fresh profile for one journey, sharing only the catalogue index."""

    base = base_profile()
    assert base is not None, skip_reason()
    profile = output_root() / f"{name}-{uuid.uuid4().hex[:8]}"
    (profile / "workspace" / "cache").mkdir(parents=True)
    text = (base / SETTINGS_NAME).read_text(encoding="utf-8")
    for old, new in ((_escaped(base.resolve()), _escaped(profile.resolve())),
                     (str(base.resolve()), str(profile.resolve())),
                     (base.resolve().as_posix(), profile.resolve().as_posix())):
        text = text.replace(old, new)
    (profile / SETTINGS_NAME).write_text(text, encoding="utf-8")
    index = base / "workspace" / "cache" / "index"
    if index.is_dir():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(profile / "workspace" / "cache" / "index"), str(index)],
                       check=True, capture_output=True)
    return profile


def remove_profile(profile: Path) -> None:
    """Remove a journey profile; the shared index junction is unlinked, never followed."""

    link = profile / "workspace" / "cache" / "index"
    if link.exists() and os.path.isjunction(link):
        os.rmdir(link)
    shutil.rmtree(profile, ignore_errors=True)


def keep_log_and_remove(profile: Path, name: str) -> None:
    log = profile / "app.log"
    if log.is_file():
        shutil.copy2(log, output_root() / f"{name}.log")
    remove_profile(profile)


@dataclass
class Run:
    """One app process under a journey profile."""

    profile: Path
    app: AutomatedApp = field(init=False)
    client: AutomationClient = field(init=False)
    process_start: float = 0.0

    def __post_init__(self) -> None:
        self.app = AutomatedApp(self.profile, log_path=self.profile / "app.log")
        self.client = self.app.connect()
        self.process_start = float(self.client.call("ping")["process_start"])

    def now(self) -> float:
        return time.time() - self.process_start

    def call(self, command: str, **args):
        return self.client.call(command, **args)

    def state(self) -> dict:
        return self.client.call("state")

    def wait_usable(self, timeout: float = 180.0) -> float:
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.state()
            if state["catalogue_ready"] and state["visible"]:
                return self.now()
            time.sleep(0.02)
        raise TimeoutError("the app never became usable")

    def select(self, target, *, timeout: float = 240.0) -> dict:
        """Select a file or a worn set and wait until its textured frame is final."""

        index = len(self.call("events"))
        clicked = self.now()
        if isinstance(target, str):
            self.call("select_entry", path=target)
        else:
            self.call("select_set", paths=list(target), label="Journey set")
        deadline = time.time() + timeout
        quiet = None
        while time.time() < deadline:
            events = self.call("events", since=index)
            failed = [e for e in events if e["event"] == "automation_set_applied" and not e.get("ok")]
            if failed:
                raise AssertionError(f"the set did not open: {failed[0]}")
            applied = [e for e in events if e["event"] == "preview:package_load_applied"]
            uploads = [e for e in events if e["event"] == "preview:texture_upload_report"]
            browse = self.state()["browse"]
            busy = browse["upgrade_pending"] or browse["texture_request_loading"] or browse["worker_busy"]
            last = applied[-1] if applied else None
            textured = [u for u in uploads if last and u.get("generation") == last.get("generation")
                        and (u.get("texture_uploads") or 0) > 0]
            settled = bool(last) and not busy and (browse["tier"] == "full" or not browse["upgrade_pending"]) and textured
            if not settled:
                quiet = None
            elif quiet is None:
                quiet = self.now()
            elif self.now() - quiet >= 1.5:
                request = next((e["t"] for e in events if e["event"] == "last_active_operation"
                                and e.get("operation") == "archive_preview_request"), clicked)
                return {"clicked_s": clicked, "request_s": request,
                        "geometry_s": applied[0]["t"] - request, "textured_s": textured[-1]["t"] - request,
                        "browse": browse}
            time.sleep(0.02)
        raise TimeoutError(f"{target} never reached its final textured frame")

    def open_mesh_editor(self, *, item_set: bool = False, timeout: float = 240.0) -> dict:
        clicked = time.time()
        self.call("open_mesh_editor", set=item_set)
        deadline = time.time() + timeout
        while time.time() < deadline:
            editor = self.state()["mesh_editor"]
            if editor and editor["ready"]:
                return {**editor, "ready_s": time.time() - clicked}
            time.sleep(0.05)
        raise TimeoutError("the Mesh Editor never became ready")

    def wait(self, predicate, *, timeout: float = 30.0, what: str = "a condition"):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        raise TimeoutError(f"timed out waiting for {what}")

    def close(self) -> int:
        return self.app.close()


def median(values) -> float:
    return float(statistics.median(values))
