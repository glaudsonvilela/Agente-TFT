"""Exercise the guided wizard's actual Tk layout on a Windows desktop."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hm45_setup import SetupWindow


@unittest.skipUnless(sys.platform == "win32", "Windows desktop required")
class SetupWindowSmoke(unittest.TestCase):
    def test_headless_option_and_all_steps_render(self):
        with patch.object(SetupWindow, "_start"):
            window = SetupWindow(Path("C:/AgenteTFT-HUD-HM4-Auto.exe"))
            try:
                window.root.update_idletasks()
                self.assertTrue(window.headless_option.winfo_ismapped())
                window._show(1)
                window.root.update_idletasks()
                self.assertFalse(window.headless_option.winfo_ismapped())
                window.vm_ready = True
                window._show(2)
                window.root.update_idletasks()
                self.assertEqual(window.step, 2)
            finally:
                window.root.destroy()


if __name__ == "__main__":
    unittest.main()
