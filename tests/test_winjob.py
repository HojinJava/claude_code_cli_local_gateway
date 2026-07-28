import subprocess
import sys
import time

import pytest

from claude_pool import winjob

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only job object API")


def _is_running(pid: int) -> bool:
    import win32api
    import win32con
    import win32process

    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
    except Exception:
        return False
    code = win32process.GetExitCodeProcess(handle)
    handle.Close()
    return code == 259  # STILL_ACTIVE


def test_create_kill_on_close_job_returns_a_job_handle():
    job = winjob.create_kill_on_close_job()
    assert job is not None


def test_closing_the_job_kills_the_assigned_process():
    job = winjob.create_kill_on_close_job()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        winjob.assign_process_to_job(job, proc.pid)
        assert _is_running(proc.pid)

        job.Close()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _is_running(proc.pid):
            time.sleep(0.1)
        assert not _is_running(proc.pid)
    finally:
        if _is_running(proc.pid):
            proc.kill()
        proc.wait()


def test_assign_process_to_job_is_a_noop_with_no_job():
    # Should not raise even though there's no job to assign to.
    winjob.assign_process_to_job(None, pid=1)
