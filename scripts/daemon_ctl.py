"""Start, stop, restart and inspect the claude-pool daemon.

    python scripts/daemon_ctl.py start | stop | restart | status

Reads the same environment variables the daemon does (PoolConfig.from_env),
so `CLAUDE_POOL_MODEL=haiku python scripts/daemon_ctl.py start` starts a
haiku daemon and later commands with the same CLAUDE_POOL_PORT act on it.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from claude_pool.client import ClaudePoolClient
from claude_pool.config import PoolConfig
from claude_pool.daemon import pid_file

STOP_TIMEOUT_SEC = 10.0


def _read_pid(config: PoolConfig) -> int | None:
    path = pid_file(config)
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _command_line(pid: int) -> str:
    """The process's command line, or '' if it is gone or unreadable."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, text=True,
        ).stdout
    else:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True
        ).stdout
    return out.strip()


def _live_daemon_pid(config: PoolConfig) -> int | None:
    """The pid only if it is really this daemon.

    A hard kill leaves the pid file behind, and the OS reuses pids, so the
    file alone is not enough to justify killing anything -- confirm the
    process is still a claude_pool daemon first.
    """
    pid = _read_pid(config)
    if pid is None:
        return None
    return pid if "claude_pool.daemon" in _command_line(pid) else None


def _daemon_pids_by_command_line() -> list[int]:
    """Every running claude_pool daemon, whatever port it serves.

    Fallback for a daemon with no usable pid file -- started before pid
    files existed, or hard-killed and restarted by hand. The port is not
    visible on the command line (it comes from the environment), so this
    can identify *a* daemon but never *which* one.
    """
    if sys.platform == "win32":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*claude_pool.daemon*' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True,
        ).stdout
    else:
        out = subprocess.run(
            ["pgrep", "-f", "claude_pool.daemon"], capture_output=True, text=True
        ).stdout
    return [int(line) for line in out.split() if line.strip().isdigit()]


def _is_answering(config: PoolConfig) -> bool:
    try:
        ClaudePoolClient(host=config.host, port=config.port, auto_start=False).health()
        return True
    except Exception:
        return False


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, text=True)
    else:
        os.kill(pid, signal.SIGTERM)


def _base_url(config: PoolConfig) -> str:
    return f"http://{config.host}:{config.port}"


def status(config: PoolConfig) -> int:
    client = ClaudePoolClient(host=config.host, port=config.port, auto_start=False)
    try:
        health = client.health()
    except Exception:
        print(f"stopped  ({_base_url(config)} is not answering)")
        return 1
    pid = _live_daemon_pid(config)
    print(f"running  pid={pid if pid else '?'}  {_base_url(config)}")
    print(f"  model    {config.model}")
    print(f"  workers  {health['idle_alive']}/{health['idle']} idle alive, "
          f"{health['busy']} busy  (min {health['min_workers']}, max {health['max_workers']})")
    print(f"  jobs     {health['jobs']['running']} running, {health['jobs']['total']} kept")
    if not health["healthy"]:
        print("  UNHEALTHY: pre-warmed workers are dying")
    for field in ("last_spawn_error", "last_error"):
        if health.get(field):
            print(f"  {field}: {health[field]}")
    print(f"  docs     {_base_url(config)}/docs")
    return 0


def start(config: PoolConfig) -> int:
    # auto_start is the daemon launcher: it spawns a detached daemon only if
    # nothing already answers on this port, so running start twice is safe.
    ClaudePoolClient(host=config.host, port=config.port, auto_start=True)
    return status(config)


def stop(config: PoolConfig) -> int:
    pid = _live_daemon_pid(config)
    if pid is None:
        pid_file(config).unlink(missing_ok=True)
        if not _is_answering(config):
            print(f"stopped  (nothing running on port {config.port})")
            return 0
        # Something is serving this port without a usable pid file. Saying
        # "nothing running" here would be a lie, and guessing which daemon
        # to kill would be worse.
        candidates = _daemon_pids_by_command_line()
        if len(candidates) != 1:
            print(f"port {config.port} is answering, but no pid file and "
                  f"{len(candidates)} daemon processes are running -- cannot tell "
                  f"which one serves this port. Stop it by hand:")
            for candidate in candidates:
                print(f"  taskkill /F /PID {candidate}"
                      if sys.platform == "win32" else f"  kill {candidate}")
            return 1
        pid = candidates[0]
        print(f"no pid file; falling back to the only running daemon (pid={pid})")

    _terminate(pid)
    deadline = time.monotonic() + STOP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if _live_daemon_pid(config) is None:
            pid_file(config).unlink(missing_ok=True)
            # Workers are in a kill-on-close job object, so the OS reaps them
            # the moment the daemon's handle closes -- nothing to clean here.
            print(f"stopped  pid={pid}")
            return 0
        time.sleep(0.2)

    print(f"FAILED to stop pid={pid} within {STOP_TIMEOUT_SEC}s")
    return 1


def restart(config: PoolConfig) -> int:
    if stop(config) != 0:
        return 1
    return start(config)


COMMANDS = {"start": start, "stop": stop, "restart": restart, "status": status}


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command not in COMMANDS:
        print(f"usage: {sys.argv[0]} [{'|'.join(COMMANDS)}]", file=sys.stderr)
        return 2
    return COMMANDS[command](PoolConfig.from_env())


if __name__ == "__main__":
    raise SystemExit(main())
