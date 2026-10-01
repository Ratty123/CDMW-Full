from __future__ import annotations

import base64
import dataclasses
import io
import json
import os
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.problem_report_service import (
    MAX_LAYOUT_ENTRIES, ProblemDetails, ProblemReportRequest, ProblemSnapshot, ReportRedactor,
    _folder_layout, _is_link, collect_problem_report, load_problem_report, parse_report_receipt,
    report_delivery_failure, validate_details,
)
from cdmw.ui.shell.menus import ShellMenusMixin
from cdmw.ui.shell.problem_report_dialog import ProblemReportDialog
from cdmw.ui.shell.profile_controller import ProfileControllerMixin
from cdmw.ui.shell.signal_wiring import ShellSignalWiringMixin
from cdmw.workers.problem_report_workers import _active_collections


def details() -> ProblemDetails:
    return ProblemDetails("Synthetic report: export failed", "Archive Browser",
        "1. Select the synthetic file. 2. Click Export.", "The file should export.",
        "A synthetic error appears instead.", "Every time", "Unknown", "Steam", "None", "Not tried")


def snapshot(root: Path) -> ProblemSnapshot:
    return ProblemSnapshot(workspace_root=str(root), captured_at=time.time())


_qt_app = None


def app() -> QApplication:
    global _qt_app
    _qt_app = QApplication.instance() or QApplication([])
    return _qt_app


def wait_until(predicate, timeout: float = 5) -> None:
    start = time.monotonic()
    while not predicate():
        assert time.monotonic() - start < timeout
        QTest.qWait(10)


def fill_form(dialog: ProblemReportDialog) -> None:
    data = details()
    for key in ("summary", "tool", "input_item", "game_version", "contact"):
        getattr(dialog, key).setText(getattr(data, key))
    for key in ("steps", "expected", "actual", "mod_setup"):
        getattr(dialog, key).setPlainText(getattr(data, key))
    for key in ("frequency", "game_platform", "clean_test", "problem_type", "last_working"):
        widget = getattr(dialog, key)
        widget.setCurrentIndex(widget.findData(getattr(data, key)))


def test_required_fields_accept_explicit_unknowns_but_reject_vague_reports():
    assert not validate_details(details())
    assert len(validate_details(dataclasses.replace(details(), steps="doesn't work", actual="broken", game_version=""))) == 3
    assert validate_details(dataclasses.replace(details(), frequency="unsure"))


def test_report_redacts_paths_credentials_and_urls_without_touching_internal_asset_paths(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Private Name")
    redactor = ReportRedactor(ProblemSnapshot(archive_root=r"D:\Games\Crimson Desert\image",
                                             workspace_root=r"C:\CDMW\workspace"))
    data = {"source": r"D:\Games\Crimson Desert\image\character.pamt",
            "slash_variant": "D:/Games/Crimson Desert/image/character.pamt",
            "asset": "character/armor/item.pac",
            "api_key": "hidden-value", "note": "Authorization: Bearer hidden-value\npassword=hidden-value",
            "unknown": r"E:\Very Private Documents\personal file.png",
            "profile": r"C:\Users\Private Name\secrets.txt", "link": "https://example.com/?token=hidden-value",
            "token_text": "github_pat_PRIVATE ghp_PRIVATE"}
    output = json.dumps(redactor.value(data))
    for private in ("Private Name", "Very Private", "hidden-value", "github_pat_PRIVATE", "ghp_PRIVATE", "https://example"):
        assert private not in output
    assert "<ARCHIVE_ROOT>" in output and "character/armor/item.pac" in output
    assert "<USER_PROFILE>" in output


def test_collection_reads_only_scoped_metadata_and_saves_exact_reviewed_draft(tmp_path):
    game = tmp_path / "Game"
    archive = game / "image"
    archive.mkdir(parents=True)
    package = archive / "character.pamt"
    package.write_bytes(b"synthetic archive; must not be uploaded")
    (game / "backups").mkdir()
    (game / "backups" / "private-secret.txt").write_text("excluded", encoding="utf-8")
    log = tmp_path / "events.jsonl"
    log.write_text(json.dumps({"timestamp":10,"event":"export","source":str(package)}) + "\n" +
                   json.dumps({"timestamp":20,"event":"future unrelated operation"}), encoding="utf-8")
    snap = dataclasses.replace(snapshot(tmp_path), archive_root=str(archive), event_log=str(log), captured_at=15,
                              context_json=json.dumps({"selected_archive_package":str(package)}),
                              live_log="token=secret-value\nError " + str(package))
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        assert path != package
        return original_open(path, *args, **kwargs)
    before = package.stat()
    with patch.object(Path,"open",guarded_open):
        result = collect_problem_report(ProblemReportRequest(details(),snap))
    payload = json.loads(result.body)
    assert result.draft_path.read_bytes() == result.body
    assert package.stat().st_mtime_ns == before.st_mtime_ns
    assert b"synthetic archive; must not be uploaded" not in result.body
    assert b"secret-value" not in result.body
    assert str(tmp_path).encode() not in result.body
    assert payload["evidence"]["selected_archive_source"]["exists"] is True
    assert payload["evidence"]["selected_archive_source"]["modified_ns"] == str(before.st_mtime_ns)
    assert len(payload["evidence"]["logs"]["runtime_events"]) == 1
    assert "private-secret.txt" not in result.preview
    assert "not a clean-install verification" in result.preview
    assert not list(result.draft_path.parent.glob("*.tmp"))


def test_layout_bounds_and_link_skipping(tmp_path, monkeypatch):
    for index in range(MAX_LAYOUT_ENTRIES + 3):
        (tmp_path / f"fixture-{index}.txt").touch()
    layout = _folder_layout(str(tmp_path), None)
    assert layout["truncated"] and layout["status"] == "partial"
    assert len(layout["entries"]) == MAX_LAYOUT_ENTRIES
    assert _is_link(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400))
    monkeypatch.setattr(Path,"lstat",lambda _path:SimpleNamespace(st_mode=stat.S_IFLNK))
    with patch("os.scandir",side_effect=AssertionError("must not traverse linked root")):
        assert _folder_layout(str(tmp_path),None)["status"] == "linked root skipped"


def test_cancelled_collection_does_not_publish_a_draft(tmp_path):
    stopped = threading.Event(); stopped.set()
    with pytest.raises(RunCancelled):
        collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path)),stop_event=stopped)
    assert not (tmp_path / "problem_reports").exists()


def test_screenshots_are_explicit_normalized_and_metadata_free(tmp_path):
    from PIL import Image, PngImagePlugin
    path = tmp_path / "private-personal-name.png"
    image = Image.new("RGB",(32,32),"blue")
    metadata = PngImagePlugin.PngInfo(); metadata.add_text("private","secret metadata")
    image.save(path,pnginfo=metadata)
    result = collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path),screenshot_paths=(str(path),)))
    shot = json.loads(result.body)["screenshots"][0]
    assert shot["name"] == "screenshot-1.jpg"
    raw = base64.b64decode(shot["data"])
    assert b"secret metadata" not in raw
    assert "private-personal-name" not in result.preview
    with Image.open(io.BytesIO(raw)) as normalized:
        assert normalized.format == "JPEG" and not normalized.getexif()
    with pytest.raises(ValueError,match="at most three"):
        collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path),screenshot_paths=(str(path),)*4))


def test_receipt_requires_matching_server_acceptance():
    good = b'{"status":"accepted","report_id":"same","issue_number":3}'
    assert parse_report_receipt(good,report_id="same").startswith("CDMW-3")
    for body in (b"invalid",b"[]",b"null",b'{"status":"pending"}',good):
        with pytest.raises(ValueError):
            parse_report_receipt(body,report_id="different")


def test_shell_snapshot_does_no_filesystem_io(tmp_path):
    class Text:
        def __init__(self, text): self.value = text
        def text(self): return self.value
        def toPlainText(self): return self.value
    owner = SimpleNamespace(settings_file_path=tmp_path / "settings.ini",
        _diagnostic_context_snapshot=lambda:{"current_tab":"Archive Browser"},
        archive=SimpleNamespace(archive_package_root_edit=Text("D:/Game/image"),archive_log_view=Text("archive")),
        textures=SimpleNamespace(log_view=Text("live")))
    with patch.object(Path,"resolve",side_effect=AssertionError("no resolve")), \
         patch.object(Path,"open",side_effect=AssertionError("no read")), \
         patch.object(Path,"stat",side_effect=AssertionError("no stat")):
        snap = ProfileControllerMixin._problem_report_snapshot(owner)
    assert snap.live_log == "live" and snap.archive_root == "D:/Game/image"
    assert "metadata cache only" in snap.context_json


def test_help_action_is_built_and_wired_to_report_handler():
    app()
    class MenuOwner(ShellMenusMixin,QMainWindow):
        def __init__(self):
            super().__init__(); self.archive=SimpleNamespace()
        def _build_support_heart_icon(self): return QIcon()
    menu = MenuOwner(); menu._build_shell_menus()
    assert menu.report_problem_action in menu.help_menu.actions()
    class Stub:
        def __getattr__(self,_name): return self
        def __call__(self,*_args,**_kwargs): return None
    class WiringOwner:
        def __init__(self): self.report_problem_action=menu.report_problem_action; self.calls=0
        def __getattr__(self,_name): return Stub()
        def show_problem_report_dialog(self): self.calls+=1
    owner = WiringOwner()
    ShellSignalWiringMixin._connect_shell_signals(owner)
    menu.report_problem_action.trigger()
    assert owner.calls == 1
    menu.close(); menu.deleteLater()


def test_dialog_requires_fields_review_and_consent_and_rejects_stale_results(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    dialog = ProblemReportDialog(snapshot(tmp_path))
    dialog._collect()
    assert "Summary" in dialog.status.text() and not dialog.send_button.isEnabled()
    fill_form(dialog); dialog._collect()
    wait_until(lambda:dialog._collection is None)
    assert dialog._reviewed is not None and not dialog.send_button.isEnabled()
    reviewed = dialog._reviewed
    dialog.consent.setChecked(True)
    assert dialog.send_button.isEnabled()
    dialog.actual.setPlainText("A different result happened instead.")
    assert dialog._reviewed is None and not dialog.send_button.isEnabled()
    dialog._collected(dialog._generation - 1,reviewed)
    assert dialog._reviewed is None
    dialog.close()


def test_close_cancels_collection_without_waiting_and_retains_the_running_worker(tmp_path,monkeypatch):
    app()
    entered = threading.Event(); release = threading.Event()
    def slow_collect(request,*,stop_event):
        entered.set(); release.wait(5)
        assert stop_event.is_set()
        return collect_problem_report(request,stop_event=stop_event)
    monkeypatch.setattr("cdmw.workers.problem_report_workers.collect_problem_report",slow_collect)
    dialog = ProblemReportDialog(snapshot(tmp_path)); fill_form(dialog); dialog._collect()
    job = dialog._collection
    try:
        wait_until(entered.is_set)
        before=time.monotonic(); dialog.close()
        assert time.monotonic() - before < 0.1
        assert job in _active_collections and job.worker.stop_event.is_set()
    finally:
        release.set(); wait_until(lambda:job not in _active_collections)
    assert not (tmp_path / "problem_reports").exists()


def test_application_shutdown_requests_nonblocking_collection_cancellation(tmp_path,monkeypatch):
    application = app()
    entered = threading.Event(); release = threading.Event()
    def slow_collect(request,*,stop_event):
        entered.set(); release.wait(5)
        assert stop_event.is_set()
        raise RunCancelled()
    monkeypatch.setattr("cdmw.workers.problem_report_workers.collect_problem_report",slow_collect)
    dialog = ProblemReportDialog(snapshot(tmp_path)); fill_form(dialog); dialog._collect()
    job = dialog._collection
    try:
        wait_until(entered.is_set)
        start=time.monotonic(); application.aboutToQuit.emit()
        assert time.monotonic() - start < 0.1 and job.worker.stop_event.is_set()
        assert job in _active_collections
    finally:
        release.set(); wait_until(lambda:job not in _active_collections); dialog.close()


def test_upload_does_not_follow_redirects_or_forward_its_access_key(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    requests = []
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            requests.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(307)
            self.send_header("Location",f"http://127.0.0.1:{self.server.server_port}/unexpected-destination")
            self.send_header("Content-Length","0"); self.end_headers()
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:dialog._reply is None)
        assert requests == ["/reports"] and not dialog._sent
        assert "not confirmed" in dialog.status.text()
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_async_upload_preserves_same_draft_on_failure_and_accepts_only_a_receipt(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    received = []
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers["Content-Length"]))
            received.append((body,self.headers.get("Authorization")))
            payload=json.loads(body)
            self.send_response(503 if len(received) == 1 else 201)
            self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"status":"accepted","report_id":payload["report_id"],"issue_number":2}).encode())
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        dialog.consent.setChecked(True); dialog._send()
        wait_until(lambda:dialog._reply is None)
        assert "not confirmed" in dialog.status.text() and not dialog._sent
        assert reviewed.draft_path.read_bytes() == reviewed.body
        dialog._send(); wait_until(lambda:dialog._reply is None)
        assert dialog._sent and "Report received: CDMW-2" in dialog.status.text()
        assert len(received) == 2 and received[0] == received[1]
        assert received[0][1] == "Bearer synthetic-key"
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_guided_questions_focus_the_missing_field_and_explain_workflow(tmp_path):
    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.problem_type.setCurrentIndex(dialog.problem_type.findData("Unexpected in-game result"))
        assert "CDMW and in the game separately" in dialog.guidance.text()
        dialog.steps.setPlainText("broken")
        dialog._next()
        assert dialog.tabs.currentIndex() == 0 and "Steps to reproduce" in dialog.status.text()
        dialog.steps.setPlainText(details().steps)
        dialog._next()
        assert dialog.tabs.currentIndex() == 1
        dialog.last_working.setCurrentIndex(dialog.last_working.findData("Worked before"))
        assert not dialog.changes.isHidden()
        dialog._collect()
        assert "Recent changes" in dialog.status.text() and dialog._collection is None
        dialog.changes.setPlainText("Not sure yet")
        dialog._collect(); wait_until(lambda:dialog._collection is None)
        assert dialog.tabs.currentIndex() == 2 and dialog._reviewed is not None
        assert "Unexpected in-game result" in dialog.preview.toPlainText()
    finally:
        dialog.close()


def test_saved_draft_reopens_exact_payload_and_rejects_edited_private_data(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    reviewed = collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path)))
    loaded = load_problem_report(str(reviewed.draft_path),snapshot(tmp_path))
    assert loaded.body == reviewed.body and loaded.report_id == reviewed.report_id
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.QFileDialog.getOpenFileName",lambda *args:(str(reviewed.draft_path),""))
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        dialog._open_draft(); wait_until(lambda:dialog._collection is None)
        assert dialog._reviewed.body == reviewed.body
        assert dialog.summary.text() == details().summary
        assert not dialog.send_button.isEnabled()
        dialog.consent.setChecked(True)
        assert dialog.send_button.isEnabled()
    finally:
        dialog.close()
    payload=json.loads(reviewed.body)
    payload["evidence"]["private"] = r"C:\Users\Private Person\secret.txt"
    reviewed.draft_path.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(ValueError,match="unchanged"):
        load_problem_report(str(reviewed.draft_path),snapshot(tmp_path))
    payload=json.loads(reviewed.body); payload["unexpected_secret"]="private-value"
    reviewed.draft_path.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(ValueError,match="unchanged"):
        load_problem_report(str(reviewed.draft_path),snapshot(tmp_path))


def test_controller_reuses_report_dialog_and_releases_it_on_close(tmp_path):
    app()
    class Owner(QMainWindow,ProfileControllerMixin):
        def _problem_report_snapshot(self): return snapshot(tmp_path)
    owner=Owner()
    try:
        owner.show_problem_report_dialog()
        first=owner._problem_report_dialog
        owner.show_problem_report_dialog()
        assert owner._problem_report_dialog is first and first.isVisible()
        first.close(); QTest.qWait(10)
        assert owner._problem_report_dialog is None
        owner.show_problem_report_dialog()
        assert owner._problem_report_dialog is not first
        owner._problem_report_dialog.close(); QTest.qWait(10)
    finally:
        owner.close()


def test_report_failure_guidance_requires_matched_duplicate_and_bounds_countdown():
    duplicate={"code":"already_reported","report_id":"current","issue_number":3}
    failure=report_delivery_failure(json.dumps(duplicate).encode(),409,report_id="current")
    assert failure.duplicate_receipt == "CDMW-3" and "was not sent" in failure.message
    assert not report_delivery_failure(json.dumps(duplicate).encode(),409,report_id="different").duplicate_receipt
    assert report_delivery_failure(b"[]",429,"999999999").retry_seconds == 86400
    assert report_delivery_failure(b"bad",202,"bad").retry_seconds == 120
    assert "expired" in report_delivery_failure(b"{}",401).message


def test_saved_screenshots_preserve_reviewed_image_and_cannot_hide_extra_data(tmp_path):
    from PIL import Image
    shot=tmp_path / "screen.png"; Image.new("RGB",(60,30)).save(shot)
    reviewed=collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path),screenshot_paths=(str(shot),)))
    assert load_problem_report(str(reviewed.draft_path),snapshot(tmp_path)).body == reviewed.body
    data=json.loads(reviewed.body); data["screenshots"][0]["private_file"]=r"C:\Users\Private\notes.txt"
    reviewed.draft_path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError,match="unchanged"):
        load_problem_report(str(reviewed.draft_path),snapshot(tmp_path))


def test_server_cooldown_blocks_repeated_send_and_retries_the_same_draft(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    received=[]
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers["Content-Length"])); received.append(body)
            self.send_response(429 if len(received)==1 else 201)
            self.send_header("Content-Type","application/json")
            self.send_header("Retry-After","1"); self.end_headers()
            payload={"code":"report_limit","retry_after":1} if len(received)==1 else {
                "status":"accepted","report_id":json.loads(body)["report_id"],"issue_number":4}
            self.wfile.write(json.dumps(payload).encode())
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:dialog._reply is None)
        assert not dialog.send_button.isEnabled() and "Retry in" in dialog.send_button.text()
        dialog._send(); assert len(received)==1
        wait_until(dialog.send_button.isEnabled,3)
        dialog._send(); wait_until(lambda:dialog._reply is None)
        assert dialog._sent and received[0] == received[1]
        dialog.copy_receipt_button.click()
        assert "CDMW-4" in QApplication.clipboard().text()
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)
