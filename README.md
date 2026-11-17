[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/terserahmauditulisapa/makefun-gta6-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/terserahmauditulisapa/makefun-gta6-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI Twitch CCU forecast — variant H

Log-scale quantile forecaster for `gta6-twitch-ccu-forecast-01`: from the
first hour's Twitch viewer print it forecasts hours 2–24 of release day as
five quantiles per hour.

How it works: anchor on the hour-1 print. Every past launch in the case's
own comparables contributes its release-day hourly curve as log-ratios to
its own hour-1 print. Per hour, the median log-ratio across launches is the
median forecast, and the spread is adaptive per hour — the 5/25/75/95%
quantiles of the log-ratios actually observed at that hour, centred on the
median and lightly smoothed across neighbouring hours. Stable hours get a
narrow band, wild hours a wide one, and the upper tail runs longer than the
lower tail, as the launches show. Only launches whose hour-1 print is within
a factor of 18 of this case's print are pooled: a launch that started from a
trickle behaves nothing like one that started big.

Run: `python3 main.py` reads every `*.in` in `$MAKEFUN_INPUT_DIR` (else
`/input`) and writes one `*.out` per case to `$MAKEFUN_OUTPUT_DIR` (else
`/output`). Python 3.13 standard library only, no network, deterministic.

Local validation (leave-one-out over the kit's 37 comparable launches with
a full release day): pinball loss 0.428 vs 0.930 for the flat house
baseline on the same synthetic cases.
