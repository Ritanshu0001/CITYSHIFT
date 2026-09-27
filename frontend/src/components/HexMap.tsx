"use client";

import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { PolygonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { APILoadingStatus, Map, RenderingType, useApiLoadingStatus, useMap } from "@vis.gl/react-google-maps";
import { cellToBoundary } from "h3-js";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { BAND_COLORS, CRASH_COUNT_COLORS, MAPS_API_KEY } from "@/lib/constants";
import type { Center, CityHex, CrashPoint, CrashesResponse } from "@/lib/types";
import { Legend } from "./Legend";

interface HexMapProps {
  center: Center;
  hexes: CityHex[];
  selectedHex: CityHex | null;
  highlightedIds: string[];
  crashes?: CrashesResponse | null;
  showCrashes?: boolean;
  flyTo?: { lat: number; lng: number; zoom: number; key: number } | null;
  onToggleCrashes?: () => void;
  onSelect: (hex: CityHex) => void;
}

interface CrashHover {
  point: CrashPoint;
  x: number;
  y: number;
}

interface HexPolygon {
  hex: CityHex;
  polygon: [number, number][];
  fillPolygon: [number, number][];
}

const FALLBACK_ZOOM = 12;
const TILE_SIZE = 256;
const FALLBACK_WIDTH = 1000;
const FALLBACK_HEIGHT = 700;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function crashFillColor(count: number): [number, number, number, number] {
  const color = count >= 4 ? CRASH_COUNT_COLORS.many : count >= 2 ? CRASH_COUNT_COLORS.few : CRASH_COUNT_COLORS.one;
  return [...color.rgb, 245];
}

function crashRingColor(point: CrashPoint): [number, number, number, number] {
  if (point.pedestrian && point.cyclist) return [248, 191, 71, 255];
  if (point.cyclist) return [24, 198, 163, 255];
  if (point.pedestrian) return [255, 255, 255, 255];
  return [255, 255, 255, 105];
}

function hexEdgeColor(hex: CityHex, alpha = 255): [number, number, number, number] {
  const [r, g, b] = BAND_COLORS[hex.band].rgb;
  return [r, g, b, alpha];
}

function crashTime(hour: number | null) {
  if (hour === null || hour < 0 || hour > 23) return "Time unknown";
  const suffix = hour >= 12 ? "PM" : "AM";
  return `${hour % 12 || 12}:00 ${suffix}`;
}

function crashInvolvement(point: CrashPoint) {
  const involved = [point.pedestrian ? "Pedestrian involved" : null, point.cyclist ? "Cyclist involved" : null].filter(Boolean);
  return involved.length ? involved.join(" · ") : "No pedestrian or cyclist involvement recorded";
}

function projectToWorld(lat: number, lng: number, zoom: number) {
  const scale = TILE_SIZE * 2 ** zoom;
  const sinLat = Math.sin((Math.max(-85.0511, Math.min(85.0511, lat)) * Math.PI) / 180);
  return {
    x: ((lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

const DARK_MAP_STYLES = [
  { elementType: "geometry", stylers: [{ color: "#111629" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#b8c4dc" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#080c18" }, { weight: 4 }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#343c56" }] },
  { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#ffffff" }] },
  { featureType: "administrative.neighborhood", elementType: "labels.text.fill", stylers: [{ color: "#c6d2e9" }] },
  { featureType: "landscape", elementType: "geometry", stylers: [{ color: "#151b30" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#1a2138" }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#303950" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#111629" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#dbe2f1" }] },
  { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: "#46516e" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#64708c" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#171d31" }] },
  { featureType: "road.highway", elementType: "labels.text.fill", stylers: [{ color: "#ffffff" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#222a43" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#080c18" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#86ace0" }] },
];

type DeckOverlayProps = Omit<HexMapProps, "center" | "onToggleCrashes"> & {
  onCrashHover: (hover: CrashHover | null) => void;
};

function DeckOverlay({ hexes, selectedHex, highlightedIds, crashes, showCrashes = false, onCrashHover, onSelect }: DeckOverlayProps) {
  const map = useMap();
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);
  const polygonHexes = useMemo<HexPolygon[]>(() => hexes.map((hex) => {
    const polygon = cellToBoundary(hex.h3).map(([lat, lng]) => [lng, lat] as [number, number]);
    const center = polygon.reduce(
      ([lngSum, latSum], [lng, lat]) => [lngSum + lng, latSum + lat],
      [0, 0],
    ).map((value) => value / polygon.length) as [number, number];
    const fillInset = 0.965;
    const fillPolygon = polygon.map(([lng, lat]) => [
      center[0] + (lng - center[0]) * fillInset,
      center[1] + (lat - center[1]) * fillInset,
    ] as [number, number]);
    return { hex, polygon, fillPolygon };
  }), [hexes]);
  const overlay = useMemo(() => new GoogleMapsOverlay({ layers: [], interleaved: false }), []);
  const attachmentGeneration = useRef(0);
  const arrowCursor = useRef(false);

  useEffect(() => {
    if (!map) return;
    const generation = ++attachmentGeneration.current;
    overlay.setMap(map);
    return () => {
      // React development mode immediately replays effects. Detaching synchronously
      // leaves a queued Google Maps draw with no projection, so only detach if this
      // attachment was not replaced by the replayed effect.
      queueMicrotask(() => {
        // Read the latest generation intentionally; copying it would reintroduce the race.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        if (attachmentGeneration.current === generation) overlay.setMap(null);
      });
    };
  }, [map, overlay]);

  useEffect(() => {
    const fillLayer = new PolygonLayer<HexPolygon>({
      id: "city-shift-hexes",
      data: polygonHexes,
      getPolygon: (item) => item.fillPolygon,
      getFillColor: ({ hex }) => {
        const [r, g, b] = BAND_COLORS[hex.band].rgb;
        if (selectedHex?.h3 === hex.h3) return [255, 255, 255, 135];
        if (highlighted.has(hex.h3)) return [31, 111, 255, 145];
        const alpha = hex.band === "red" ? 78 : hex.band === "yellow" ? 66 : 52;
        return [r, g, b, alpha];
      },
      stroked: false,
      filled: true,
      lineAntialiasing: true,
      pickable: true,
      onClick: ({ object }) => object && onSelect(object.hex),
      updateTriggers: { getFillColor: [selectedHex?.h3, highlightedIds.join("|")] },
    });

    const glowLayer = new PolygonLayer<HexPolygon>({
      id: "city-shift-boundary-glow",
      data: polygonHexes,
      getPolygon: (item) => item.polygon,
      getFillColor: [0, 0, 0, 0],
      getLineColor: ({ hex }) => {
        if (selectedHex?.h3 === hex.h3) return [255, 255, 255, 72];
        if (highlighted.has(hex.h3)) return [122, 174, 255, 76];
        return hexEdgeColor(hex, 24);
      },
      getLineWidth: 2.2,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 2,
      lineWidthMaxPixels: 2.8,
      stroked: true,
      filled: false,
      lineAntialiasing: true,
      pickable: false,
      updateTriggers: { getLineColor: [selectedHex?.h3, highlightedIds.join("|")] },
    });

    const outlineLayer = new PolygonLayer<HexPolygon>({
      id: "city-shift-boundaries",
      data: polygonHexes,
      getPolygon: (item) => item.polygon,
      getFillColor: [0, 0, 0, 0],
      getLineColor: ({ hex }) => {
        if (selectedHex?.h3 === hex.h3) return [255, 255, 255, 225];
        if (highlighted.has(hex.h3)) return [156, 193, 255, 215];
        return hexEdgeColor(hex, 135);
      },
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 1,
      lineWidthMaxPixels: 1.35,
      stroked: true,
      filled: false,
      lineAntialiasing: true,
      pickable: false,
      updateTriggers: { getLineColor: [selectedHex?.h3, highlightedIds.join("|")] },
    });

    const novelLayer = new PolygonLayer<HexPolygon>({
      id: "novel-hexes",
      data: polygonHexes.filter(({ hex }) => hex.novel.length > 0),
      getPolygon: (item) => item.polygon,
      getFillColor: [0, 0, 0, 0],
      getLineColor: [255, 255, 255, 255],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 1,
      lineWidthMaxPixels: 1.5,
      stroked: true,
      filled: false,
      lineAntialiasing: true,
      pickable: false,
    });

    const crashLayer = crashes?.available ? new ScatterplotLayer<CrashPoint>({
      id: "fatal-crashes",
      data: crashes.points,
      visible: showCrashes,
      getPosition: (point) => [point.lng, point.lat],
      getRadius: 8,
      radiusUnits: "meters",
      radiusMinPixels: 3,
      radiusMaxPixels: 7,
      getFillColor: (point) => crashFillColor(crashes.by_hex[point.h3]?.count ?? 1),
      getLineColor: crashRingColor,
      getLineWidth: (point) => point.pedestrian || point.cyclist ? 2 : 1,
      lineWidthUnits: "pixels",
      stroked: true,
      filled: true,
      parameters: { depthCompare: "always", depthWriteEnabled: false },
      pickable: showCrashes,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 220],
      onHover: ({ object, x, y }) => onCrashHover(object ? { point: object, x, y } : null),
      onClick: ({ object, x, y }) => onCrashHover(object ? { point: object, x, y } : null),
    }) : null;

    overlay.setProps({
      layers: [fillLayer, glowLayer, outlineLayer, novelLayer, ...(crashLayer ? [crashLayer] : [])],
      // Google Maps owns the cursor and shows its grab hand everywhere; over a hex or crash dot,
      // show the normal arrow instead. Dragging still shows Google's grabbing hand.
      onHover: ({ object }) => {
        const overHex = Boolean(object);
        if (overHex === arrowCursor.current) return;
        arrowCursor.current = overHex;
        map?.setOptions({ draggableCursor: overHex ? "default" : null });
      },
    });
  }, [crashes, highlighted, highlightedIds, map, onCrashHover, onSelect, overlay, polygonHexes, selectedHex, showCrashes]);

  return null;
}

function FlyToController({ command }: { command?: HexMapProps["flyTo"] }) {
  const map = useMap();

  useEffect(() => {
    if (!map || !command) return;
    map.moveCamera({ center: { lat: command.lat, lng: command.lng }, zoom: command.zoom });
  }, [command, map]);

  return null;
}

function FallbackMap({
  center,
  hexes,
  selectedHex,
  highlightedIds,
  onSelect,
  offline = false,
}: HexMapProps & { offline?: boolean }) {
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);
  const centerPoint = useMemo(() => projectToWorld(center.lat, center.lng, FALLBACK_ZOOM), [center]);
  const tiles = useMemo(() => {
    const startX = Math.floor((centerPoint.x - FALLBACK_WIDTH / 2) / TILE_SIZE);
    const endX = Math.floor((centerPoint.x + FALLBACK_WIDTH / 2) / TILE_SIZE);
    const startY = Math.floor((centerPoint.y - FALLBACK_HEIGHT / 2) / TILE_SIZE);
    const endY = Math.floor((centerPoint.y + FALLBACK_HEIGHT / 2) / TILE_SIZE);
    const visible = [];

    for (let y = startY; y <= endY; y += 1) {
      for (let x = startX; x <= endX; x += 1) {
        visible.push({
          key: `${FALLBACK_ZOOM}-${x}-${y}`,
          href: `https://tile.openstreetmap.org/${FALLBACK_ZOOM}/${x}/${y}.png`,
          x: x * TILE_SIZE - centerPoint.x + FALLBACK_WIDTH / 2,
          y: y * TILE_SIZE - centerPoint.y + FALLBACK_HEIGHT / 2,
        });
      }
    }

    return visible;
  }, [centerPoint]);
  const shapes = useMemo(() => {
    return hexes.map((hex) => ({
      hex,
      points: cellToBoundary(hex.h3)
        .map(([lat, lng]) => {
          const point = projectToWorld(lat, lng, FALLBACK_ZOOM);
          return `${FALLBACK_WIDTH / 2 + point.x - centerPoint.x},${FALLBACK_HEIGHT / 2 + point.y - centerPoint.y}`;
        })
        .join(" "),
    }));
  }, [centerPoint, hexes]);

  return (
    <div className="fallback-map">
      <svg viewBox="0 0 1000 700" role="group" aria-label="Interactive H3 city shift map">
        {!offline && (
          <g className="fallback-tiles" aria-hidden="true">
            {tiles.map((tile) => (
              <image key={tile.key} href={tile.href} x={tile.x} y={tile.y} width={TILE_SIZE} height={TILE_SIZE} />
            ))}
          </g>
        )}
        <g>
          {shapes.map(({ hex, points }, index) => (
            <polygon
              key={hex.h3}
              points={points}
              className={`fallback-hex band-${hex.band}${selectedHex?.h3 === hex.h3 ? " is-selected" : ""}${highlighted.has(hex.h3) ? " is-highlighted" : ""}${hex.novel.length ? " is-novel" : ""}`}
              style={{ animationDelay: `${Math.min(index * 9, 350)}ms` }}
              role="button"
              aria-label={`${hex.shift_score}% shift score${hex.novel.length ? ", novel feature" : ""}`}
              tabIndex={0}
              onClick={() => onSelect(hex)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(hex);
              }}
            />
          ))}
        </g>
      </svg>
      <div className="map-mode"><span /> {offline ? "Offline map" : "Street map preview"}</div>
      {!offline && (
        <div className="map-attribution">
          © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
        </div>
      )}
    </div>
  );
}

export function HexMap(props: HexMapProps) {
  const apiStatus = useApiLoadingStatus();
  const [online, setOnline] = useState(true);
  const [crashHover, setCrashHover] = useState<CrashHover | null>(null);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const googleReady = Boolean(MAPS_API_KEY) && online && apiStatus === APILoadingStatus.LOADED;
  const googleUnavailable = Boolean(MAPS_API_KEY) && (
    !online || apiStatus === APILoadingStatus.FAILED || apiStatus === APILoadingStatus.AUTH_FAILURE
  );
  const availableCrashes = props.crashes?.available ? props.crashes : null;
  const crashLayerAvailable = googleReady && Boolean(availableCrashes?.points.length);

  return (
    <div className="map-wrap">
      {googleReady ? (
        <Map
          defaultCenter={props.center}
          defaultZoom={12}
          gestureHandling="greedy"
          disableDefaultUI
          zoomControl
          renderingType={RenderingType.RASTER}
          styles={DARK_MAP_STYLES}
          className="google-map"
        >
          <FlyToController command={props.flyTo} />
          <DeckOverlay {...props} onCrashHover={setCrashHover} />
        </Map>
      ) : (
        <FallbackMap {...props} offline={!online || googleUnavailable || Boolean(MAPS_API_KEY)} />
      )}
      {crashLayerAvailable && props.onToggleCrashes && (
        <div className={`crash-control${props.showCrashes ? " is-open" : ""}`}>
          <button
            type="button"
            className="crash-toggle"
            aria-expanded={Boolean(props.showCrashes)}
            aria-controls="crash-layer-details"
            onClick={() => {
              setCrashHover(null);
              props.onToggleCrashes?.();
            }}
          >
            <span className="crash-toggle-dot" aria-hidden="true" />
            <span className="crash-toggle-copy">
              <strong>Fatal crashes</strong>
              <small>NHTSA FARS · 2020–24</small>
            </span>
            <b>{props.showCrashes ? "On" : "Off"}</b>
            <ChevronDown className="crash-toggle-chevron" size={17} aria-hidden="true" />
          </button>
          <div id="crash-layer-details" className="crash-details" aria-hidden={!props.showCrashes}>
            <div className="crash-details-inner">
              <div className="crash-summary">
                <strong>{availableCrashes?.total ?? 0}</strong>
                <span>records in this city</span>
              </div>
              <div className="crash-area-key">
                <span>Crashes per area</span>
                <div>
                  <span><i style={{ background: CRASH_COUNT_COLORS.one.hex }} /> 1</span>
                  <span><i style={{ background: CRASH_COUNT_COLORS.few.hex }} /> 2–3</span>
                  <span><i style={{ background: CRASH_COUNT_COLORS.many.hex }} /> 4+</span>
                </div>
              </div>
              <p>Light rings mark pedestrians or cyclists.</p>
            </div>
          </div>
        </div>
      )}
      {props.showCrashes && crashHover && (
        <div className="crash-tooltip" style={{ left: crashHover.x + 12, top: crashHover.y + 12 }} role="status">
          <b>Fatal crash record</b>
          <span>{MONTHS[crashHover.point.month - 1] ?? "Unknown month"} {crashHover.point.year} · {crashTime(crashHover.point.hour)}</span>
          <strong>{crashHover.point.fatalities} {crashHover.point.fatalities === 1 ? "fatality" : "fatalities"}</strong>
          <span>{crashInvolvement(crashHover.point)}</span>
          <span>{crashHover.point.dark ? "Dark conditions" : "Daylight"}</span>
        </div>
      )}
      <Legend />
    </div>
  );
}
