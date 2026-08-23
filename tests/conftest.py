"""Shared pytest fixtures and test data factories for ed-galaxy-sync-pg test suite."""

import pytest

from eddn.metrics import EDDNMetrics
from eddn.normalizers import NormalizerManager


@pytest.fixture
def normalizer_instance() -> NormalizerManager:
    """Provides a pre-loaded NormalizerManager instance."""
    return NormalizerManager()


@pytest.fixture
def metrics_instance() -> EDDNMetrics:
    """Provides a fresh EDDNMetrics telemetry instance."""
    return EDDNMetrics()


@pytest.fixture
def sample_fsd_jump_payload() -> dict:
    """Provides a standard Live EDDN FSDJump event message payload."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "CommanderTest",
            "softwareName": "EDMarketConnector",
            "softwareVersion": "5.10.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "event": "FSDJump",
            "timestamp": "2026-08-17T12:00:00Z",
            "StarSystem": "Sol",
            "SystemAddress": 10477373803,
            "StarPos": [0.0, 0.0, 0.0],
            "SystemAllegiance": "Federation",
            "SystemGovernment": "Democracy",
            "SystemEconomy": "$economy_Industrial;",
            "SystemSecondEconomy": "$economy_Refinery;",
            "SystemSecurity": "$SYSTEM_SECURITY_high;",
            "Population": 22780871769,
            "BodyCount": 42,
            "PowerplayState": "Exploited",
            "Powers": ["Zachary Hudson"],
            "ControllingPower": "Zachary Hudson",
            "SystemFaction": {"Name": "Mother Gaia", "FactionState": "None"},
            "Factions": [
                {
                    "Name": "Mother Gaia",
                    "FactionState": "None",
                    "Allegiance": "Federation",
                    "Government": "Democracy",
                    "Influence": 0.582,
                    "ActiveStates": [],
                },
                {
                    "Name": "Sol Workers' Party",
                    "FactionState": "CivilUnrest",
                    "Allegiance": "Independent",
                    "Government": "Communist",
                    "Influence": 0.142,
                },
            ],
        },
    }


@pytest.fixture
def sample_carrier_jump_payload() -> dict:
    """Provides a standard CarrierJump event message payload."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "CommanderTest",
            "softwareName": "EDMarketConnector",
            "softwareVersion": "5.10.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "event": "CarrierJump",
            "timestamp": "2026-08-19T12:30:00Z",
            "StarSystem": "Colonia",
            "SystemAddress": 109823485721,
            "StarPos": [-9530.5, -910.28, 19808.12],
            "StationName": "RZZ-51F",
            "CarrierName": "ESB Tiberium Toke",
            "MarketID": 3706615552,
            "StationType": "Drake-Class Carrier",
            "BodyID": 4,
            "DistFromStarLS": 124.5,
            "CarrierDockingAccess": "all",
            "StationServices": ["dock", "autodock", "commodities", "refuel", "repair"],
        },
    }


@pytest.fixture
def sample_scan_body_payload() -> dict:
    """Provides a standard celestial body Scan event message payload."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "CommanderTest",
            "softwareName": "EDMarketConnector",
            "softwareVersion": "5.10.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "event": "Scan",
            "timestamp": "2026-08-17T12:05:00Z",
            "StarSystem": "Sol",
            "SystemAddress": 10477373803,
            "BodyID": 3,
            "BodyName": "Earth",
            "PlanetClass": "Earthlike body",
            "DistanceFromArrivalLS": 499.2,
            "SurfaceTemperature": 288.0,
            "Radius": 6371000.0,
            "SurfaceGravity": 9.81,
            "MassEM": 1.0,
            "Landable": False,
            "AtmosphereType": "EarthLike",
            "TerraformState": "",
            "Rings": [
                {
                    "Name": "Earth Ring A",
                    "RingClass": "eRingClass_Icy",
                    "MassMT": 500000.0,
                    "InnerRad": 10000000.0,
                    "OuterRad": 25000000.0,
                }
            ],
        },
    }


@pytest.fixture
def sample_docked_payload() -> dict:
    """Provides a standard station Docked event message payload."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
        "header": {
            "uploaderID": "CommanderTest",
            "softwareName": "EDMarketConnector",
            "softwareVersion": "5.10.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "event": "Docked",
            "timestamp": "2026-08-17T12:10:00Z",
            "StarSystem": "Sol",
            "SystemAddress": 10477373803,
            "StationName": "Abraham Lincoln",
            "StationType": "Coriolis",
            "MarketID": 128000100,
            "DistFromStarLS": 500.0,
            "StationAllegiance": "Federation",
            "StationGovernment": "Democracy",
            "StationEconomy": "$economy_Refinery;",
            "StationServices": ["dock", "autodock", "commodities", "shipyard", "outfitting"],
            "LandingPads": {"Small": 4, "Medium": 8, "Large": 12},
        },
    }


@pytest.fixture
def sample_commodity_payload() -> dict:
    """Provides a standard EDDN v3 commodity market event message payload."""
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
        "header": {
            "uploaderID": "CommanderTest",
            "softwareName": "EDMarketConnector",
            "softwareVersion": "5.10.0",
            "gameversion": "4.0.0.1451",
        },
        "message": {
            "timestamp": "2026-08-17T12:15:00Z",
            "systemName": "Sol",
            "stationName": "Abraham Lincoln",
            "marketId": 128000100,
            "commodities": [
                {
                    "name": "Tritium",
                    "buyPrice": 45000,
                    "sellPrice": 42000,
                    "demand": 15000,
                    "stock": 8000,
                    "commodityId": 128045,
                },
                {
                    "name": "Gold",
                    "buyPrice": 52000,
                    "sellPrice": 48000,
                    "demand": 2500,
                    "stock": 1200,
                },
            ],
        },
    }
