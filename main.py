"""Variant H: log-scale quantile forecaster for gta6-twitch-ccu-forecast-01.

Model, in one paragraph: anchor on the hour-1 print p1. For every past
launch in the case's own comparables, take its release-day hourly curve and
express each hour as a log-ratio to that launch's hour-1 print. For each
forecast hour, the median log-ratio across launches is the median forecast
(the middle path through the launches: early hours dip a little, later
hours rise as the rest of the world unlocks), and the spread is adaptive per
hour: the 5/25/75/95% quantiles of the log-ratios actually observed at that
hour, centred on the median, lightly smoothed across neighbouring hours.
Stable hours get a narrow band, wild hours a wide one; the upper tail is
allowed to run much longer than the lower tail, because that is what the
launches show. Only launches whose hour-1 print is within a factor of 18 of
this case's p1 are pooled: a launch that started from a trickle behaves
nothing like one that started big, and pooling them blurs both. Everything
is fitted at runtime from the comparables inside the case file itself, so
the program needs no network and no shipped data; if a case carries too few
usable curves it falls back to a table of the same shape fitted once from
the kit's comparable launches (baked in below), and only to a flat forecast
when it carries none at all.

Python 3.13 standard library only. Deterministic: no randomness, no clock,
no dict-order dependence; sorted inputs throughout.
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# A comparable joins the pool only when its hour-1 print is within this
# factor of the case's own hour-1 print (either direction, in log space).
SCALE_WINDOW = 18.0
# Below this many pooled launches, fall back to every usable comparable.
MIN_POOL = 5
# Median shrink toward flat (1.0 = the pooled median, unshrunk) and spread
# multiplier (1.0 = the observed spread, as is). Both were picked by
# leave-one-out pinball over the kit's comparable launches.
MEDIAN_SHRINK = 1.0
SPREAD_MULT = 1.0
# Safety rails on the log-quantiles, far outside anything the data shows.
LOG_MIN = -12.0
LOG_MAX = 12.0

# Fallback table, fitted once from the kit's 37 comparable launches with a
# full release day (median log-ratio to hour 1, and each level's deviation
# from that median, per hour 2..24). Used only when a case carries too few
# usable curves to fit at runtime; deviations are smoothed on use, exactly
# as the runtime fit smooths them.
MED_FALLBACK = [
    -0.1376, -0.2829, -0.3100, -0.2916, -0.2377, -0.2201, -0.1066, -0.1259,
    -0.0925, -0.0745, -0.0223, 0.0574, 0.1661, 0.4176, 0.5022, 0.5713,
    0.6681, 0.8761, 0.8635, 0.8460, 0.8322, 0.7803, 0.7122,
]
DEV_FALLBACK = {
    0.05: [
        -0.2542, -0.7228, -0.5718, -0.9223, -0.9315, -0.8502, -0.8876,
        -0.8262, -0.8011, -0.8549, -0.8761, -0.7387, -0.7248, -0.8954,
        -0.9179, -0.9064, -0.8663, -0.9610, -0.9886, -0.9612, -0.9873,
        -1.0376, -1.0425,
    ],
    0.25: [
        -0.1196, -0.1944, -0.3316, -0.1947, -0.4385, -0.3211, -0.4871,
        -0.5567, -0.5846, -0.6183, -0.5429, -0.5328, -0.4657, -0.6699,
        -0.5843, -0.3910, -0.4345, -0.6457, -0.6176, -0.6013, -0.6315,
        -0.7274, -0.6047,
    ],
    0.5: [0.0] * 23,
    0.75: [
        0.1329, 0.2138, 0.1895, 0.2173, 0.3046, 0.3313, 0.3298, 0.4074,
        0.3752, 0.5678, 0.6697, 0.8955, 0.9864, 1.0602, 1.4556, 1.5622,
        1.4943, 1.4434, 1.5469, 1.4953, 1.4608, 1.3358, 1.2330,
    ],
    0.95: [
        0.4771, 0.6642, 0.6611, 0.6938, 1.3223, 1.4232, 1.6467, 2.2974,
        3.7941, 3.8889, 3.9743, 4.5112, 4.8709, 4.7717, 4.8952, 5.1391,
        5.1076, 4.9417, 5.1362, 5.2345, 5.2027, 5.1203, 5.1078,
    ],
}


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def quantile(sorted_vals, q):
    """Linear-interpolated empirical quantile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - pos) + sorted_vals[hi] * (pos - lo)


def smooth3(vals):
    """Three-point moving average (edges average their two neighbours)."""
    out = []
    for i in range(len(vals)):
        near = [vals[j] for j in (i - 1, i, i + 1) if 0 <= j < len(vals)]
        out.append(sum(near) / len(near))
    return out


def release_day_curves(case):
    """[(name, hour1, [hour2..hour24])] for comparables with a full,
    strictly positive release day. Sorted by name so fitting is stable."""
    curves = []
    for comp in case.get("comparables") or []:
        try:
            start = parse_time(comp["day_start"])
            by_hour = {}
            for row in comp.get("hourly") or []:
                hour = int((parse_time(row["from"]) - start).total_seconds() // 3600) + 1
                if 1 <= hour <= 24:
                    by_hour[hour] = row["viewers"]
            if len(by_hour) == 24 and all(v > 0 for v in by_hour.values()):
                curves.append((comp.get("name", ""), by_hour[1],
                               [by_hour[h] for h in range(2, 25)]))
        except (KeyError, TypeError, ValueError):
            continue
    curves.sort(key=lambda c: c[0])
    return curves


def fit_table(curves):
    """Per forecast hour: median log-ratio plus each level's deviation from
    that median, deviations smoothed across neighbouring hours."""
    medians = []
    devs = {tau: [] for tau in LEVELS}
    for i in range(23):  # hours 2..24
        xs = sorted(math.log(v[i] / v1) for _, v1, v in curves)
        med = quantile(xs, 0.5)
        medians.append(med)
        for tau in LEVELS:
            devs[tau].append(quantile(xs, tau) - med)
    for tau in LEVELS:
        devs[tau] = smooth3(devs[tau])
    return medians, devs


def hour_quantiles(p1, medians, devs, hour):
    idx = min(max(hour - 2, 0), 22)
    centre = MEDIAN_SHRINK * medians[idx]
    row = []
    for tau in LEVELS:
        lg = centre + SPREAD_MULT * devs[tau][idx]
        lg = min(max(lg, LOG_MIN), LOG_MAX)
        row.append(min(max(p1 * math.exp(lg), 1.0), 1e9))
    rounded = [round2(q) for q in row]
    for j in range(1, 5):  # rounding/clamping must never break monotonicity
        rounded[j] = max(rounded[j], rounded[j - 1])
    return rounded


def flat_quantiles(p1, hour):
    """Last-resort fallback: flat median, widening normal spread."""
    z = [-1.645, -0.674, 0.0, 0.674, 1.645]
    row = [round2(min(max(p1 * math.exp(zz * 0.15 * math.sqrt(hour - 1)), 1.0), 1e9))
           for zz in z]
    for j in range(1, 5):
        row[j] = max(row[j], row[j - 1])
    return row


def forecast_case(case):
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    p1 = max(1, first["viewers"]) if first is not None else 1
    hours = [row["hour"] for row in case.get("forecast") or []]
    if not hours:
        hours = list(range(2, 25))
    curves = release_day_curves(case)
    if len(curves) >= MIN_POOL:
        near = [c for c in curves
                if abs(math.log(c[1] / p1)) <= math.log(SCALE_WINDOW)]
        pool = near if len(near) >= MIN_POOL else curves
        medians, devs = fit_table(pool)
        rows = [{"hour": h, "q": hour_quantiles(p1, medians, devs, h)} for h in hours]
    elif curves:
        devs = {tau: smooth3(DEV_FALLBACK[tau]) for tau in LEVELS}
        rows = [{"hour": h, "q": hour_quantiles(p1, MED_FALLBACK, devs, h)}
                for h in hours]
    else:
        rows = [{"hour": h, "q": flat_quantiles(p1, h)} for h in hours]
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            forecast = forecast_case(case)
        except Exception:
            first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
            p1 = max(1, first["viewers"]) if first is not None else 1
            hours = [row["hour"] for row in case.get("forecast") or []]
            if not hours:
                hours = list(range(2, 25))
            forecast = {"hours": [{"hour": h, "q": flat_quantiles(p1, h)} for h in hours]}
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
