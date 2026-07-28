from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


class ClaudePoolError(Exception):
    pass


class ClaudePoolClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8756,
        auto_start: bool = True,
        start_timeout_sec: float = 15.0,
    ):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        if auto_start and not self._is_healthy():
            self._start_daemon()
            self._wait_until_healthy(start_timeout_sec)

    def _is_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=1.0):
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def _start_daemon(self) -> None:
        # The daemon reads PoolConfig.from_env(), so it only binds where this
        # client expects if we hand it this client's own host and port.
        env = dict(os.environ)
        env["CLAUDE_POOL_HOST"] = self.host
        env["CLAUDE_POOL_PORT"] = str(self.port)
        kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        subprocess.Popen([sys.executable, "-m", "claude_pool.daemon"], **kwargs)

    def _wait_until_healthy(self, timeout_sec: float) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self._is_healthy():
                return
            time.sleep(0.2)
        raise ClaudePoolError("daemon did not become healthy in time")

    def generate(self, prompt: str, timeout_sec: float | None = None) -> str:
        payload: dict = {"prompt": prompt}
        if timeout_sec is not None:
            payload["timeout_sec"] = timeout_sec
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_timeout = (timeout_sec or 120.0) + 5.0
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read())
            raise ClaudePoolError(body.get("error", "unknown error")) from exc
        return body["text"]

    def health(self) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=5.0) as resp:
            return json.loads(resp.read())
