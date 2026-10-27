# Tunisia route-level flood-risk prototype

A flood-risk prototype for road segments (pilot: Nabeul). It has two parts:

- a **terrain model** that ranks roads by how early they flood;
- a **provisional rain trigger** that decides when that ranking becomes an alert.

It is a prototype. **It is not an operationally validated flood-warning system.**

## Current system

| Part | File | Status |
|---|---|---|
| Terrain model: ranks road segments inside a zone by flood susceptibility, from terrain only | `models/final/v2_terrain.joblib` | evaluated offline with leave-one-event-out cross-validation across 13 Mediterranean floods and leave-one-country-out across 6 countries; not tested in operational conditions |
| Rain trigger: an alert when a zone's rain reaches **44 mm in a rolling 24 h window** | `models/final/trigger.json` | **provisional** |

Alert levels are a budget per zone: the riskiest 10 % of a zone's roads are Moderate, 2 % High and 0.5 % Very
high, once the trigger is on.

The terrain model and the rain trigger were evaluated on different scopes:

- The 44 mm threshold was fitted on NASA IMERG Final rain over 13 Mediterranean floods.
- It was then tested, unchanged, on Tunisian floods from press reports, once with IMERG Final and once with the
  available INM synoptic gauges.
- Both Tunisian tests are **exploratory**. Neither validates the threshold for operation or tests a real-time
  rain feed.

How to call the model, its inputs and outputs, and the rules for the application: [docs/MODEL_CONTRACT.md](docs/MODEL_CONTRACT.md).

## Documentation

| File | Content |
|---|---|
| [docs/MODEL_CONTRACT.md](docs/MODEL_CONTRACT.md) | system design, inputs and outputs, PostGIS, application rules, measured performance |
| [docs/TRIGGER_VALIDATION.md](docs/TRIGGER_VALIDATION.md) | protocol to validate the trigger on gauge records |
| [pipeline_v2_temporel.ipynb](pipeline_v2_temporel.ipynb) | why terrain only: rain rebuilt with only what is known at prediction time, ablations, label audit |
| [reports/med_trigger/README.md](reports/med_trigger/README.md) | Mediterranean study that set the 44 mm threshold |
| [reports/tn_trigger_imerg/README.md](reports/tn_trigger_imerg/README.md) | Tunisian test with NASA IMERG Final satellite rain (exploratory) |
| [reports/tn_trigger_synop/README.md](reports/tn_trigger_synop/README.md) | Tunisian test with INM synoptic gauges (exploratory) |
| [docs/PROTOTYPE_HISTORY.md](docs/PROTOTYPE_HISTORY.md) | the former root README: earlier stages, sources and commands |

## Project history

The design came out of successive stages:

1. A synthetic-data prototype, which tested the pipeline only.
2. Training on New York street-flooding reports, with a transfer test on Nabeul 2018.
3. A Mediterranean inventory of 13 Copernicus floods, with NASA IMERG rain. It gave the terrain model and the 44 mm threshold.
4. The Tunisian trigger tests.

Results of the earlier stages are not a validation of the current system. In particular, their alert levels
(target recalls of 90, 70 and 35 %) are not those of the current system.

## Install

```
pip install -r requirements.txt
```

Raw downloads (`data/raw/`) are cached locally. Some of them are not in git: Earthdata cookies, the IMERG cache
and the NOAA station files.
