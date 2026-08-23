"""Modular EDDN schema transformers for converting raw payloads into database records.

Each transformer handles a specific EDDN schema or journal event family:

- ``JournalJumpTransformer``: FSDJump, Location, CarrierJump, FSSDiscoveryScan → systems, system_factions.
- ``JournalScanTransformer``: Scan, SAASignalsFound, FSSBodySignals, ScanOrganic, CodexEntry → bodies, body_rings, body_belts, body_signals, system_signals.
- ``JournalStationTransformer``: Docked, ApproachSettlement → stations, body_pois.
- ``CommodityTransformer``: Commodity schema → station_commodities.
- ``ShipyardTransformer``: Shipyard/Outfitting schemas → station_ships, station_modules.
- ``FSSSignalTransformer``: FSSSignalDiscovered → system_signals.
- ``FCMaterialsTransformer``: FCMaterials schema → station_materials.
- ``UnhandledEventTransformer``: Dead-Letter Queue fallback → eddn_unhandled_events.
"""

from .base import BaseTransformer, TransformedRecord
from .commodity import CommodityTransformer
from .fc_materials import FCMaterialsTransformer
from .fss_signal import FSSSignalTransformer
from .journal_jump import JournalJumpTransformer
from .journal_scan import JournalScanTransformer
from .journal_station import JournalStationTransformer
from .shipyard import ShipyardTransformer
from .unhandled import UnhandledEventTransformer


__all__ = [
    "BaseTransformer",
    "CommodityTransformer",
    "FCMaterialsTransformer",
    "FSSSignalTransformer",
    "JournalJumpTransformer",
    "JournalScanTransformer",
    "JournalStationTransformer",
    "ShipyardTransformer",
    "TransformedRecord",
    "UnhandledEventTransformer",
]
