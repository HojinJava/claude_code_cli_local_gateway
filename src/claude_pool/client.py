from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


class ClaudePoolError(Exception):
    """A failed /generate call, carrying the daemon's classification.

    `retryable` distinguishes "the same request will work shortly" (queue
    pressure, rate limit, timeout) from "a human has to fix something"
    (expired CLI login, model error), so callers can back off instead of
    hammering — and `retry_after_sec` says how long to wait when the daemon
    knows.
    """

    def __init__(
        self,
        message: str,
        kind: str = "unknown",
        retryable: bool = False,
        retry_after_sec: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.retry_after_sec = retry_after_sec


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

    def _call(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        request_timeout: float = 30.0,
    ) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise self._error_from(exc) from exc

    @staticmethod
    def _prompt_payload(prompt: str, timeout_sec: float | None) -> dict:
        payload: dict = {"prompt": prompt}
        if timeout_sec is not None:
            payload["timeout_sec"] = timeout_sec
        return payload

    def generate(self, prompt: str, timeout_sec: float | None = None) -> str:
        """Run a prompt and wait for it. Holds the connection open throughout."""
        body = self._call(
            "POST",
            "/generate",
            self._prompt_payload(prompt, timeout_sec),
            # Outlive the daemon's own timeout, so a slow completion surfaces
            # as the daemon's 504 rather than as a socket timeout here.
            request_timeout=(timeout_sec or 120.0) + 5.0,
        )
        return body["text"]

    def submit(self, prompt: str, timeout_sec: float | None = None) -> str:
        """Hand the prompt off to run in the background; returns a job id.

        Use instead of generate() when waiting on an open socket is the
        problem — a batch of prompts, or a caller that must not block.
        """
        return self._call(
            "POST", "/jobs", self._prompt_payload(prompt, timeout_sec)
        )["job_id"]

    def job(self, job_id: str) -> dict:
        """The job's current state. Never raises for a failed job — read
        `status`; the failure detail is in the same dict."""
        return self._call("GET", f"/jobs/{job_id}")

    def jobs(self) -> list[dict]:
        return self._call("GET", "/jobs")["jobs"]

    def cancel(self, job_id: str) -> dict:
        """Cancel a running job (killing its worker), or forget a finished one."""
        return self._call("DELETE", f"/jobs/{job_id}")

    def wait(
        self,
        job_id: str,
        poll_interval_sec: float = 1.0,
        timeout_sec: float | None = None,
    ) -> str:
        """Block until the job finishes and return its text.

        Raises ClaudePoolError carrying the job's own classification if it
        failed or was cancelled, so it fails the same way generate() does.
        """
        deadline = None if timeout_sec is None else time.monotonic() + timeout_sec
        while True:
            job = self.job(job_id)
            status = job["status"]
            if status == "succeeded":
                return job["text"]
            if status in ("failed", "cancelled"):
                raise ClaudePoolError(
                    job.get("error", status),
                    kind=job.get("kind", status),
                    retryable=bool(job.get("retryable", False)),
                    retry_after_sec=job.get("retry_after_sec"),
                )
            if deadline is not None and time.monotonic() >= deadline:
                raise ClaudePoolError(
                    f"job {job_id} still {status} after {timeout_sec}s",
                    kind="timeout",
                    retryable=True,
                )
            time.sleep(poll_interval_sec)

    @staticmethod
    def _error_from(exc: urllib.error.HTTPError) -> ClaudePoolError:
        try:
            body = json.loads(exc.read())
        except (ValueError, OSError):
            # A non-JSON error body (proxy, crash page) must still raise
            # ClaudePoolError, not a decode error from inside the client.
            body = {}
        retry_after = body.get("retry_after_sec")
        if retry_after is None:
            header = exc.headers.get("Retry-After") if exc.headers else None
            retry_after = int(header) if header and header.isdigit() else None
        return ClaudePoolError(
            body.get("error", f"HTTP {exc.code}"),
            kind=body.get("kind", "unknown"),
            retryable=bool(body.get("retryable", False)),
            retry_after_sec=retry_after,
        )

    def health(self) -> dict:
        return self._call("GET", "/health", request_timeout=5.0)

    def api_info(self) -> dict:
        """The daemon's own description of itself (GET /)."""
        return self._call("GET", "/", request_timeout=5.0)
