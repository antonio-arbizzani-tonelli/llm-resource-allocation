"""Fresh-process checks for package loading and mechanism exports."""

from pathlib import Path
import subprocess
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


class ImportBoundaryTests(unittest.TestCase):
    def run_fresh(self, code: str) -> None:
        result = subprocess.run(
            [sys.executable, "-I", "-c",
             f"import sys; sys.path.insert(0, {str(SOURCE_ROOT)!r});\n{code}"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_packages_do_not_load_scientific_or_solver_modules(self):
        for package in ("math", "optimization", "validation"):
            with self.subTest(package=package):
                self.run_fresh(
                    f"import llm_resource_allocation.{package}\n"
                    "assert not any(name.startswith(('pyomo', 'highspy')) "
                    "for name in sys.modules)\n"
                    f"assert not any(name.startswith('llm_resource_allocation.{package}.') "
                    "for name in sys.modules)\n"
                )

    def test_stage2_imports_work_in_both_orders(self):
        modules = (
            "llm_resource_allocation.validation.stage2",
            "llm_resource_allocation.optimization.stage2_run",
        )
        for order in (modules, modules[::-1]):
            with self.subTest(order=order):
                self.run_fresh("\n".join(f"import {module}" for module in order))

    def test_budget_does_not_load_optimization_or_validation(self):
        self.run_fresh(
            "from llm_resource_allocation.math.budget import BudgetDiagnostic\n"
            "assert BudgetDiagnostic(60, 20, 10, 100).slack == 10\n"
            "assert not any(name.startswith(('llm_resource_allocation.optimization', "
            "'llm_resource_allocation.validation', 'pyomo', 'highspy')) "
            "for name in sys.modules)\n"
        )

    def test_configured_validators_do_not_load_solver_backends(self):
        self.run_fresh(
            "from llm_resource_allocation.validation.placement import PlacementValidator\n"
            "from llm_resource_allocation.validation.stage2 import Stage2Validator\n"
            "assert not any(name.startswith(('pyomo', 'highspy')) "
            "for name in sys.modules)\n"
        )

    def test_mechanism_exports_share_the_defining_module_objects(self):
        owners = {
            "m1": (
                "M1ConfigurationDiagnostic",
                "M1SelectionResult",
                "select_minimum_feasible_parallelism",
            ),
            "m2": (
                "M2CandidateEvaluation",
                "M2ConfigurationEvidence",
                "M2CoverageLimiter",
                "M2EffectiveCoverageDiagnostic",
                "M2EvaluationInputs",
                "M2MarginalCostBreakdown",
                "M2UnrankableReason",
                "compute_m2_effective_coverage",
                "compute_m2_marginal_cost",
                "evaluate_m2_candidate",
                "rank_m2_candidates",
            ),
            "m3": (
                "M3ConfigurationDiagnostic",
                "M3EvaluationState",
                "M3NoUpgradeReason",
                "M3UpgradeResult",
                "select_m3_parallelism_upgrade",
            ),
        }
        self.run_fresh(
            "import importlib\n"
            "import importlib.util\n"
            "import llm_resource_allocation.algorithms as algorithms\n"
            "assert importlib.util.find_spec(\n"
            "    'llm_resource_allocation.algorithms.mechanisms') is None\n"
            f"owners = {owners!r}\n"
            "for owner, names in owners.items():\n"
            "    defining_module = importlib.import_module(\n"
            "        f'llm_resource_allocation.algorithms.{owner}')\n"
            "    for name in names:\n"
            "        value = getattr(defining_module, name)\n"
            "        assert name in algorithms.__all__, name\n"
            "        assert getattr(algorithms, name) is value, name\n"
            "        assert value.__module__ == defining_module.__name__, name\n"
            "assert not any(name.startswith(('pyomo', 'highspy')) "
            "for name in sys.modules)\n"
        )


if __name__ == "__main__":
    unittest.main()
