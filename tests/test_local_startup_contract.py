from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
