from __future__ import annotations

import base64
import dataclasses
import io
import hashlib
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

from PySide6.QtCore import QPoint, QSignalBlocker, QUrl, Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QMainWindow, QStyle, QStyleFactory, QStyleOptionComboBox, QToolTip,
)

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.problem_report_service import (
    MAX_LAYOUT_ENTRIES, ProblemDetails, ProblemReportRequest, ProblemSnapshot, ReportRedactor,
    _folder_layout, _is_link, collect_problem_report, load_problem_report, parse_report_receipt,
    report_delivery_failure, validate_details,
    parse_report_verification, parse_report_verification_status, report_verification_request,
)
from cdmw.ui.shell.menus import ShellMenusMixin
from cdmw.ui.shell.problem_report_dialog import ProblemReportDialog
from cdmw.ui.shell.problem_report_catalog import (
    REPORT_TOOLS, decode_tool, encode_tool, report_tool, tool_actions,
)
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


@pytest.fixture(autouse=True)
def keep_verification_browsers_in_tests(monkeypatch):
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.QDesktopServices.openUrl", lambda url: True)


class VerifiedReportReceiver(BaseHTTPRequestHandler):
    """Real Qt HTTP handoff; the human check is simulated only by this local server."""

    def handle_verification_start(self):
        if self.path != "/verification/start":
            return False
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.verification = data
        ticket = data["report_id"] + ".synthetic_signature"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "verification_required", "report_id": data["report_id"],
            "ticket": ticket, "verification_url": f"http://127.0.0.1:{self.server.server_port}/verify#{ticket}",
            "expires_in": 600}).encode())
        return True

    def do_GET(self):
        assert self.path == "/verification/status"
        data = self.server.verification
        assert self.headers["Authorization"] == "Bearer " + data["report_id"] + ".synthetic_signature"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "pending" if getattr(self.server,"verification_pending",False) else "verified",
            "report_id": data["report_id"]}).encode())


def fill_form(dialog: ProblemReportDialog) -> None:
    data = details()
    spec, action, other = decode_tool(data.tool)
    dialog.tool.setCurrentIndex(dialog.tool.findData(spec.key))
    dialog.workflow.setCurrentIndex(dialog.workflow.findData(action or "Extract files"))
    dialog.other_tool.setText(other)
    dialog.input_source.setCurrentIndex(dialog.input_source.findData("DDS texture"))
    for key in ("summary", "game_version", "contact"):
        getattr(dialog, key).setText(getattr(data, key))
    dialog.input_item.setText("character/synthetic.dds")
    dialog.mod_state.setCurrentIndex(dialog.mod_state.findData("No mods installed"))
    for key in ("steps", "expected", "actual", "mod_setup"):
        getattr(dialog, key).setPlainText(getattr(data, key))
    for key in ("frequency", "game_platform", "problem_type", "last_working"):
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
    assert "Tool" in dialog.status.text() and not dialog.send_button.isEnabled()
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


@pytest.mark.parametrize("phase", ["start", "status", "upload"])
def test_upload_does_not_follow_redirects_or_forward_its_access_key(tmp_path,monkeypatch,phase):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    requests = []; authorization = []
    redirect_path = {"start":"/verification/start", "status":"/verification/status", "upload":"/reports"}[phase]
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def redirect(self):
            self.send_response(307)
            self.send_header("Location",f"http://127.0.0.1:{self.server.server_port}/unexpected-destination")
            self.send_header("Content-Length","0"); self.end_headers()
        def do_POST(self):
            requests.append(self.path)
            authorization.append(self.headers.get("Authorization"))
            if self.path != redirect_path and self.handle_verification_start(): return
            self.rfile.read(int(self.headers["Content-Length"]))
            self.redirect()
        def do_GET(self):
            requests.append(self.path)
            authorization.append(self.headers.get("Authorization"))
            if self.path == redirect_path: self.redirect()
            else: super().do_GET()
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path)); dialog._verification_poll.setInterval(10)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:not dialog._network_stage)
        expected_paths = ["/verification/start"] + (["/verification/status"] if phase != "start" else [])
        if phase == "upload": expected_paths.append("/reports")
        assert requests == expected_paths and not dialog._sent
        assert authorization[0] is None and all(value != "Bearer synthetic-key" for value in authorization)
        if phase != "start": assert authorization[-1].startswith("Bearer " + dialog._reviewed.report_id)
        assert "not confirmed" in dialog.status.text()
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_async_upload_preserves_same_draft_on_failure_and_accepts_only_a_receipt(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    received = []
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def do_POST(self):
            if self.handle_verification_start(): return
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
    dialog._verification_poll.setInterval(10)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        dialog.consent.setChecked(True); dialog._send()
        wait_until(lambda:not dialog._network_stage)
        assert "not confirmed" in dialog.status.text() and not dialog._sent
        assert reviewed.draft_path.read_bytes() == reviewed.body
        dialog._send(); wait_until(lambda:not dialog._network_stage)
        assert dialog._sent and "Report received: CDMW-2" in dialog.status.text()
        assert dialog.tabs.currentIndex() == dialog._RECEIPT_PAGE
        assert dialog.receipt_reference.text() == "CDMW-2"
        assert dialog.receipt_summary.text() == details().summary
        assert dialog.send_button.isHidden() and dialog.status.isHidden()
        assert len(received) == 2 and received[0] == received[1]
        assert received[0][1] == "Bearer " + reviewed.report_id + ".synthetic_signature"
        assert server.verification == {"report_id":reviewed.report_id,"report_sha256":hashlib.sha256(reviewed.body).hexdigest()}
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_matched_duplicate_opens_receipt_without_claiming_the_new_draft_was_sent(tmp_path,monkeypatch):
    app(); monkeypatch.setenv("CDMW_REPORT_TEST_TOKEN","synthetic-key")
    received=[]
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def do_POST(self):
            if self.handle_verification_start(): return
            payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload["report_id"])
            self.send_response(409)
            self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps({"code":"already_reported","report_id":payload["report_id"],"issue_number":3}).encode())
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path))
    dialog._verification_poll.setInterval(10)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:not dialog._network_stage)
        assert dialog._sent and dialog.tabs.currentIndex() == dialog._RECEIPT_PAGE
        assert dialog.receipt_title.text() == "Already reported"
        assert dialog.receipt_reference.text() == "CDMW-3"
        assert "was not sent" in dialog.receipt_detail.text()
        assert dialog.send_button.isHidden() and not dialog._step_buttons[0].isEnabled()
        dialog._send(); assert len(received) == 1
        dialog.copy_receipt_button.click()
        assert QApplication.clipboard().text() == "CDMW-3"
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_guided_questions_focus_the_missing_field_and_explain_workflow(tmp_path):
    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.problem_type.setCurrentIndex(dialog.problem_type.findData("Unexpected in-game result"))
        dialog.mod_manager.setCurrentIndex(dialog.mod_manager.findData("CDMW overlays"))
        dialog.install_method.setCurrentIndex(dialog.install_method.findData("CDMW overlay"))
        dialog.mod_setup.setPlainText("Synthetic test mod")
        assert "CDMW and in the game separately" in dialog._problem_help.toolTip()
        assert dialog._problem_help.toolTip() in dialog._steps_help.toolTip()
        dialog._problem_help.click()
        assert QToolTip.text() == dialog._problem_help.toolTip()
        QToolTip.hideText()
        dialog.steps.setPlainText("broken")
        dialog.show()
        dialog.summary.setFocus()
        QTest.keyClick(dialog.summary, Qt.Key.Key_Return)
        assert dialog.tabs.currentIndex() == 1
        dialog._next()
        assert dialog.tabs.currentIndex() == 1 and "Steps to reproduce" in dialog.status.text()
        dialog.steps.setPlainText(details().steps)
        dialog._next()
        assert dialog.tabs.currentIndex() == 2
        dialog.last_working.setCurrentIndex(dialog.last_working.findData("Worked before"))
        assert not dialog._changes_field.isHidden()
        dialog._collect()
        assert "Recent changes" in dialog.status.text() and dialog._collection is None
        dialog.changes.setPlainText("Not sure yet")
        dialog._collect(); wait_until(lambda:dialog._collection is None)
        assert dialog.tabs.currentIndex() == dialog._REVIEW_PAGE and dialog._reviewed is not None
        assert "Unexpected in-game result" in dialog.preview.toPlainText()
        assert dialog._raw_preview.toPlainText() == dialog._reviewed.preview
    finally:
        dialog.close()


def test_guided_navigation_validates_skipped_steps_and_recollects_after_edit(tmp_path):
    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.game_version.clear()
        dialog._step_buttons[3].click()
        assert dialog.tabs.currentIndex() == 2 and "Game version" in dialog.status.text()
        dialog.game_version.setText("Unknown")
        dialog._step_buttons[3].click()
        assert dialog.tabs.currentIndex() == 3 and not dialog.collect_button.isHidden()
        dialog.collect_button.click()
        wait_until(lambda:dialog._collection is None)
        assert dialog.tabs.currentIndex() == dialog._REVIEW_PAGE
        original = dialog._reviewed
        dialog.full_details_button.click()
        assert not dialog._raw_preview.isHidden() and dialog.preview.isHidden()
        dialog._review_link(QUrl("https://example.invalid/"))
        assert dialog.tabs.currentIndex() == dialog._REVIEW_PAGE
        dialog._review_link(QUrl("edit:1"))
        assert dialog.tabs.currentIndex() == 1
        dialog.actual.setPlainText("A changed outcome for the same problem.")
        assert dialog._reviewed is None and not dialog.consent.isEnabled()
        dialog._navigate(dialog._REVIEW_PAGE)
        wait_until(lambda:dialog._collection is None)
        assert dialog._reviewed is not None and dialog._reviewed.report_id != original.report_id
        assert not dialog.consent.isChecked()
    finally:
        dialog.close()


def test_reporting_explains_repository_access_and_per_report_evidence_links(tmp_path):
    from cdmw.services.problem_report_service import REPORT_DESTINATION, REPORT_ENDPOINT

    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        assert REPORT_ENDPOINT == "https://cdmw-reports.cdmw-workbench.workers.dev/reports"
        assert not any("inbox" in label.text().casefold() for label in dialog.findChildren(QLabel))
        assert dialog.destination.text() == "Evidence kept for 90 days"
        assert dialog.destination.toolTip() == REPORT_DESTINATION
        assert "maintainer and invited repository collaborators" in REPORT_DESTINATION
        assert "Anyone with the complete evidence link" in REPORT_DESTINATION
        dialog._privacy_help.click()
        assert QToolTip.text() == REPORT_DESTINATION
        QToolTip.hideText()
        dialog._reviewed = collect_problem_report(ProblemReportRequest(details(), snapshot(tmp_path)))
        dialog._receipt = "Report reference 123"
        dialog._show_receipt()
        assert dialog.receipt_detail.text() == "Evidence kept for 90 days"
        assert dialog.receipt_detail.toolTip() == REPORT_DESTINATION
    finally:
        dialog.close()


def test_guided_review_escapes_report_text_and_provides_fitted_screenshots(tmp_path):
    from PIL import Image
    app()
    shot = tmp_path / "screenshot.png"
    Image.new("RGB", (1800, 900), "blue").save(shot)
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.summary.setText("Literal <b>markup</b> in this report")
        dialog._screenshots = (str(shot),)
        dialog._collect()
        wait_until(lambda:dialog._collection is None)
        assert "<b>markup</b>" in dialog.preview.toPlainText()
        assert dialog.image_tabs.count() == 1 and not dialog.fit_images.isHidden()
        dialog.show()
        QTest.qWait(10)
        image = dialog.image_tabs.widget(0)
        assert image._label.pixmap().width() <= image.viewport().width()
        assert image._label.pixmap().height() <= image.viewport().height()
        dialog.fit_images.setChecked(False)
        assert image._label.pixmap().width() == 1800
        dialog.actual.setPlainText("A different actual result requires review.")
        assert dialog.image_tabs.count() == 0 and dialog.fit_images.isHidden()
    finally:
        dialog.close()


def test_guided_compact_navigation_preserves_the_current_step(tmp_path):
    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.show()
        dialog.resize(600, 600)
        QTest.qWait(10)
        assert dialog.rail.isHidden() and not dialog.step_picker.isHidden()
        dialog.step_picker.activated.emit(2)
        assert dialog.tabs.currentIndex() == 2 and dialog.step_picker.currentIndex() == 2
        dialog.resize(1000, 760)
        QTest.qWait(10)
        assert not dialog.rail.isHidden() and dialog.step_picker.isHidden()
        assert dialog._step_buttons[2].isChecked()
    finally:
        dialog.close()


def test_all_reporting_dropdowns_use_bounded_lists_and_tool_opens_below(tmp_path):
    from cdmw.ui.themes import build_app_stylesheet
    application = app()
    previous_stylesheet = application.styleSheet()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    fusion = QStyleFactory.create("Fusion")
    fusion.setParent(dialog)
    dialog.setStyle(fusion)
    try:
        application.setStyleSheet(build_app_stylesheet("graphite"))
        fill_form(dialog)
        dialog.show()
        QTest.qWait(20)
        for combo in dialog.findChildren(QComboBox):
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            assert combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, option, combo) == 0
        for selection in (0, dialog.tool.findData("settings"), dialog.tool.count() - 1):
            with QSignalBlocker(dialog.tool):
                dialog.tool.setCurrentIndex(selection)
            dialog.tool.showPopup()
            QTest.qWait(10)
            popup = dialog.tool.view().window()
            bottom = dialog.tool.mapToGlobal(QPoint(0, dialog.tool.height() - 1)).y()
            assert popup.y() >= bottom - 2
            assert dialog.tool.screen().availableGeometry().contains(popup.frameGeometry())
            assert dialog.tool.view().verticalScrollBar().maximum() > 0
            dialog.tool.hidePopup()
    finally:
        dialog.tool.hidePopup()
        dialog.close()
        application.setStyleSheet(previous_stylesheet)


def test_tool_menu_covers_shell_tools_and_resets_dependent_choices(tmp_path):
    from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS
    app()
    by_key = {tool.key:tool for tool in REPORT_TOOLS}
    assert len(by_key) == len(REPORT_TOOLS)
    assert all(by_key[spec.key].label == spec.label for spec in COMPACT_TOOL_SPECS)
    assert report_tool("Archive Browser").key == "archive_browser"
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        assert not dialog.tool.isEditable() and not dialog.workflow.isEditable()
        for spec in REPORT_TOOLS:
            dialog.tool.setCurrentIndex(dialog.tool.findData(spec.key))
            assert dialog.workflow.currentData() == ""
            actual = tuple(dialog.workflow.itemData(index) for index in range(1,dialog.workflow.count()))
            assert actual == tool_actions(spec)
            for action in actual:
                decoded, restored, other = decode_tool(encode_tool(spec,action,"Synthetic feature"))
                assert decoded.key == spec.key and restored == action
            dialog.workflow.setCurrentIndex(1)
        dialog.tool.setCurrentIndex(dialog.tool.findData("mesh_editor"))
        for action in ("Cloth","Vertex Parameters","Hair Tools / Appearance","Import Replacement / editable exchange"):
            assert dialog.workflow.findData(action) > 0
        dialog.workflow.setCurrentIndex(dialog.workflow.findData("Cloth"))
        assert "cloth profile/control" in dialog._workflow_help.toolTip()
        dialog.tool.setCurrentIndex(dialog.tool.findData("textures"))
        assert dialog.workflow.currentData() == "" and dialog.workflow.findData("Cloth") == -1
        assert dialog.workflow.findData("Recolor") > 0 and dialog.workflow.findData("Upscale / AI backend") > 0
    finally:
        dialog.close()


def test_mesh_report_targets_source_and_action_and_app_only_setup_without_changing_wire_schema(tmp_path,monkeypatch):
    app()
    dialog = ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.tool.setCurrentIndex(dialog.tool.findData("mesh_editor"))
        dialog.workflow.setCurrentIndex(dialog.workflow.findData("Parts / materials / textures"))
        dialog.input_source.setCurrentIndex(dialog.input_source.findData("GLB / glTF"))
        dialog.input_item.setText("coat.glb / body part")
        dialog.game_involved.setCurrentIndex(dialog.game_involved.findData("No"))
        assert "material/texture slot" in dialog._steps_help.toolTip()
        assert "Select the part" in dialog.steps.placeholderText()
        assert dialog._game_fields.isHidden() and not dialog.include_layout.isEnabled()
        assert not dialog._form_errors()
        dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        payload=json.loads(reviewed.body)
        assert payload["schema_version"] == 1 and set(payload["details"]) == set(dataclasses.asdict(details()))
        assert payload["details"]["tool"] == "Mesh Editor — Parts / materials / textures"
        assert payload["details"]["input_item"] == "Source: GLB / glTF\nItem: coat.glb / body part"
        assert payload["details"]["game_version"] == "Not applicable"
        assert "folder_layout" not in payload["evidence"]
        assert "Game files and mods are not involved" in dialog.preview.toPlainText()
        monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.QFileDialog.getOpenFileName",lambda *args:(str(reviewed.draft_path),""))
        dialog._open_draft(); wait_until(lambda:dialog._collection is None)
        assert dialog._reviewed.body == reviewed.body
        assert dialog.tool.currentData() == "mesh_editor" and dialog.workflow.currentData() == "Parts / materials / textures"
        assert dialog.input_source.currentData() == "GLB / glTF" and dialog.input_item.text() == "coat.glb / body part"
        assert dialog.game_involved.currentData() == "No"
        dialog.input_source.setCurrentIndex(dialog.input_source.findData("Game model (PAC / PAM / PAMLOD)"))
        assert dialog.game_involved.currentData() == "Yes" and not dialog.game_involved.isEnabled()
        dialog.workflow.setCurrentIndex(dialog.workflow.findData("Window / layout / controls"))
        assert dialog.game_involved.isEnabled() and dialog._input_fields.isHidden()
        dialog.game_involved.setCurrentIndex(dialog.game_involved.findData("No"))
        assert dialog._details().input_item == "Not applicable" and not dialog._form_errors()
        dialog.tool.setCurrentIndex(dialog.tool.findData("textures"))
        assert dialog._reviewed is None and not dialog.consent.isEnabled()
        dialog._collect()
        assert "Affected action" in dialog.status.text()
    finally:
        dialog.close()


def test_stall_report_requires_wait_and_response_and_restores_them_from_exact_draft(tmp_path,monkeypatch):
    app()
    dialog=ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.problem_type.setCurrentIndex(dialog.problem_type.findData("Slow or unresponsive"))
        assert not dialog._stall_fields.isHidden()
        dialog._collect()
        assert "How long" in dialog.status.text()
        dialog.waited.setCurrentIndex(dialog.waited.findData("5–15 minutes"))
        dialog.progress_state.setCurrentIndex(dialog.progress_state.findData("Progress stopped"))
        dialog.actual.clear()
        assert any(key=="actual" for key,_ in dialog._form_errors())
        dialog.actual.setPlainText("Progress remains at 0% after Extract.")
        dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        assert "Waited: 5–15 minutes\nProgress: Progress stopped\nObserved:" in json.loads(reviewed.body)["details"]["actual"]
        monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.QFileDialog.getOpenFileName",lambda *args:(str(reviewed.draft_path),""))
        dialog._open_draft(); wait_until(lambda:dialog._collection is None)
        assert dialog._reviewed.body == reviewed.body
        assert dialog.waited.currentData() == "5–15 minutes" and dialog.progress_state.currentData() == "Progress stopped"
        assert dialog.actual.toPlainText() == "Progress remains at 0% after Extract."
        dialog.problem_type.setCurrentIndex(dialog.problem_type.findData("CDMW error / crash"))
        assert dialog._stall_fields.isHidden() and "Waited:" not in dialog._details().actual
    finally:
        dialog.close()


def test_export_target_is_required_even_when_no_mod_has_been_installed(tmp_path):
    app()
    dialog=ProblemReportDialog(snapshot(tmp_path))
    try:
        fill_form(dialog)
        dialog.workflow.setCurrentIndex(dialog.workflow.findData("Export a mod package"))
        assert not dialog._mod_fields.isHidden()
        dialog._collect()
        assert "Manager" in dialog.status.text()
        dialog.mod_manager.setCurrentIndex(dialog.mod_manager.findData("CDUMM"))
        dialog.install_method.setCurrentIndex(dialog.install_method.findData("Not installed yet"))
        dialog.mod_setup.setPlainText("Synthetic texture replacement mod")
        assert not dialog._form_errors()
        assert "Mods: No mods installed\nManager: CDUMM\nInstallation: Not installed yet" in dialog._details().mod_setup
        dialog.input_item.setText("Not applicable")
        assert any(key=="input_item" for key,_ in dialog._form_errors())
        dialog.item_unknown.setChecked(True)
        assert not dialog._form_errors() and "Unknown item / file" in dialog._details().input_item
        dialog.tool.setCurrentIndex(dialog.tool.findData("application"))
        dialog.workflow.setCurrentIndex(dialog.workflow.findData("Start / close CDMW"))
        assert dialog.input_item.parentWidget().isHidden() and dialog._game_fields.isHidden()
        assert dialog.problem_type.findData("Unexpected in-game result") == -1
        assert dialog._details().input_item == "Not applicable"
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
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def do_POST(self):
            if self.handle_verification_start(): return
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
    dialog._verification_poll.setInterval(10)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:not dialog._network_stage)
        assert not dialog.send_button.isEnabled() and "Retry in" in dialog.send_button.text()
        dialog._send(); assert len(received)==1
        wait_until(dialog.send_button.isEnabled,3)
        dialog._send(); wait_until(lambda:not dialog._network_stage)
        assert dialog._sent and received[0] == received[1]
        dialog.copy_receipt_button.click()
        assert "CDMW-4" in QApplication.clipboard().text()
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)


def test_verification_metadata_has_no_report_text_and_rejects_other_destinations(tmp_path):
    reviewed = collect_problem_report(ProblemReportRequest(details(),snapshot(tmp_path)))
    metadata = json.loads(report_verification_request(reviewed))
    assert metadata == {"report_id":reviewed.report_id,"report_sha256":hashlib.sha256(reviewed.body).hexdigest()}
    endpoint = "https://reports.example/reports"
    response = {"status":"verification_required","report_id":reviewed.report_id,"ticket":"signed.ticket",
        "verification_url":"https://reports.example/verify#signed.ticket","expires_in":600}
    check = parse_report_verification(json.dumps(response).encode(),report_id=reviewed.report_id,endpoint=endpoint)
    assert check.url == response["verification_url"]
    for changed in ({"report_id":"different"},{"ticket":"a"},{"expires_in":601},{"expires_in":True},
        {"verification_url":"https://attacker.example/verify#signed.ticket"},
        {"verification_url":"http://reports.example/verify#signed.ticket"},
        {"verification_url":"https://reports.example/verify?key=signed.ticket#signed.ticket"},
        {"verification_url":"https://reports.example/verify#different"}):
        with pytest.raises(ValueError):
            parse_report_verification(json.dumps({**response,**changed}).encode(),report_id=reviewed.report_id,endpoint=endpoint)
    assert parse_report_verification_status(json.dumps({"status":"verified","report_id":reviewed.report_id}).encode(),report_id=reviewed.report_id)
    assert not parse_report_verification_status(json.dumps({"status":"pending","report_id":reviewed.report_id}).encode(),report_id=reviewed.report_id)
    with pytest.raises(ValueError):
        parse_report_verification_status(b'{"status":"verified","report_id":"other"}',report_id=reviewed.report_id)


@pytest.mark.parametrize("phase",["start","status"])
@pytest.mark.parametrize("action",["cancel","edit","close"])
def test_cancel_edit_or_close_during_verification_never_uploads_a_report(tmp_path,monkeypatch,phase,action):
    app(); monkeypatch.delenv("CDMW_REPORT_TEST_TOKEN",raising=False)
    entered=threading.Event(); release=threading.Event(); uploads=[]
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def do_POST(self):
            try:
                if self.path == "/verification/start":
                    if phase == "start": entered.set(); release.wait(5)
                    self.handle_verification_start()
                else:
                    uploads.append(self.path)
                    self.send_response(500); self.end_headers()
            except (BrokenPipeError,ConnectionResetError): pass
        def do_GET(self):
            try:
                if phase == "status": entered.set(); release.wait(5)
                super().do_GET()
            except (BrokenPipeError,ConnectionResetError): pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path)); dialog._verification_poll.setInterval(10)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        dialog.consent.setChecked(True)
        assert dialog.send_button.isEnabled()
        dialog._send(); wait_until(entered.is_set)
        start=time.monotonic()
        if action == "cancel": dialog.verification_cancel_button.click()
        elif action == "edit": dialog.summary.setText("A different problem invalidates verification")
        else: dialog.close()
        assert time.monotonic()-start < .1
        assert not dialog._verification_poll.isActive() and not dialog._network_stage
        release.set(); QTest.qWait(40)
        assert uploads == [] and not dialog._sent
        assert reviewed.draft_path.read_bytes() == reviewed.body
    finally:
        release.set()
        if not dialog._closed: dialog.close()
        server.shutdown(); server.server_close(); thread.join(2)


def test_browser_failure_and_expiry_leave_the_reviewed_draft_available(tmp_path,monkeypatch):
    from cdmw.ui.themes import build_app_stylesheet
    application=app(); previous_stylesheet=application.styleSheet()
    monkeypatch.delenv("CDMW_REPORT_TEST_TOKEN",raising=False)
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.QDesktopServices.openUrl",lambda url:False)
    class Receiver(VerifiedReportReceiver):
        def log_message(self,*args): pass
        def do_POST(self): assert self.handle_verification_start()
    server=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr("cdmw.ui.shell.problem_report_dialog.REPORT_ENDPOINT",f"http://127.0.0.1:{server.server_port}/reports")
    dialog=ProblemReportDialog(snapshot(tmp_path)); dialog._verification_poll.setInterval(60000)
    try:
        fill_form(dialog); dialog._collect(); wait_until(lambda:dialog._collection is None)
        reviewed=dialog._reviewed
        dialog.consent.setChecked(True); dialog._send(); wait_until(lambda:dialog._network_stage == "waiting")
        assert "Could not open" in dialog.status.text()
        assert not dialog.verification_open_button.isHidden() and not dialog.send_button.isEnabled()
        application.setStyleSheet(build_app_stylesheet("graphite"))
        dialog.resize(460,440); dialog.show(); QTest.qWait(10)
        assert dialog.width() == 460
        for button in (dialog.verification_open_button,dialog.verification_cancel_button,dialog.close_button):
            assert button.width() >= button.sizeHint().width()
        dialog._verification_deadline=time.monotonic()-1
        dialog._poll_verification()
        assert "expired" in dialog.status.text() and dialog.send_button.isEnabled()
        assert dialog._reviewed is reviewed and not dialog._verification_poll.isActive()
        assert not dialog._verification_ticket
    finally:
        dialog.close(); server.shutdown(); server.server_close(); thread.join(2)
        application.setStyleSheet(previous_stylesheet)
