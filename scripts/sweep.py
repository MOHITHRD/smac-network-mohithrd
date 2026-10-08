"""
sweep.py - empirical parameter tuning for the M3 severance threshold.

Section 3.1.3 flags rho (and delta) as parameters to be tuned during MVP
development from the observed distribution in the study area, rather than
fixed a priori. This is that tuning.

    python scripts/sweep.py

Produces:
  1. the observed severance-ratio distribution over all stops
  2. rejection rate as a function of rho
  3. rejection rate as a function of tau, for reference
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import matching as M


def clear():
    M.match_all.cache_clear()


def observed_ratios():
    """The worst severance ratio near each stop, regardless of threshold."""
    clear()
    saved = M.RHO
    M.RHO = float("inf")          # nothing rejected; we just want the ratios
    rows = []
    for stop in M.load_stops():
        m = M.match_m3(stop)
        rows.append((stop["stop_id"], stop["stop_name"][:38],
                     m.straight_line_m, m.severance_ratio))
    M.RHO = saved
    clear()
    return rows


def sweep_rho(values):
    out = []
    saved = M.RHO
    for r in values:
        M.RHO = r
        clear()
        s = M.statistics("M3")
        out.append((r, s["matched"], s["unmatched"], s["unmatched_rate"]))
    M.RHO = saved
    clear()
    return out


def sweep_tau(values):
    out = []
    saved = M.TAU
    for t in values:
        M.TAU = t
        clear()
        s2, s3 = M.statistics("M2"), M.statistics("M3")
        out.append((t, s2["unmatched"], s3["unmatched"]))
    M.TAU = saved
    clear()
    return out


if __name__ == "__main__":
    print("=" * 74)
    print("  OBSERVED SEVERANCE RATIOS  (network distance / straight-line, "
          "nearest pair)")
    print("=" * 74)
    rows = observed_ratios()
    rated = sorted([r for r in rows if r[3] is not None],
                   key=lambda r: -r[3])
    none_ct = sum(1 for r in rows if r[3] is None)
    print(f"  {'stop_id':<9} {'name':<38} {'d(m)':>6} {'ratio':>8}")
    print("  " + "-" * 66)
    for sid, name, d, ratio in rated:
        print(f"  {sid:<9} {name:<38} {d:6.0f} {ratio:8.1f}")
    print(f"\n  {none_ct} stops had no candidate pair within "
          f"{M.SEVERANCE_PAIR_MAX_M} m (no severance test applied).")

    print()
    print("=" * 74)
    print("  REJECTION RATE vs RHO      (tau fixed at "
          f"{M.TAU} m, {len(M.load_stops())} stops)")
    print("=" * 74)
    print(f"  {'rho':>6} {'matched':>9} {'rejected':>9} {'rate':>8}")
    print("  " + "-" * 36)
    for r, ok, bad, rate in sweep_rho([2, 3, 4, 5, 6, 8, 10, 15, 20, 50]):
        print(f"  {r:6.0f} {ok:9} {bad:9} {rate * 100:7.1f}%")

    print()
    print("=" * 74)
    print("  UNMATCHED vs TAU")
    print("=" * 74)
    print(f"  {'tau(m)':>7} {'M2 unmatched':>14} {'M3 unmatched':>14}")
    print("  " + "-" * 38)
    for t, u2, u3 in sweep_tau([25, 50, 75, 100, 150, 200, 300, 400]):
        print(f"  {t:7} {u2:14} {u3:14}")
    print("=" * 74)