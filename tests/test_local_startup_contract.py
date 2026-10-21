from pathlib import Path
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("courseweave_local_launcher", ROOT / "scripts" / "start_local.py")
launcher_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher_module)


class LocalStartupContractTests(unittest.TestCase):
    def test_all_local_entrypoints_use_port_8001(self):
        launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")
        backend_main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        vite_config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_PORT = 8001", launcher)
        self.assertIn('os.getenv("PORT", "8001")', backend_main)
        self.assertIn("localhost:8001", vite_config)

    def test_launcher_waits_for_health_and_detaches_cleanly(self):
        launcher = (ROOT / "scripts" / "start_local.py").read_text(encoding="utf-8")

        self.assertIn("/api/health", launcher)
        self.assertIn("subprocess.DETACHED_PROCESS", launcher)
        self.assertIn("subprocess.CREATE_NO_WINDOW", launcher)
        self.assertIn("STDERR_PATH", launcher)

    def test_broken_copied_venv_falls_back_only_to_compatible_working_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            packages = project / ".venv" / "Lib" / "site-packages"
            packages.mkdir(parents=True)
            (project / ".venv" / "pyvenv.cfg").write_text("home = C:\\old-user\\python\nversion = 3.12.4\n", encoding="utf-8")

            def probe(command, env, code):
                if command[0] == str(project / ".venv" / "Scripts" / "python.exe"):
                    return subprocess.CompletedProcess(command, 1, "", "Python home missing")
                if "sys.version_info" in code:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"executable": "working-python.exe", "version": [3, 12]}), "")
                usable = env.get("PYTHONPATH", "").split(os.pathsep)[0] == str(packages)
                return subprocess.CompletedProcess(command, 0 if usable else 1, "", "")

            with patch.dict(os.environ, {}, clear=True), patch.object(launcher_module.shutil, "which", return_value=None), \
                 patch.object(launcher_module, "_probe", side_effect=probe):
                command, env, description = launcher_module.select_python(project)
            self.assertEqual(command, ["working-python.exe"])
            self.assertEqual(env["PYTHONPATH"], str(packages))
            self.assertIn("兼容", description)

    def test_incompatible_python_does_not_receive_copied_binary_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            packages = project / ".venv" / "Lib" / "site-packages"
            packages.mkdir(parents=True)
            (project / ".venv" / "pyvenv.cfg").write_text("version = 3.12.4\n", encoding="utf-8")
            seen_envs = []

            def probe(command, env, code):
                seen_envs.append(env)
                if "sys.version_info" in code:
                    return subprocess.CompletedProcess(command, 0, json.dumps({"executable": "python313.exe", "version": [3, 13]}), "")
                return subprocess.CompletedProcess(command, 1, "", "dependencies unavailable")

            with patch.dict(os.environ, {}, clear=True), patch.object(launcher_module.shutil, "which", return_value=None), \
                 patch.object(launcher_module, "_probe", side_effect=probe):
                self.assertIsNone(launcher_module.select_python(project))
            self.assertTrue(all(str(packages) not in env.get("PYTHONPATH", "") for env in seen_envs))

    def test_probe_handles_invalid_interpreter_without_importing_application(self):
        with patch.object(launcher_module.subprocess, "run", side_effect=OSError("missing executable")):
            self.assertIsNone(launcher_module._probe(["missing.exe"], {}, "import sys"))
        text = launcher_module.environment_help()
        self.assertIn(".venv-local", text)
        self.assertIn("COURSEWEAVE_PYTHON", text)
        self.assertNotIn("Administrator", text)

    def test_cmd_can_bootstrap_without_the_copied_venv(self):
        script = (ROOT / "start-courseweave.cmd").read_text(encoding="utf-8")
        self.assertIn("COURSEWEAVE_PYTHON", script)
        self.assertIn('py -3 -c "import sys"', script)
        self.assertIn('python -c "import sys"', script)
        self.assertIn('exit /b %courseweave_exit_code%', script)


if __name__ == "__main__":
    unittest.main()
