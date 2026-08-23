"""Unit tests for EDDN domain event transformers."""

import json

from eddn.transformers.commodity import CommodityTransformer
from eddn.transformers.fc_materials import FCMaterialsTransformer
from eddn.transformers.fss_signal import FSSSignalTransformer
from eddn.transformers.journal_jump import JournalJumpTransformer
from eddn.transformers.journal_scan import JournalScanTransformer
from eddn.transformers.journal_station import JournalStationTransformer
from eddn.transformers.shipyard import ShipyardTransformer


def test_jump_fsd_jump_emits_system_and_factions(sample_fsd_jump_payload: dict) -> None:
    """Validates JournalJumpTransformer transforms FSDJump into system and system_factions records."""
    transformer = JournalJumpTransformer()
    schema_ref = sample_fsd_jump_payload["$schemaRef"]
    header = sample_fsd_jump_payload["header"]
    message = sample_fsd_jump_payload["message"]

    assert transformer.can_handle(schema_ref, header, message) is True
    records = transformer.transform(schema_ref, header, message)

    assert len(records) == 3  # 1 system + 2 factions
    sys_rec = next(r for r in records if r.table_name == "systems")
    assert sys_rec.data["id64"] == 10477373803
    assert sys_rec.data["name"] == "Sol"
    assert sys_rec.data["coords"] == "(0.0, 0.0, 0.0)"
    assert sys_rec.data["population"] == 22780871769
    assert sys_rec.data["update_dtm"] == "2026-08-17T12:00:00Z"

    fac_recs = [r for r in records if r.table_name == "system_factions"]
    assert len(fac_recs) == 2
    assert fac_recs[0].data["name"] == "Mother Gaia"


def test_jump_carrier_jump_emits_station_and_system(sample_carrier_jump_payload: dict) -> None:
    """Validates CarrierJump events emit both the target system record and station carrier record."""
    transformer = JournalJumpTransformer()
    schema_ref = sample_carrier_jump_payload["$schemaRef"]
    header = sample_carrier_jump_payload["header"]
    message = sample_carrier_jump_payload["message"]

    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 2  # 1 system + 1 station

    sys_rec = next(r for r in records if r.table_name == "systems")
    assert sys_rec.data["id64"] == 109823485721
    assert sys_rec.data["name"] == "Colonia"

    sta_rec = next(r for r in records if r.table_name == "stations")
    assert sta_rec.data["market_id"] == 3706615552
    assert sta_rec.data["name"] == "RZZ-51F"
    assert sta_rec.data["carrierName"] == "ESB Tiberium Toke"
    assert sta_rec.data["distanceToArrival"] == 124.5


def test_jump_fss_discovery_scan_emits_system_body_count() -> None:
    """Validates FSSDiscoveryScan event creates system record with bodyCount."""
    transformer = JournalJumpTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "FSSDiscoveryScan",
        "timestamp": "2026-08-17T12:20:00Z",
        "SystemAddress": 10477373803,
        "SystemName": "Sol",
        "BodyCount": 42,
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "systems"
    assert records[0].data["bodyCount"] == 42


def test_scan_planet_calculates_gravity_and_subtype(sample_scan_body_payload: dict) -> None:
    """Validates JournalScanTransformer computes body_id64, surface gravity, and body_rings."""
    transformer = JournalScanTransformer()
    schema_ref = sample_scan_body_payload["$schemaRef"]
    header = sample_scan_body_payload["header"]
    message = sample_scan_body_payload["message"]

    assert transformer.can_handle(schema_ref, header, message) is True
    records = transformer.transform(schema_ref, header, message)

    assert len(records) == 2  # 1 body + 1 ring
    body_rec = next(r for r in records if r.table_name == "bodies")
    assert body_rec.data["id64"] == (10477373803 << 9) | 3
    assert body_rec.data["name"] == "Earth"
    assert body_rec.data["subType"] == "Earth-like World"
    assert round(body_rec.data["gravity"], 2) == 1.0  # 9.81 / 9.80665 ~ 1.00g

    ring_rec = next(r for r in records if r.table_name == "body_rings")
    assert ring_rec.data["name"] == "Earth Ring A"
    assert ring_rec.data["type"] == "Icy"


def test_scan_fss_body_signals_normalizes_genuses() -> None:
    """Validates FSSBodySignals event records biological signals into body_signals table."""
    transformer = JournalScanTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "FSSBodySignals",
        "timestamp": "2026-08-18T10:00:00Z",
        "SystemAddress": 10477373803,
        "BodyName": "Sol 3 a",
        "BodyID": 4,
        "Signals": [{"Type": "$Codex_Ent_Aleoida_01_A_Name;", "Count": 2}],
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "body_signals"
    signals_dict = json.loads(records[0].data["signals"])
    assert signals_dict["Aleoida_01_A"] == 2


def test_scan_organic_sampling_normalizes_genus() -> None:
    """Validates ScanOrganic event generates body_signals genus entries with canonical normalization."""
    transformer = JournalScanTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "ScanOrganic",
        "timestamp": "2026-08-18T10:30:00Z",
        "SystemAddress": 10477373803,
        "Body": 4,
        "Genus": "$Codex_Ent_Aleoid_Genus_Name;",
        "Species": "$Codex_Ent_Aleoida_01_A_Name;",
        "ScanType": "Sample",
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "body_signals"
    assert records[0].data["genuses"] == ["Aleoida"]


def test_scan_codex_entry_biology_registers_genus() -> None:
    """Validates CodexEntry biology discovery normalizes entry genus."""
    transformer = JournalScanTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "CodexEntry",
        "timestamp": "2026-08-18T11:00:00Z",
        "SystemAddress": 10477373803,
        "BodyID": 4,
        "Latitude": 12.34,
        "Longitude": 56.78,
        "Category": "$Codex_Category_Biology;",
        "SubCategory": "$Codex_SubCategory_Organic_Structures;",
        "EntryID": 12345,
        "Name": "$Codex_Ent_Aleoida_01_A_Name;",
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "body_signals"
    assert records[0].data["genuses"] == ["Aleoida"]


def test_scan_codex_entry_stellar_phenomena_emits_system_signal() -> None:
    """Validates CodexEntry space phenomena (Lagrange, Anomalies) creates system_signals."""
    transformer = JournalScanTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "CodexEntry",
        "timestamp": "2026-08-18T11:30:00Z",
        "SystemAddress": 10477373803,
        "Category": "$Codex_Category_StellarPhenomena;",
        "SubCategory": "$Codex_SubCategory_SpaceOrganisms;",
        "Name": "$Codex_Ent_Seed_A_Name;",
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "system_signals"
    assert records[0].data["name"] == "Seed_A"


def test_scan_codex_entry_personal_discoveries_ignored() -> None:
    """Validates personal stellar bodies Codex entries (e.g. stars/planets) produce no records."""
    transformer = JournalScanTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "CodexEntry",
        "timestamp": "2026-08-18T12:00:00Z",
        "SystemAddress": 10477373803,
        "Category": "$Codex_Category_Stars;",
        "Name": "K (Yellow-Orange) Star",
    }
    assert len(transformer.transform(schema_ref, header, message)) == 0


def test_station_docked_updates_pads_and_economies(sample_docked_payload: dict) -> None:
    """Validates JournalStationTransformer extracts pads, economies, and services."""
    transformer = JournalStationTransformer()
    schema_ref = sample_docked_payload["$schemaRef"]
    header = sample_docked_payload["header"]
    message = sample_docked_payload["message"]

    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    sta_rec = records[0]
    assert sta_rec.table_name == "stations"
    assert sta_rec.data["name"] == "Abraham Lincoln"
    assert sta_rec.data["market_id"] == 128000100
    assert sta_rec.data["pad_large"] == 12
    assert sta_rec.data["pad_medium"] == 8
    assert sta_rec.data["pad_small"] == 4
    assert "shipyard" in sta_rec.data["services_arr"]


def test_station_approach_settlement_with_market() -> None:
    """Validates ApproachSettlement with MarketID populates surface settlement coordinates."""
    transformer = JournalStationTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "ApproachSettlement",
        "timestamp": "2026-08-18T12:15:00Z",
        "SystemAddress": 10477373803,
        "MarketID": 3228991200,
        "Name": "Ray Gateway Ground",
        "BodyID": 5,
        "BodyName": "Sol 4",
        "Latitude": 12.345,
        "Longitude": -67.890,
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "stations"
    assert records[0].data["market_id"] == 3228991200
    assert records[0].data["latitude"] == 12.345
    assert records[0].data["longitude"] == -67.890


def test_station_approach_settlement_guardian_poi() -> None:
    """Validates ApproachSettlement for Guardian / Thargoid site without MarketID populates body_pois."""
    transformer = JournalStationTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "ApproachSettlement",
        "timestamp": "2026-08-18T12:30:00Z",
        "SystemAddress": 10477373803,
        "Name": "$Ancient_Structure_01;",
        "BodyID": 5,
        "BodyName": "Sol 4",
        "Latitude": 45.0,
        "Longitude": 90.0,
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 1
    assert records[0].table_name == "body_pois"
    assert records[0].data["raw_name"] == "$Ancient_Structure_01;"


def test_commodity_market_commodities_and_timestamp_update(sample_commodity_payload: dict) -> None:
    """Validates CommodityTransformer emits station_commodities and updates stations.market_updated_at."""
    transformer = CommodityTransformer()
    schema_ref = sample_commodity_payload["$schemaRef"]
    header = sample_commodity_payload["header"]
    message = sample_commodity_payload["message"]

    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 3  # 1 station timestamp update + 2 commodities

    sta_rec = next(r for r in records if r.table_name == "stations")
    assert sta_rec.data["market_id"] == 128000100
    assert sta_rec.data["market_updated_at"] == "2026-08-17T12:15:00Z"

    comm_recs = [r for r in records if r.table_name == "station_commodities"]
    assert len(comm_recs) == 2
    trit = next(c for c in comm_recs if c.data["commodityId"] == 128045)
    assert trit.data["buyPrice"] == 45000
    assert trit.data["supply"] == 8000


def test_shipyard_ships_and_timestamp_update() -> None:
    """Validates ShipyardTransformer emits station_ships and updates stations.shipyard_updated_at."""
    transformer = ShipyardTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/shipyard/2"
    header = {"uploaderID": "Cmdr"}
    message = {
        "timestamp": "2026-08-18T13:00:00Z",
        "marketId": 128000100,
        "systemName": "Sol",
        "stationName": "Abraham Lincoln",
        "ships": ["python", "anaconda", "type9"],
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 4  # 1 station + 3 ships

    sta_rec = next(r for r in records if r.table_name == "stations")
    assert sta_rec.data["shipyard_updated_at"] == "2026-08-18T13:00:00Z"

    ship_recs = [r for r in records if r.table_name == "station_ships"]
    assert len(ship_recs) == 3
    assert any(s.data["name"] == "Python" for s in ship_recs)
    assert any(s.data["name"] == "Anaconda" for s in ship_recs)


def test_outfitting_modules_and_timestamp_update() -> None:
    """Validates ShipyardTransformer for outfitting schema emits station_modules."""
    transformer = ShipyardTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/outfitting/2"
    header = {"uploaderID": "Cmdr"}
    message = {
        "timestamp": "2026-08-18T13:30:00Z",
        "marketId": 128000100,
        "systemName": "Sol",
        "stationName": "Abraham Lincoln",
        "modules": ["hpt_slugshot_fixed_large", "int_hyperdrive_size5_class5"],
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 3  # 1 station + 2 modules

    sta_rec = next(r for r in records if r.table_name == "stations")
    assert sta_rec.data["outfitting_updated_at"] == "2026-08-18T13:30:00Z"

    mod_recs = [r for r in records if r.table_name == "station_modules"]
    assert len(mod_recs) == 2


def test_fc_materials_journal_variant() -> None:
    """Validates FCMaterialsTransformer extracts Odyssey micro-resources from journal event."""
    transformer = FCMaterialsTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/fcmaterials_journal/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "FCMaterials",
        "timestamp": "2026-08-19T12:35:00Z",
        "MarketID": 3706615552,
        "CarrierID": "RZZ-51F",
        "CarrierName": "ESB Tiberium Toke",
        "Items": [
            {"id": 128962614, "Name": "Weapon Schematics", "Price": 3500000, "Stock": 10, "Demand": 0},
        ],
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 2  # 1 station + 1 material
    sta_rec = next(r for r in records if r.table_name == "stations")
    assert sta_rec.data["name"] == "RZZ-51F"
    assert sta_rec.data["carrierName"] == "ESB Tiberium Toke"

    mat_rec = next(r for r in records if r.table_name == "station_materials")
    assert mat_rec.data["material_id"] == 128962614
    assert mat_rec.data["name"] == "Weapon Schematics"


def test_fss_signal_scenarios_and_threat_levels() -> None:
    """Validates FSSSignalTransformer normalizes multiplayer scenario titles and threat levels."""
    transformer = FSSSignalTransformer()
    schema_ref = "https://eddn.edcd.io/schemas/fsssignaldiscovered/1"
    header = {"uploaderID": "Cmdr"}
    message = {
        "event": "FSSSignalDiscovered",
        "timestamp": "2026-08-20T04:15:17Z",
        "SystemAddress": 3657466647274,
        "signals": [
            {"SignalName": "$Warzone_PointRace_Low:#index=1;", "SignalType": "$Warzone;"},
            {"SignalName": "ESB Tiberium Toke RZZ-51F", "SignalType": "FleetCarrier", "IsStation": True},
        ],
    }
    records = transformer.transform(schema_ref, header, message)
    assert len(records) == 2
    wz = next(r for r in records if "Warzone" in r.data["raw_name"])
    assert wz.data["name"] == "Conflict Zone [Low]"
