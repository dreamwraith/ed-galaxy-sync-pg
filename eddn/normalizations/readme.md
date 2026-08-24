# Normalization Mappings Architecture

This directory contains modular YAML normalization dictionaries loaded by `NormalizerManager` for $O(1)$ case-, space-, and punctuation-insensitive token resolution across the Elite Dangerous data pipeline.

---

## Directory Structure

```text
eddn/normalizations/
├── direct/                       # Active streaming direct normalization lookup tables
│   ├── allegiances.yaml
│   ├── carrier_docking_access.yaml
│   ├── commodities.yaml
│   ├── commodity_categories.yaml
│   ├── economies.yaml
│   ├── faction_states.yaml
│   ├── genuses.yaml
│   ├── governments.yaml
│   ├── materials.yaml
│   ├── module_categories.yaml
│   ├── modules.yaml
│   ├── planet_classes.yaml
│   ├── poi_types.yaml
│   ├── reserve_levels.yaml
│   ├── ring_types.yaml
│   ├── securities.yaml
│   ├── ships.yaml
│   ├── signal_types.yaml
│   ├── species_variants_reference.yaml
│   ├── star_types.yaml
│   ├── station_types.yaml
│   └── terraform_states.yaml
├── multifield/                   # Multi-attribute entity definitions (NamedTuple records)
│   └── scenarios.yaml
└── disabled/                     # Reference / future-use mappings (excluded from runtime memory)
    └── direct/
        ├── crimes.yaml
        ├── docking_denied_reasons.yaml
        ├── happiness.yaml
        ├── passenger_types.yaml
        ├── ranks_combat.yaml
        ├── ranks_cqc.yaml
        ├── ranks_empire.yaml
        ├── ranks_exploration.yaml
        ├── ranks_federation.yaml
        └── ranks_trade.yaml
```

---

## Active Streaming Mappings vs. Future-Use Reference Mappings

### 1. Active Real-Time Stream Mappers (`eddn/normalizations/direct/` & `multifield/`)

These files are directly loaded into memory by `NormalizerManager` during live EDDN message processing (e.g. `journal_jump`, `journal_scan`, `journal_station`, `commodity`, `shipyard`, `fss_signal` transformers):

* **Galaxy State Enums**: `allegiances.yaml`, `economies.yaml`, `governments.yaml`, `securities.yaml`, `faction_states.yaml`, `terraform_states.yaml`.
* **Outfitting & Markets**: `commodities.yaml`, `commodity_categories.yaml`, `modules.yaml`, `module_categories.yaml`, `materials.yaml`, `ships.yaml`.
* **Celestial & Exobiology**: `planet_classes.yaml`, `star_types.yaml`, `ring_types.yaml`, `reserve_levels.yaml`, `genuses.yaml`, `species_variants_reference.yaml`.
* **Stations & Scenarios**: `station_types.yaml`, `carrier_docking_access.yaml`, `signal_types.yaml`, `poi_types.yaml`, `scenarios.yaml`.

### 2. Reference Mappers (`eddn/normalizations/disabled/direct/`)

Stored in `disabled/direct/` so they are **not** loaded into runtime memory by default. These dictionaries provide canonical mappings matching `FDevIDs` for future schema additions, companion queries, and offline analyses:

* **`happiness.yaml`**: Faction happiness bands (`HappinessBand1` through `HappinessBand5` $\rightarrow$ `Elated` to `Despondent`).
* **`ranks_combat.yaml`**, **`ranks_trade.yaml`**, **`ranks_exploration.yaml`**, **`ranks_cqc.yaml`**, **`ranks_empire.yaml`**, **`ranks_federation.yaml`**: Commander progressions across Combat, Trade, Exploration, CQC, Empire Naval, and Federation Naval ranks (1-to-1 with FDevIDs rank CSVs).
* **`crimes.yaml`**: Flight and on-foot Odyssey crime types.
* **`docking_denied_reasons.yaml`**: Station docking denial rejection reasons.
* **`passenger_types.yaml`**: Passenger cabin demographic and VIP archetypes.

---

## Dynamic Customization

All YAML files in this directory are loaded dynamically at runtime. Users can add new variants or adjust canonical labels without modifying python source code.
