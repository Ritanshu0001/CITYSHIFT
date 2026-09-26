"use client";

import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { Map, useMap } from "@vis.gl/react-google-maps";
import { cellToBoundary } from "h3-js";
import { useEffect, useMemo, useRef } from "react";
import { BAND_COLORS, MAPS_API_KEY } from "@/lib/constants";
import type { Center, CityHex } from "@/lib/types";
import { Legend } from "./Legend";

interface HexMapProps {
  center: Center;
  hexes: CityHex[];
  selectedHex: CityHex | null;
  highlightedIds: string[];
  onSelect: (hex: CityHex) => void;
}

const FALLBACK_ZOOM = 12;
const TILE_SIZE = 256;
const FALLBACK_WIDTH = 1000;
const FALLBACK_HEIGHT = 700;

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
  { elementType: "labels.text.fill", stylers: [{ color: "#78829c" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#111629" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#343c56" }] },
  { featureType: "landscape", elementType: "geometry", stylers: [{ color: "#151b30" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#1a2138" }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#303950" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#111629" }] },
  { featureType: "road.arterial", elementType: "geometry", stylers: [{ color: "#46516e" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#64708c" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#171d31" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#222a43" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#080c18" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#59637c" }] },
];

function DeckOverlay({ hexes, selectedHex, highlightedIds, onSelect }: Omit<HexMapProps, "center">) {
  const map = useMap();
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);

  useEffect(() => {
    if (!map) return;
    const overlay = new GoogleMapsOverlay({ layers: [] });
    overlay.setMap(map);
    overlayRef.current = overlay;
    return () => {
      overlay.setMap(null);
      overlay.finalize();
      overlayRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    if (!overlayRef.current) return;
    const fillLayer = new H3HexagonLayer<CityHex>({
      id: "city-shift-hexes",
      data: hexes,
      getHexagon: (hex) => hex.h3,
      getFillColor: (hex) => {
        const [r, g, b] = BAND_COLORS[hex.band].rgb;
        if (selectedHex?.h3 === hex.h3) return [255, 255, 255, 238];
        if (highlighted.has(hex.h3)) return [31, 111, 255, 235];
        return [r, g, b, 184];
      },
      getLineColor: [10, 14, 28, 220],
      lineWidthMinPixels: 1,
      stroked: true,
      filled: true,
      pickable: true,
      onClick: ({ object }) => object && onSelect(object),
      updateTriggers: { getFillColor: [selectedHex?.h3, highlightedIds.join("|")] },
    });

    const novelLayer = new H3HexagonLayer<CityHex>({
      id: "novel-hexes",
      data: hexes.filter((hex) => hex.novel.length > 0),
      getHexagon: (hex) => hex.h3,
      getFillColor: [0, 0, 0, 0],
      getLineColor: [255, 255, 255, 245],
      lineWidthMinPixels: 3,
      stroked: true,
      filled: false,
      pickable: false,
    });

    overlayRef.current.setProps({ layers: [fillLayer, novelLayer] });
  }, [hexes, highlighted, highlightedIds, onSelect, selectedHex]);

  return null;
}

function FallbackMap({ center, hexes, selectedHex, highlightedIds, onSelect }: HexMapProps) {
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
        <g className="fallback-tiles" aria-hidden="true">
          {tiles.map((tile) => (
            <image key={tile.key} href={tile.href} x={tile.x} y={tile.y} width={TILE_SIZE} height={TILE_SIZE} />
          ))}
        </g>
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
      <div className="map-mode"><span /> Live OSM streets · add Google key for Places + Street View</div>
      <div className="map-attribution">
        © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>
      </div>
    </div>
  );
}

export function HexMap(props: HexMapProps) {
  return (
    <div className="map-wrap">
      {MAPS_API_KEY ? (
        <Map
          defaultCenter={props.center}
          defaultZoom={12}
          gestureHandling="greedy"
          disableDefaultUI
          zoomControl
          styles={DARK_MAP_STYLES}
          className="google-map"
        >
          <DeckOverlay {...props} />
        </Map>
      ) : (
        <FallbackMap {...props} />
      )}
      <Legend />
    </div>
  );
}
