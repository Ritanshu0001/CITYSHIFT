import { cellToBoundary, cellToLatLng, type CoordPair } from "h3-js";

const EARTH_RADIUS_M = 6_371_008.8;
const COMPASS_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

export interface LiveTerrain {
  centerElevationM: number;
  steepestGradePct: number;
  direction: (typeof COMPASS_DIRECTIONS)[number];
  coarse: boolean;
}

function radians(degrees: number) {
  return degrees * Math.PI / 180;
}

function distanceMeters([latA, lngA]: CoordPair, [latB, lngB]: CoordPair) {
  const latDelta = radians(latB - latA);
  const lngDelta = radians(lngB - lngA);
  const startLat = radians(latA);
  const endLat = radians(latB);
  const haversine = Math.sin(latDelta / 2) ** 2
    + Math.cos(startLat) * Math.cos(endLat) * Math.sin(lngDelta / 2) ** 2;
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function directionFromCenter([latA, lngA]: CoordPair, [latB, lngB]: CoordPair) {
  const startLat = radians(latA);
  const endLat = radians(latB);
  const lngDelta = radians(lngB - lngA);
  const y = Math.sin(lngDelta) * Math.cos(endLat);
  const x = Math.cos(startLat) * Math.sin(endLat)
    - Math.sin(startLat) * Math.cos(endLat) * Math.cos(lngDelta);
  const bearing = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  return COMPASS_DIRECTIONS[Math.round(bearing / 45) % COMPASS_DIRECTIONS.length];
}

export async function getLiveTerrain(h3: string): Promise<LiveTerrain> {
  if (!window.google?.maps?.importLibrary) throw new Error("Google Maps is unavailable.");

  const center = cellToLatLng(h3);
  const corners = cellToBoundary(h3);
  if (corners.length !== 6) throw new Error("Expected six H3 corners.");

  const locations = [center, ...corners].map(([lat, lng]) => ({ lat, lng }));
  await google.maps.importLibrary("elevation");
  if (!google.maps.ElevationService) throw new Error("Google Elevation is unavailable.");
  const { results } = await new google.maps.ElevationService().getElevationForLocations({ locations });
  if (results.length !== locations.length) throw new Error("Google Elevation returned incomplete terrain data.");

  const centerElevationM = results[0].elevation;
  const grades = corners.map((corner, index) => ({
    corner,
    gradePct: Math.abs(results[index + 1].elevation - centerElevationM) / distanceMeters(center, corner) * 100,
  }));
  const steepest = grades.reduce((current, candidate) => (
    candidate.gradePct > current.gradePct ? candidate : current
  ));

  return {
    centerElevationM,
    steepestGradePct: steepest.gradePct,
    direction: directionFromCenter(center, steepest.corner),
    coarse: results.some((result) => result.resolution > 100),
  };
}
