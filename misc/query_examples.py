"""
Elite Dangerous Galaxy Database Query Examples and Reference Queries.

This standalone module demonstrates how to perform spatial, attribute, and aggregation
queries against the PostgreSQL galaxy database, including 3D Euclidean distance queries
via the PostgreSQL `cube` GiST spatial extension.

Usage Examples:
    # 1. Look up a system by exact name:
    python misc/query_examples.py --password 'PASS' lookup "Sol"

    # 2. Search systems by allegiance and minimum population:
    python misc/query_examples.py --password 'PASS' search --allegiance "Empire" --min-pop 1000000000 --limit 5

    # 3. 3D Radial search around coordinates or named center system:
    python misc/query_examples.py --password 'PASS' nearby --name "Sol" --radius 50
    python misc/query_examples.py --password 'PASS' nearby --x 0 --y 0 --z 0 --radius 30

    # 4. Find landable Earth-like or high-value exploration bodies:
    python misc/query_examples.py --password 'PASS' find-body --subtype "Earth-like world" --landable

    # 5. Search orbital and planetary starports with markets and shipyards:
    python misc/query_examples.py --password 'PASS' stations --system "Sol" --has-market --has-shipyard

    # 6. Database row counts and allegiance breakdown:
    python misc/query_examples.py --password 'PASS' stats
"""

import argparse
import os
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_PG_URI = os.environ.get("DATABASE_URL", "postgresql://galaxy_searcher@localhost:5432/galaxy_sync")


def get_connection(pg_uri: str = DEFAULT_PG_URI, read_only: bool = True) -> psycopg.Connection:
    """Returns a connection to the PostgreSQL galaxy database with dict_row factory.

    Args:
        pg_uri: Target PostgreSQL database connection URI string.
        read_only: If True, sets transaction mode to read-only.

    Returns:
        psycopg.Connection: Configured psycopg connection instance.
    """
    conn = psycopg.connect(pg_uri, row_factory=dict_row, autocommit=not read_only)
    if read_only:
        conn.read_only = True
    return conn


def parse_coords(coords_raw: Any) -> tuple[str, str, str]:
    """Safely unpacks coordinates from PostgreSQL cube or dictionary representation.

    Args:
        coords_raw: Raw coordinates object (dict, string tuple representation, or None).

    Returns:
        tuple[str, str, str]: Tuple of (x, y, z) coordinate strings.
    """
    if coords_raw is None:
        return ("", "", "")
    if isinstance(coords_raw, dict):
        return (
            str(coords_raw.get("x", "")),
            str(coords_raw.get("y", "")),
            str(coords_raw.get("z", "")),
        )
    if isinstance(coords_raw, str):
        cleaned = coords_raw.strip("()")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if len(parts) >= 3:
            return (parts[0], parts[1], parts[2])
    return ("", "", "")


# ---------------------------------------------------------------------------
# 1. System Queries
# ---------------------------------------------------------------------------


def get_system_by_name(conn: psycopg.Connection, name: str) -> dict[str, Any] | None:
    """
    Finds a star system by exact name (case-insensitive).
    """
    query = """
        SELECT 
            id64, name, coords, allegiance, government, primaryEconomy, secondaryEconomy, 
            security, population, bodyCount, controllingPower, powerState, 
            powerStateControlProgress, powerStateReinforcement, powerStateUndermining, 
            powers, controllingFaction, powerConflictProgress, thargoidWar, timestamps, update_dtm 
        FROM systems 
        WHERE LOWER(name) = LOWER(%s) 
        LIMIT 1;
    """
    with conn.cursor() as cur:
        cur.execute(query, (name,))
        return cur.fetchone()


def search_systems(
    conn: psycopg.Connection,
    name: str | None = None,
    allegiance: str | None = None,
    government: str | None = None,
    min_pop: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Search star systems matching one or more filter criteria.
    """
    conditions = []
    params: list[Any] = []

    if name:
        conditions.append("LOWER(name) LIKE LOWER(%s)")
        params.append(f"%{name}%")
    if allegiance:
        conditions.append("LOWER(allegiance) = LOWER(%s)")
        params.append(allegiance)
    if government:
        conditions.append("LOWER(government) = LOWER(%s)")
        params.append(government)
    if min_pop is not None:
        conditions.append("population >= %s")
        params.append(min_pop)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"""
        SELECT id64, name, coords, allegiance, government, population, bodyCount
        FROM systems
        {where_clause}
        ORDER BY population DESC NULLS LAST
        LIMIT %s;
    """
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 2. 3D Spatial Queries (Cube GiST Extension)
# ---------------------------------------------------------------------------


def find_nearby_systems(
    conn: psycopg.Connection,
    x: float,
    y: float,
    z: float,
    radius_ly: float,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Finds star systems within a given 3D radius (in light years) from coordinates (x, y, z).
    Utilizes PostgreSQL cube GiST index for fast bounding box containment (<@) and Euclidean distance (<->).
    """
    query = """
        SELECT 
            id64, 
            name, 
            coords, 
            allegiance, 
            government, 
            population, 
            bodyCount,
            (coords <-> cube(ARRAY[%s, %s, %s]::double precision[])) AS distance_ly
        FROM systems
        WHERE coords <@ cube(
            ARRAY[%s, %s, %s]::double precision[],
            ARRAY[%s, %s, %s]::double precision[]
        )
          AND (coords <-> cube(ARRAY[%s, %s, %s]::double precision[])) <= %s
        ORDER BY distance_ly ASC
        LIMIT %s;
    """
    params = [
        x,
        y,
        z,
        x - radius_ly,
        y - radius_ly,
        z - radius_ly,
        x + radius_ly,
        y + radius_ly,
        z + radius_ly,
        x,
        y,
        z,
        radius_ly,
        limit,
    ]
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 3. Celestial Body Queries
# ---------------------------------------------------------------------------


def find_bodies_by_subtype(
    conn: psycopg.Connection,
    subtype: str | None = None,
    is_landable: bool | None = None,
    max_distance: float | None = None,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    origin_z: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Searches for celestial bodies matching criteria (e.g. 'Earth-like world', 'Ammonia world').
    """
    conditions = []
    params: list[Any] = [origin_x, origin_y, origin_z]

    query = """
        SELECT
            systems.name AS system_name,
            systems.coords AS system_coords,
            bodies.name AS body_name,
            bodies.type AS body_type,
            bodies.subType AS body_subtype,
            bodies.distanceToArrival,
            bodies.isLandable,
            bodies.gravity,
            bodies.surfaceTemperature,
            bodies.atmosphereType,
            bodies.earthMasses,
            (systems.coords <-> cube(ARRAY[%s, %s, %s]::double precision[])) AS distance_from_origin_ly
        FROM bodies
        INNER JOIN systems ON bodies.system_id64 = systems.id64
    """

    if subtype:
        conditions.append("LOWER(bodies.subType) LIKE LOWER(%s)")
        params.append(f"%{subtype}%")
    if is_landable is not None:
        conditions.append("bodies.isLandable = %s")
        params.append(is_landable)
    if max_distance is not None:
        conditions.append("bodies.distanceToArrival <= %s")
        params.append(max_distance)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY distance_from_origin_ly ASC LIMIT %s;"
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 4. Station & Market Queries
# ---------------------------------------------------------------------------


def find_stations(
    conn: psycopg.Connection,
    name: str | None = None,
    system_name: str | None = None,
    station_type: str | None = None,
    has_market: bool | None = None,
    has_shipyard: bool | None = None,
    has_outfitting: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Search starports, outposts, surface ports, and fleet carriers with optional market/services filters.
    """
    conditions = []
    params: list[Any] = []

    query = """
        SELECT 
            systems.name AS system_name,
            stations.name AS station_name,
            stations.type AS station_type,
            (stations.market_id IS NOT NULL) AS hasMarket,
            (stations.shipyard_updated_at IS NOT NULL) AS hasShipyard,
            (stations.outfitting_updated_at IS NOT NULL) AS hasOutfitting,
            stations.distanceToArrival,
            stations.allegiance
        FROM stations
        INNER JOIN systems ON stations.system_id64 = systems.id64
    """

    if name:
        conditions.append("LOWER(stations.name) LIKE LOWER(%s)")
        params.append(f"%{name}%")
    if system_name:
        conditions.append("LOWER(systems.name) LIKE LOWER(%s)")
        params.append(f"%{system_name}%")
    if station_type:
        conditions.append("LOWER(stations.type) LIKE LOWER(%s)")
        params.append(f"%{station_type}%")
    if has_market is not None:
        if has_market:
            conditions.append("stations.market_id IS NOT NULL")
        else:
            conditions.append("stations.market_id IS NULL")
    if has_shipyard is not None:
        if has_shipyard:
            conditions.append("stations.shipyard_updated_at IS NOT NULL")
        else:
            conditions.append("stations.shipyard_updated_at IS NULL")
    if has_outfitting is not None:
        if has_outfitting:
            conditions.append("stations.outfitting_updated_at IS NOT NULL")
        else:
            conditions.append("stations.outfitting_updated_at IS NULL")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " LIMIT %s;"
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 5. Database Statistics Summary
# ---------------------------------------------------------------------------


def get_database_stats(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Returns summary row counts and distribution statistics for the PostgreSQL database.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM systems;")
        system_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM system_factions;")
        system_factions_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM bodies;")
        body_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM body_rings;")
        body_rings_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM body_belts;")
        body_belts_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM body_signals;")
        body_signals_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM stations;")
        station_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM station_commodities;")
        station_commodities_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM station_ships;")
        station_ships_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM station_modules;")
        station_modules_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM _ingested_tables;")
        ingested_files_count = cur.fetchone()["count"]

        cur.execute("SELECT allegiance, COUNT(*) as cnt FROM systems GROUP BY allegiance ORDER BY cnt DESC;")
        allegiances = {r["allegiance"]: r["cnt"] for r in cur.fetchall()}

    return {
        "total_systems": system_count,
        "total_system_factions": system_factions_count,
        "total_bodies": body_count,
        "total_body_rings": body_rings_count,
        "total_body_belts": body_belts_count,
        "total_body_signals": body_signals_count,
        "total_stations": station_count,
        "total_station_commodities": station_commodities_count,
        "total_station_ships": station_ships_count,
        "total_station_modules": station_modules_count,
        "total_ingested_files": ingested_files_count,
        "allegiance_distribution": allegiances,
    }


# ---------------------------------------------------------------------------
# CLI Command Runner
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Elite Dangerous PostgreSQL Database Query Examples & Reference CLI")
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"), help="PostgreSQL host (default: localhost)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PGPORT", "5432")), help="PostgreSQL port (default: 5432)")
    parser.add_argument(
        "--user", default=os.environ.get("PGUSER", "galaxy_searcher"), help="PostgreSQL user (default: galaxy_searcher)"
    )
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD"), help="PostgreSQL password (env: PGPASSWORD)")
    parser.add_argument(
        "--dbname", default=os.environ.get("PGDATABASE", "galaxy_sync"), help="PostgreSQL database (default: galaxy_sync)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available query subcommands")

    # lookup
    lookup_p = subparsers.add_parser("lookup", help="Look up a star system by exact name")
    lookup_p.add_argument("name", help="Name of star system (e.g. Sol, Achenar)")

    # search
    search_p = subparsers.add_parser("search", help="Search systems with filters")
    search_p.add_argument("--name", help="Partial or exact system name filter")
    search_p.add_argument("--allegiance", help="Filter by allegiance")
    search_p.add_argument("--government", help="Filter by government")
    search_p.add_argument("--min-pop", type=int, help="Filter by minimum population")
    search_p.add_argument("--limit", type=int, default=10, help="Max results to return")

    # nearby
    nearby_p = subparsers.add_parser("nearby", help="Find systems within a radius (ly) of coordinates or named system")
    nearby_p.add_argument("--name", help="Name of center system (e.g. Sol)")
    nearby_p.add_argument("--x", type=float, help="Center X coordinate")
    nearby_p.add_argument("--y", type=float, help="Center Y coordinate")
    nearby_p.add_argument("--z", type=float, help="Center Z coordinate")
    nearby_p.add_argument("--radius", type=float, default=50.0, help="Search radius in light years")
    nearby_p.add_argument("--limit", type=int, default=10, help="Max results to return")

    # find-body
    body_p = subparsers.add_parser("find-body", help="Find celestial bodies matching criteria")
    body_p.add_argument("--subtype", help="Body subType filter (e.g. 'Earth-like world')")
    body_p.add_argument("--landable", action="store_true", help="Filter for landable bodies only")
    body_p.add_argument("--max-distance", type=float, help="Max distance to arrival star in LS")
    body_p.add_argument("--x", type=float, default=0.0, help="Origin X coordinate (default: 0.0)")
    body_p.add_argument("--y", type=float, default=0.0, help="Origin Y coordinate (default: 0.0)")
    body_p.add_argument("--z", type=float, default=0.0, help="Origin Z coordinate (default: 0.0)")
    body_p.add_argument("--limit", type=int, default=10, help="Max results to return")

    # stations
    station_p = subparsers.add_parser("stations", help="Search stations with market/service filters")
    station_p.add_argument("--name", help="Station name filter")
    station_p.add_argument("--system", help="System name filter")
    station_p.add_argument("--type", help="Station type filter")
    station_p.add_argument("--has-market", action="store_true", default=None, help="Only stations with active commodity market")
    station_p.add_argument("--has-shipyard", action="store_true", default=None, help="Only stations with shipyard")
    station_p.add_argument("--has-outfitting", action="store_true", default=None, help="Only stations with outfitting")
    station_p.add_argument("--limit", type=int, default=20, help="Max results to return")

    # stats
    subparsers.add_parser("stats", help="Display overall database statistics and record counts")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    import urllib.parse

    if args.password:
        encoded_pwd = urllib.parse.quote_plus(args.password)
        pg_uri = f"postgresql://{args.user}:{encoded_pwd}@{args.host}:{args.port}/{args.dbname}"
    else:
        pg_uri = f"postgresql://{args.user}@{args.host}:{args.port}/{args.dbname}"

    try:
        conn = get_connection(pg_uri, read_only=True)
    except Exception as e:
        print(f"Error: Failed to connect to PostgreSQL database at {args.host}:{args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    with conn:
        match args.command:
            case "lookup":
                result = get_system_by_name(conn, args.name)
                if not result:
                    print(f"System '{args.name}' not found.")
                else:
                    cx, cy, cz = parse_coords(result.get("coords"))
                    print(f"\n--- System Details: {result.get('name')} ---")
                    print(f"ID64       : {result.get('id64')}")
                    print(f"Coordinates: X={cx}, Y={cy}, Z={cz}")
                    print(f"Allegiance : {result.get('allegiance')}")
                    print(f"Government : {result.get('government')}")
                    pop = result.get("population")
                    print(f"Population : {pop:,}" if pop is not None else "Population : None")
                    print(f"Bodies     : {result.get('bodycount')} bodies logged")

            case "search":
                results = search_systems(
                    conn,
                    name=args.name,
                    allegiance=args.allegiance,
                    government=args.government,
                    min_pop=args.min_pop,
                    limit=args.limit,
                )
                print(f"\nFound {len(results)} matching system(s):")
                for r in results:
                    cx, cy, cz = parse_coords(r.get("coords"))
                    pop = r.get("population")
                    pop_str = f" | Pop: {pop:,}" if pop is not None else ""
                    print(f"  - {r.get('name')} | Coords: ({cx}, {cy}, {cz}) | Allegiance: {r.get('allegiance')}{pop_str}")

            case "nearby":
                target_x, target_y, target_z = args.x, args.y, args.z
                center_label = f"({target_x}, {target_y}, {target_z})"
                if args.name and (target_x is None or target_y is None or target_z is None):
                    sys_info = get_system_by_name(conn, args.name)
                    if not sys_info:
                        print(f"Error: Center system '{args.name}' not found in database.", file=sys.stderr)
                        return
                    cx, cy, cz = parse_coords(sys_info.get("coords"))
                    try:
                        target_x = float(cx) if cx != "" else None
                        target_y = float(cy) if cy != "" else None
                        target_z = float(cz) if cz != "" else None
                    except ValueError, TypeError:
                        target_x, target_y, target_z = None, None, None
                    center_label = f"'{args.name}' ({target_x}, {target_y}, {target_z})"

                if target_x is None or target_y is None or target_z is None:
                    print("Error: Must specify either --name or all three coordinates (--x, --y, --z).", file=sys.stderr)
                    return

                results = find_nearby_systems(conn, target_x, target_y, target_z, args.radius, limit=args.limit)
                print(f"\nFound {len(results)} system(s) within {args.radius} ly of {center_label}:")
                for r in results:
                    dist = r.get("distance_ly", 0.0)
                    cx, cy, cz = parse_coords(r.get("coords"))
                    print(f"  - {r.get('name')} ({dist:.2f} ly away) | Coords: ({cx}, {cy}, {cz})")

            case "find-body":
                results = find_bodies_by_subtype(
                    conn,
                    subtype=args.subtype,
                    is_landable=True if args.landable else None,
                    max_distance=args.max_distance,
                    origin_x=args.x,
                    origin_y=args.y,
                    origin_z=args.z,
                    limit=args.limit,
                )
                subtype_label = args.subtype or "All"
                print(f"\nFound {len(results)} '{subtype_label}' bodies (Landable only: {args.landable}):")
                for r in results:
                    dist = r.get("distance_from_origin_ly", 0.0)
                    landable_str = " (Landable)" if r.get("islandable") else ""
                    print(f"  - {r.get('body_name')} in {r.get('system_name')} ({dist:.2f} ly away){landable_str}")
                    mass = r.get("earthmasses")
                    mass_str = f"{mass:.3f}" if mass is not None else "N/A"
                    temp = r.get("surfacetemperature")
                    temp_str = f"{temp:.0f}" if temp is not None else "N/A"
                    print(
                        f"    Type: {r.get('body_type')} | SubType: {r.get('body_subtype')} | Mass: {mass_str} Earths | Temp: {temp_str} K"
                    )

            case "stations":
                results = find_stations(
                    conn,
                    name=args.name,
                    system_name=args.system,
                    station_type=args.type,
                    has_market=args.has_market,
                    has_shipyard=args.has_shipyard,
                    has_outfitting=args.has_outfitting,
                    limit=args.limit,
                )
                print(f"\nFound {len(results)} station(s):")
                for r in results:
                    services = []
                    if r.get("hasmarket"):
                        services.append("Market")
                    if r.get("hasshipyard"):
                        services.append("Shipyard")
                    if r.get("hasoutfitting"):
                        services.append("Outfitting")
                    serv_str = f" [{', '.join(services)}]" if services else ""
                    print(f"  - {r.get('station_name')} ({r.get('station_type')}) in {r.get('system_name')}{serv_str}")

            case "stats":
                stats = get_database_stats(conn)
                print("\n==================================================")
                print("          GALAXY DATABASE STATISTICS")
                print("==================================================")
                print(f"Total Star Systems logged : {stats.get('total_systems', 0):,}")
                print(f"Total System Factions     : {stats.get('total_system_factions', 0):,}")
                print(f"Total Bodies logged       : {stats.get('total_bodies', 0):,}")
                print(f"Total Body Rings          : {stats.get('total_body_rings', 0):,}")
                print(f"Total Body Belts          : {stats.get('total_body_belts', 0):,}")
                print(f"Total Body Signals        : {stats.get('total_body_signals', 0):,}")
                print(f"Total Stations logged     : {stats.get('total_stations', 0):,}")
                print(f"Total Station Commodities : {stats.get('total_station_commodities', 0):,}")
                print(f"Total Station Ships       : {stats.get('total_station_ships', 0):,}")
                print(f"Total Station Modules     : {stats.get('total_station_modules', 0):,}")
                print(f"Total Ingested Files      : {stats.get('total_ingested_files', 0):,}")
                print("==================================================")
                allegiances = stats.get("allegiance_distribution", {})
                if allegiances:
                    print("  Allegiance Distribution:")
                    for allegiance, count in allegiances.items():
                        label = allegiance if allegiance else "None"
                        print(f"    {label:<28}: {count:,}")

            case None | _:
                parser.print_help()


if __name__ == "__main__":
    main()
