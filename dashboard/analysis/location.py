"""Fixed-budget maximum coverage; retain feasible greedy incumbent on solver timeout."""
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import csr_matrix, hstack, vstack, eye


def solve_locations(distances, existing, weights, budgets, radius=240, nested=True):
    uncovered = existing > radius
    cover = distances[:, uncovered] <= radius
    w = weights[uncovered]
    # Equal coverage signatures are equivalent for the primary MCLP objective.
    # Keep the one with least covered-population walking distance as tie-break.
    groups = {}
    for i, row in enumerate(cover):
        if not row.any():
            continue
        key = np.packbits(row).tobytes()
        score = float((distances[i, uncovered][row] * w[row]).sum())
        if key not in groups or score < groups[key][1]:
            groups[key] = (i, score)
    candidates = np.array([v[0] for v in groups.values()], dtype=int)
    C = cover[candidates]
    if len(C) < max(budgets):
        raise ValueError('Not enough distinct feasible candidates')
    nc, nd = C.shape
    matrix = vstack([hstack([-csr_matrix(C.T, dtype=float), eye(nd)]),
                     csr_matrix(np.r_[np.ones(nc), np.zeros(nd)][None, :])]).tocsr()
    result, audit, fixed = {}, [], []
    for k in sorted(budgets):
        greedy = list(fixed)
        covered = C[greedy].any(axis=0) if greedy else np.zeros(len(w), dtype=bool)
        while len(greedy) < k:
            gain = C[:, ~covered] @ w[~covered]
            gain[greedy] = -1
            j = int(np.argmax(gain)); greedy.append(j); covered |= C[j]
        incumbent = np.array(greedy)
        lower = np.zeros(nc + nd); lower[fixed] = 1
        value = lambda selected: float(w[C[selected].any(axis=0)].sum())
        solved = milp(c=np.r_[np.zeros(nc), -w], integrality=np.ones(nc + nd),
                      bounds=Bounds(lower, 1),
                      constraints=LinearConstraint(matrix, np.r_[np.full(nd, -np.inf), k], np.r_[np.zeros(nd), k]),
                      options={'time_limit': 45, 'mip_rel_gap': 0.0001})
        chosen = np.flatnonzero(solved.x[:nc] > .5) if solved.x is not None else incumbent
        if len(chosen) != k or not set(fixed).issubset(chosen) or value(chosen) < value(incumbent) - 1e-7:
            chosen = incumbent
        result[k] = candidates[chosen]
        gap = getattr(solved, 'mip_gap', None)
        audit.append(dict(stops=k, method='nested MCLP MILP' if nested else 'MCLP MILP', fixedStops=len(fixed), solverStatus=int(solved.status),
                          optimal=bool(solved.status == 0), gap=None if gap is None else float(gap),
                          candidateCount=nc, rawCandidateCount=len(distances),
                          greedyAddedPopulation=value(incumbent), selectedAddedPopulation=value(chosen)))
        print('MCLP', audit[-1], flush=True)
        if nested:
            fixed = chosen.tolist()
    return result, audit
