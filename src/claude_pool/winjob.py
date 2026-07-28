"""Windows Job Object helpers.

Assigning worker processes to a job created with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE means the OS kernel terminates every
assigned process the moment the job's last handle closes - including when
the daemon process holding that handle is killed outright (crash,
TerminateProcess, power loss) with no chance to run any Python cleanup
code. This is enforced by Windows itself, not by anything in this process.
"""
from __future__ import annotations

import sys

if sys.platform == "win32":
    import win32api
    import win32con
    import win32job


def create_kill_on_close_job() -> object | None:
    """Create a job object that kills its members when its last handle
    closes. Returns None on non-Windows platforms."""
    if sys.platform != "win32":
        return None
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


def assign_process_to_job(job: object | None, pid: int) -> None:
    """Assign the process with the given pid to job. No-op if job is None
    (non-Windows platforms, or job creation was skipped)."""
    if job is None:
        return
    proc_handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
    try:
        win32job.AssignProcessToJobObject(job, proc_handle)
    finally:
        proc_handle.Close()
