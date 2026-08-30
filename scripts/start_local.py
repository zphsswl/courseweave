"""Start CourseWeave as a detached local Windows process."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


DEFAULT_PORT = 8001
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
PID_PATH = RUNTIME_DIR / "courseweave.pid"
STDOUT_PATH = RUNTIME_DIR / "courseweave.out.log"
STDERR_PATH = RUNTIME_DIR / "courseweave.err.log"


def is_healthy(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            payload = json.load(response)
            return response.status == 200 and payload.get("status") == "ok"
    except (OSError, URLError, ValueError):
        return False


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    app_url = f"http://127.0.0.1:{port}/"

    if is_healthy(port):
        print(f"CourseWeave 已经在运行：{app_url}")
        return 0

    python_path = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python_path.exists():
        print(f"未找到项目 Python 环境：{python_path}", file=sys.stderr)
        return 1

    RUNTIME_DIR.mkdir(exist_ok=True)
    creation_flags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
    )
    command = [
        str(python_path),
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    with STDOUT_PATH.open("a", encoding="utf-8") as stdout_file, STDERR_PATH.open(
        "a", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creation_flags,
            close_fds=True,
        )

    PID_PATH.write_text(str(process.pid), encoding="ascii")

    for _ in range(40):
        if is_healthy(port):
            print(f"CourseWeave 启动成功：{app_url}")
            print(f"运行日志：{RUNTIME_DIR}")
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.25)

    error_tail = ""
    if STDERR_PATH.exists():
        error_tail = "\n".join(STDERR_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
    print(f"CourseWeave 启动失败，请查看：{STDERR_PATH}\n{error_tail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
