"""Compare the MCLP solver to exhaustive enumeration on a greedy counterexample."""
import itertools
import unittest
import numpy as np
from location import solve_locations


class LocationTest(unittest.TestCase):
    def test_weighted_optimum_existing_supply_and_duplicate_candidates(self):
        # Greedy picks A (12) then B/C (+5); optimum B+C covers 22.
        distance = np.array([[10, 10, 999, 999, 10],
                             [10, 999, 10, 999, 999],
                             [999, 10, 999, 10, 999],
                             [20, 20, 999, 999, 20],
                             [999, 999, 999, 999, 10]])
        existing = np.array([999, 999, 999, 999, 0])
        weights = np.array([6, 6, 5, 5, 100])
        selected, audit = solve_locations(distance, existing, weights, [1, 2])
        for k in [1, 2]:
            def objective(indices):
                covered = (distance[list(indices)] <= 240).any(axis=0) & (existing > 240)
                return weights[covered].sum()
            best = max(objective(c) for c in itertools.combinations(range(len(distance)), k))
            self.assertEqual(len(selected[k]), k)
            self.assertEqual(objective(selected[k]), best)
        self.assertEqual(selected[1].tolist(), [0])
        self.assertEqual(set(selected[2]), {1, 2})
        self.assertGreater(audit[1]['selectedAddedPopulation'], audit[1]['greedyAddedPopulation'])


if __name__ == '__main__':
    unittest.main()
