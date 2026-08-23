-- ==============================================================================
-- system_distance_3d.sql: 3D Euclidean Distance Helper Function
-- ==============================================================================

CREATE OR REPLACE FUNCTION system_distance_3d (
    system_a cube,
    system_b cube DEFAULT cube(ARRAY[0,0,0]::double precision[])
) RETURNS double precision
LANGUAGE plpgsql
IMMUTABLE PARALLEL SAFE
AS $$
BEGIN
    RETURN system_a <-> system_b;
END;
$$;

-- Documentation
COMMENT ON FUNCTION system_distance_3d(cube, cube) IS
  'Computes the 3D Euclidean distance in light-years between two systems using native cube <-> operator. '
  'If system_b is omitted, the distance from system_a to the origin (Sol at 0,0,0) is returned. '
  'IMMUTABLE and PARALLEL SAFE — safe to use in indexes and parallel queries. '
  'Example: SELECT system_distance_3d(a.coords, b.coords) FROM systems a, systems b WHERE a.name = ''Sol'';';
