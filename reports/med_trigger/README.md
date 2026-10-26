# Rain trigger study (`python -m flood_risk.real.trigger`)

Rain spells in the 120 days before each of the 13 Copernicus floods, 28 zones, NASA IMERG Final daily
rain at the wettest cell of each zone. Flood spell = the mapped flood; dry spell = any other spell >= 5 mm
(no Copernicus activation, so no *mapped* flood).

| Indicator | Flood spells (median) | Dry spells (median) | Threshold (leave-one-event-out) | Flood zones caught | Dry spells triggered |
|---|---|---|---|---|---|
| **Max daily rain** | 74 mm | 13 mm | **44-52 mm** | **88 % (25/28)** | **5/126** |
| Max 2-day rain | 83 mm | 15 mm | 52-66 mm | 85 % | 7/126 |
| Spell total | 122 mm | 18 mm | 67-83 mm | 85 % | 14/126 |

Chosen: **44 mm in 24 h** (`models/final/trigger.json`, status *provisional*), about 0.65 trigger per zone
and year without a mapped flood. Missed: western Attica 2019 (28-30 mm/day in IMERG). One "false" trigger
(Heraklion, 20 Oct 2020) matches a documented flood that Copernicus did not map.

| Threshold | Flood zones caught | Dry spells triggered | Triggers / zone / year without mapped flood |
|---|---|---|---|
| 30 mm | 93 % | 13 | 1.4 |
| 40 mm | 93 % | 7 | 0.75 |
| 45 mm | 86 % | 6 | 0.65 |
| 50 mm | 86 % | 4 | 0.43 |
| 60 mm | 75 % | 2 | 0.22 |

Limits: 13 events; IMERG Final (published months later) while operation will use IMERG Early, radar or
INM gauges; a dry spell means "no mapped flood", not "no flood". Re-check on Tunisian gauge records.

## Calendar day versus rolling 24 h window

The threshold was fitted on calendar days (00-24 UTC). In operation, `predict.py` compares it with a rolling
window from t - 12 h to t + 12 h. A calendar day is one of these 24 h windows, so the rolling value is
**always at least as large**. On the 28 flood storms (`window_check.csv`, IMERG half-hourly):

- the ratio is ×1.03 in median and up to ×1.7, when a storm straddles midnight (western Attica 2019, Sicily 2023, Aude);
- flood zones above 44 mm go from 24 to **27 out of 28** (western Attica 2019 is now caught at 47.6 mm).

The trigger therefore fires **earlier and more often** than in the study. The extra false triggers
cannot be measured here, because dry spells were only downloaded as daily totals. That must be checked on
Tunisian gauge records before production.
