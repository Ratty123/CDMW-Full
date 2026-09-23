from __future__ import annotations

import ctypes
import os
from unittest.mock import Mock

import pytest

from cdmw.services import process_job_service as jobs


@pytest.fixture
def windows_jobs(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows job setup")
    monkeypatch.setattr(jobs, "_app_job_bound", None)
    monkeypatch.setattr(jobs, "_app_job_handle", 0)
    monkeypatch.setattr(jobs, "_app_job_failure", "")
    kernel = Mock()
    kernel.CreateJobObjectW.return_value = 101
    kernel.SetInformationJobObject.return_value = True
    kernel.AssignProcessToJobObject.return_value = True
    kernel.GetCurrentProcess.return_value = 202
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)
    return kernel


@pytest.mark.parametrize("operation", ["CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject"])
def test_failed_job_setup_preserves_error_and_closes_unassigned_handle(windows_jobs, operation):
    getattr(windows_jobs, operation).return_value = 0
    assert not jobs.bind_process_tree_to_app_lifetime()
    assert not jobs.app_lifetime_job_is_bound()
    assert operation in jobs.app_lifetime_job_failure()
    assert "5" in jobs.app_lifetime_job_failure()
    if operation == "CreateJobObjectW":
        windows_jobs.CloseHandle.assert_not_called()
    else:
        windows_jobs.CloseHandle.assert_called_once_with(101)


def test_successful_job_setup_retains_noninherited_kill_on_close_handle(windows_jobs):
    assert jobs.bind_process_tree_to_app_lifetime()
    assert jobs.bind_process_tree_to_app_lifetime()
    windows_jobs.CreateJobObjectW.assert_called_once_with(None, None)
    windows_jobs.AssignProcessToJobObject.assert_called_once_with(101, 202)
    windows_jobs.CloseHandle.assert_not_called()
    limits = windows_jobs.SetInformationJobObject.call_args.args[2]._obj
    assert limits.BasicLimitInformation.LimitFlags & jobs.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert jobs.app_lifetime_job_failure() == ""


@pytest.mark.skipif(os.name != "nt", reason="Windows bootstrap containment")
@pytest.mark.parametrize("argv", [[], ["--cli"]])
def test_failed_containment_aborts_before_any_main_app_work(monkeypatch, argv):
    from cdmw.app import bootstrap

    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: False)
    monkeypatch.setattr(bootstrap, "app_lifetime_job_failure", lambda: "AssignProcessToJobObject: access denied")
    monkeypatch.setattr(bootstrap, "gui_startup_smoke_requested", lambda: False)
    report = Mock()
    monkeypatch.setattr(bootstrap, "write_bootstrap_report", report)
    for name in ("_reap_stranded_helpers", "start_external_startup_splash", "run_startup_maintenance",
                 "run_cli_workflow", "run_gui_workflow", "acquire_single_instance_guard"):
        monkeypatch.setattr(bootstrap, name, lambda: pytest.fail("Uncontained startup continued"))
    with pytest.raises(RuntimeError, match="AssignProcessToJobObject: access denied"):
        bootstrap.main(argv)
    assert report.call_args.args[0] == "process_containment_failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows bootstrap containment")
def test_startup_smoke_reports_containment_failure_without_an_error_dialog(monkeypatch):
    from cdmw.app import bootstrap

    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: False)
    monkeypatch.setattr(bootstrap, "app_lifetime_job_failure", lambda: "CreateJobObjectW failed")
    monkeypatch.setattr(bootstrap, "gui_startup_smoke_requested", lambda: True)
    monkeypatch.setattr(bootstrap, "write_bootstrap_report", Mock())
    monkeypatch.setattr(bootstrap, "update_pyinstaller_boot_splash", Mock())
    result = Mock()
    monkeypatch.setattr(bootstrap, "write_gui_startup_smoke_result", result)
    assert bootstrap.main([]) == 3
    assert result.call_args.kwargs["ok"] is False
    assert result.call_args.kwargs["stage"] == "process_containment"


@pytest.mark.parametrize("failed", [False, True])
def test_workflow_exit_arms_shutdown_even_without_a_window_close(monkeypatch, failed):
    from cdmw.app import bootstrap

    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: True)
    monkeypatch.setattr(bootstrap, "_reap_stranded_helpers", lambda: None)
    monkeypatch.setattr(bootstrap, "run_startup_maintenance", lambda: None)
    monkeypatch.setattr(bootstrap, "write_bootstrap_report", Mock())
    arm = Mock()
    monkeypatch.setattr(bootstrap, "begin_application_shutdown", arm)
    runner = Mock(side_effect=RuntimeError("workflow failed")) if failed else Mock(return_value=0)
    monkeypatch.setattr(bootstrap, "run_cli_workflow", runner)
    if failed:
        with pytest.raises(RuntimeError, match="workflow failed"):
            bootstrap.main(["--cli"])
    else:
        assert bootstrap.main(["--cli"]) == 0
    arm.assert_called_once_with()
