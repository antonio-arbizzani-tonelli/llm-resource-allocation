"""Measure configuration and statistical bookkeeping without changing decisions."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("openmp_diagnostics",ROOT/"scripts/run_openmp_diagnostics.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class DiagnosticsTests(unittest.TestCase):
    def test_complete_grid_and_unique_keys(self):
        configs=module.configurations(16)
        self.assertEqual(len(configs),585)
        self.assertEqual(len({module.key(c) for c in configs}),585)
        self.assertEqual({c["threads"] for c in configs},set(range(1,17)))
        self.assertEqual({c["schedule"] for c in configs},{"static","dynamic","guided"})
        self.assertEqual({c["chunk"] for c in configs},{1,2,4})

    def test_interventions_keep_own_baseline(self):
        configs=module.configurations(16)
        for c in configs:
            if c["sorted"] or c["arena"]:
                self.assertIn({**c,"threads":1},configs)

if __name__=="__main__": unittest.main()
