from __future__ import annotations

import ast
import unittest
from pathlib import Path


class WindowsLauncherTests(unittest.TestCase):
    def test_double_click_launcher_bootstraps_and_starts_streamlit(self) -> None:
        launcher = Path("SPUSTIT_STRATEGY_QUANT.bat").read_text(encoding="utf-8")
        self.assertIn(r".venv\Scripts\python.exe", launcher)
        self.assertIn("-m pip install", launcher)
        self.assertIn("-m streamlit run app.py", launcher)
        self.assertIn("MetaTrader 5", launcher)

    def test_data_manager_page_is_valid_python_and_read_only(self) -> None:
        source = Path("pages/1_Data_Manager.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("MT5DataSource", source)
        self.assertIn("manager.import_mt5", source)
        self.assertIn("discover_mt5_terminals", source)
        self.assertNotIn("order_send", source)


if __name__ == "__main__":
    unittest.main()
