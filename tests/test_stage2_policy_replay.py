"""Hand-derived denominators for the separately recorded policy replay."""

import unittest
from scripts.replay_stage2_policy import summarize, paired_bootstrap


def row(job, old, frozen, baseline, adapted, solver=None):
    return {"job":job, "old_usable":old, "frozen_feasible":frozen,
            "frozen_cost_usd":baseline, "adapted_cost_usd":adapted,
            "independently_feasible":adapted is not None,
            "solver_objective":adapted if solver is None else solver,
            "independent_objective":adapted, "absolute_tolerance":1e-8}


class PolicyReplayAggregationTests(unittest.TestCase):
    def test_failed_baseline_is_excluded_from_cost_and_recovery_uses_all_failures(self):
        rows = [row("a",True,True,100.0,90.0),
                row("b",True,False,None,20.0),
                row("c",False,False,None,None)]
        result = summarize(rows,0.0,0,37)
        self.assertEqual((result["attempted"],result["usable"]),(3,2))
        self.assertEqual((result["frozen_failures"],result["recovered"]),(2,1))
        self.assertEqual(result["recovery_fraction"],0.5)
        self.assertEqual(result["paired_scenarios"],1)
        self.assertEqual(result["paired_baseline_cost_sum_usd"],100.0)
        self.assertEqual(result["paired_adapted_cost_sum_usd"],90.0)
        self.assertEqual(result["paired_reduction_fraction"],0.1)

    def test_cost_reduction_is_ratio_of_sums_and_bootstrap_keeps_pairs(self):
        rows = [row("a",True,True,100.0,50.0), row("b",True,True,300.0,300.0)]
        result = summarize(rows,0.0,0,37)
        self.assertEqual(result["paired_reduction_fraction"],0.125)
        identical = [row("a",True,True,100.0,90.0), row("b",True,True,300.0,270.0)]
        result = paired_bootstrap(identical,100,37,True)
        self.assertEqual(result["ci95"],[0.1,0.1])
        self.assertEqual(result["units"],2)
        self.assertEqual(result,paired_bootstrap(identical,100,37,True))


if __name__ == "__main__":
    unittest.main()
