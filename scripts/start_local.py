"""Start CourseWeave as a detached local Windows process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
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


def _probe(command: list[str], env: dict[str, str], code: str):
    """Probe interpreters without importing the app, reading config or starting jobs."""
    try:
        return subprocess.run(
            [*command, "-c", code], cwd=PROJECT_ROOT, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def select_python(project_root: Path = PROJECT_ROOT) -> tuple[list[str], dict[str, str], str] | None:
    """Prefer a usable project environment, then installed Python with working dependencies.

    Copied Windows venvs retain their original Python home. Reusing their package
    directory is allowed only with the same Python major/minor and after actual
    imports succeed, so incompatible binary extensions are never assumed usable.
    """
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    venv = project_root / ".venv"
    version = None
    config = venv / "pyvenv.cfg"
    if config.exists():
        match = re.search(r"(?m)^version\s*=\s*(\d+)\.(\d+)", config.read_text(encoding="utf-8", errors="replace"))
        if match:
            version = tuple(map(int, match.groups()))
    candidates = []
    override = environment.get("COURSEWEAVE_PYTHON")
    if override:
        candidates.append(([override], "指定的 Python"))
    candidates.extend([
        ([str(venv / "Scripts" / "python.exe")], "项目虚拟环境"),
        ([sys.executable], "当前 Python"),
    ])
    launcher = shutil.which("py")
    if launcher:
        if version:
            candidates.append(([launcher, f"-{version[0]}.{version[1]}"], "系统 Python Launcher"))
        candidates.append(([launcher, "-3"], "系统 Python Launcher"))
    for name in ("python", "python3"):
        executable = shutil.which(name)
        if executable and "windowsapps" not in executable.lower():
            candidates.append(([executable], "系统 Python"))

    seen = set()
    for command, label in candidates:
        identity = tuple(value.lower() for value in command)
        if identity in seen:
            continue
        seen.add(identity)
        result = _probe(command, environment, "import json, sys; print(json.dumps({'executable': sys.executable, 'version': list(sys.version_info[:2])}))")
        if result is None or result.returncode:
            continue
        try:
            metadata = json.loads(result.stdout)
            runtime_version = tuple(metadata["version"])
            executable = metadata["executable"]
        except (ValueError, KeyError, TypeError):
            continue
        if runtime_version < (3, 10):
            continue
        environments = [(environment, label)]
        packages = venv / "Lib" / "site-packages"
        if version == runtime_version and packages.is_dir() and label != "项目虚拟环境":
            reused = environment.copy()
            reused["PYTHONPATH"] = str(packages) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
            environments.append((reused, label + " + 兼容的项目依赖"))
        for child_env, description in environments:
            dependencies = _probe([executable], child_env,
                                  "import fastapi, uvicorn, sqlalchemy, pydantic, pypdf, fitz, rank_bm25, openai, httpx, multipart, dotenv")
            if dependencies is not None and dependencies.returncode == 0:
                return [executable], child_env, description
    return None


def environment_help() -> str:
    return (
        "未找到可以运行本项目的 Python 与依赖。复制的 .venv 可能仍引用原电脑的 Python 路径。\n"
        "请安装 Python 3.12，然后在项目目录新建环境（保留现有 .venv）：\n"
        "  py -3.12 -m venv .venv-local\n"
        "  .venv-local\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        '  set "COURSEWEAVE_PYTHON=%CD%\\.venv-local\\Scripts\\python.exe"\n'
        "  start-courseweave.cmd\n"
        "启动器不会自动安装依赖，也不会修改已有环境。"
    )


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

    runtime = select_python()
    if runtime is None:
        print(environment_help(), file=sys.stderr)
        return 1
    python_command, child_environment, description = runtime
    print(f"使用 {description}：{python_command[0]}")

    RUNTIME_DIR.mkdir(exist_ok=True)
    creation_flags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
    )
    command = [
        *python_command,
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
            env=child_environment,
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
