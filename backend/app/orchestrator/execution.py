"""Runs the generated site's checks inside Docker (the Integrate phase).

Each check gets a fresh container from the runner image (backend/runner/) with:
no network, a read-only root filesystem, only the run's site/ folder mounted read-only,
no environment variables (so no secrets), capped memory, CPU and processes, no Linux
capabilities, a non-root user and a timeout. Nothing a model wrote ever runs on the host.
"""

import asyncio
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings


@dataclass
class CheckResult:
    status: str  # passed | failed | not_run
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    logo: dict[str, Any] | None = None
    detail: str = ""
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "errors": self.errors, "warnings": self.warnings,
                "logo": self.logo, "detail": self.detail}


def docker_args(site_dir: Path, image: str, name: str) -> list[str]:
    s = get_settings()
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--read-only", "--tmpfs", "/tmp:size=16m,noexec",
        "--memory", s.runner_memory, "--memory-swap", s.runner_memory,
        "--cpus", str(s.runner_cpus), "--pids-limit", "64",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "1000:1000",
        "--env-file", "/dev/null",
        "-v", f"{site_dir.resolve()}:/work/site:ro",
        image, "/work/site",
    ]


async def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", get_settings().runner_image,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(proc.wait(), 15) == 0
    except (OSError, TimeoutError):
        return False


async def check_site(site_dir: Path) -> CheckResult:
    s = get_settings()
    if not site_dir.is_dir():
        return CheckResult("failed", errors=[{"file": "site/index.html", "kind": "missing",
                                              "message": "The site folder does not exist.", "line": None}])
    if not await docker_available():
        return CheckResult("not_run", detail=f"Docker or the runner image ({s.runner_image}) is not available, "
                                             "so the site was not run. Build it with: docker build -t "
                                             f"{s.runner_image} backend/runner")
    name = f"pantheon-check-{uuid.uuid4().hex[:10]}"
    proc = await asyncio.create_subprocess_exec(
        *docker_args(site_dir, s.runner_image, name),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), s.runner_timeout_s)
    except TimeoutError:
        kill = await asyncio.create_subprocess_exec("docker", "kill", name, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        await kill.wait()
        return CheckResult("failed", errors=[{"file": None, "kind": "timeout",
                                              "message": f"The check timed out after {s.runner_timeout_s}s "
                                                         "(an endless loop?)", "line": None}])
    try:
        report = json.loads(out.decode().strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return CheckResult("failed", errors=[{"file": None, "kind": "runner",
                                              "message": (err.decode() or out.decode())[-500:], "line": None}])
    return CheckResult(
        "passed" if report.get("ok") else "failed",
        errors=report.get("errors", []), warnings=report.get("warnings", []),
        logo=report.get("logo"), raw=report,
    )
