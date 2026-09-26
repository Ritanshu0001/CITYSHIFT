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
        if (selectedHex?.h3 === hex.h3) return [16, 35, 56, 235];
        if (highlighted.has(hex.h3)) return [238, 99, 50, 225];
        return [r, g, b, 164];
      },
      getLineColor: [248, 247, 243, 210],
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
      getLineColor: [11, 36, 59, 255],
      lineWidthMinPixels: 4,
      stroked: true,
      filled: false,
      pickable: false,
    });

    overlayRef.current.setProps({ layers: [fillLayer, novelLayer] });
  }, [hexes, highlighted, highlightedIds, onSelect, selectedHex]);

  return null;
}

function FallbackMap({ hexes, selectedHex, highlightedIds, onSelect }: Omit<HexMapProps, "center">) {
  const highlighted = useMemo(() => new Set(highlightedIds), [highlightedIds]);
  const shapes = useMemo(() => {
    const cells = hexes.map((hex) => ({ hex, boundary: cellToBoundary(hex.h3) }));
    const points = cells.flatMap((cell) => cell.boundary);
    const lats = points.map(([lat]) => lat);
    const lngs = points.map(([, lng]) => lng);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const latSpan = maxLat - minLat || 1;
    const lngSpan = maxLng - minLng || 1;
    return cells.map(({ hex, boundary }) => ({
      hex,
      points: boundary
        .map(([lat, lng]) => `${60 + ((lng - minLng) / lngSpan) * 880},${55 + ((maxLat - lat) / latSpan) * 590}`)
        .join(" "),
    }));
  }, [hexes]);

  return (
    <div className="fallback-map">
      <svg viewBox="0 0 1000 700" role="group" aria-label="Interactive H3 city shift map">
        <g className="fallback-streets" aria-hidden="true">
          <path d="M-20 180 C160 80 245 280 430 200 S710 120 1040 300" />
          <path d="M120 -20 C180 210 390 265 350 720" />
          <path d="M650 -20 C590 160 790 260 720 720" />
          <path d="M-20 520 C220 460 390 610 1020 470" />
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
      <div className="map-mode"><span /> Cartographic preview · add a Maps key for live streets</div>
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
