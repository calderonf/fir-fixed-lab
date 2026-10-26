"""Pruebas del pequeño lanzador que se empaqueta para Windows."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import socket
import unittest


LAUNCHER_PATH = (
    Path(__file__).parents[1] / "packaging" / "windows" / "fir_fixed_lab_launcher.py"
)
SPEC = spec_from_file_location("fir_fixed_lab_launcher", LAUNCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
launcher = module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_selects_a_loopback_port_that_can_be_bound(self) -> None:
        port = launcher._available_local_port()
        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))

    def test_development_command_runs_the_launcher_script_as_child(self) -> None:
        command = launcher._server_command(45678)
        self.assertEqual(command[-2:], ["--serve", "45678"])
        self.assertTrue(command[-3].endswith("fir_fixed_lab_launcher.py"))


if __name__ == "__main__":
    unittest.main()
