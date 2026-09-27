"use client";

import { Map, RenderingType, useMap } from "@vis.gl/react-google-maps";
import { cellToBoundary } from "h3-js";
import { useEffect, useMemo, useRef } from "react";
import { BAND_COLORS } from "@/lib/constants";
import { cumulative, describeRisk, pointAlong, type LatLng, type Place, type RideRoute, type RoutePlan } from "@/lib/ride";

// Native Google polylines and markers rather than deck.gl: routes are polylines anyway, and the
// native overlays render the same in every browser engine.

const LIGHT_STYLES: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#f3f5f9" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#5d6478" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#f3f5f9" }, { weight: 3 }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#e1efe6" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#e3e7ef" }] },
  { featureType: "road.arterial", elementType: "labels.text.fill", stylers: [{ color: "#737b90" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#fdfdfe" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#d5dbe6" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#cfe0f3" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#7d97b8" }] },
];

const COLORS = {
  fastest: "#f05263",
  balanced: "#147af3",
  safest: "#12a36d",
  casing: "#ffffff",
  alternate: "#7d879b",
  onRoute: "#f07a2b",
  avoided: "#d46b76",
  ink: "#243047",
};

function routeColor(label: RideRoute["label"]) {
  if (label === "Fastest") return COLORS.fastest;
  if (label === "Balanced") return COLORS.balanced;
  return COLORS.safest;
}

function endpointIcon(kind: "pickup" | "dropoff"): google.maps.Icon {
  const symbol = kind === "pickup"
    ? `<circle cx="16" cy="16" r="3.2" fill="#fff"/>`
    : `<path d="M11.5 21.5V10.2M12.8 11.4h7.8l-2 2.9 2 2.9h-7.8" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>`;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <defs>
        <filter id="s" x="-45%" y="-45%" width="190%" height="205%">
          <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#101426" flood-opacity=".26"/>
        </filter>
      </defs>
      <circle cx="16" cy="16" r="11.8" fill="#151923" stroke="#fff" stroke-width="2" filter="url(#s)"/>
      ${symbol}
    </svg>`;
  return {
    url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    scaledSize: new google.maps.Size(28, 28),
    anchor: new google.maps.Point(14, 14),
  };
}

function riskSiteIcon(onRoute: boolean): google.maps.Icon {
  const stroke = onRoute ? COLORS.onRoute : COLORS.avoided;
  const width = onRoute ? 19 : 16;
  const height = onRoute ? 22 : 19;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 27">
      <defs>
        <filter id="s" x="-55%" y="-45%" width="210%" height="205%">
          <feDropShadow dx="0" dy="1" stdDeviation="1" flood-color="#243047" flood-opacity=".2"/>
        </filter>
      </defs>
      <g filter="url(#s)">
        <path d="M12 2.4 21 6.1v7.7c0 6.2-3.6 11.2-9 14.2-5.4-3-9-8-9-14.2V6.1L12 2.4Z" fill="#fff" fill-opacity=".74" stroke="#fff" stroke-width="4" stroke-linejoin="round"/>
        <path d="M12 2.4 21 6.1v7.7c0 6.2-3.6 11.2-9 14.2-5.4-3-9-8-9-14.2V6.1L12 2.4Z" fill="none" stroke="${stroke}" stroke-width="2.1" stroke-linejoin="round"/>
        <path d="M12 8.3v8" fill="none" stroke="${stroke}" stroke-width="2.3" stroke-linecap="round"/>
        <circle cx="12" cy="20.5" r="1.3" fill="${stroke}"/>
      </g>
    </svg>`;
  return {
    url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    scaledSize: new google.maps.Size(width, height),
    anchor: new google.maps.Point(width / 2, height / 2),
  };
}

function waymoCarImage(accent: string) {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 64">
      <defs>
        <linearGradient id="body" x1="0" y1="0" x2="1" y2="1">
          <stop stop-color="#ffffff"/>
          <stop offset=".58" stop-color="#f3f5f7"/>
          <stop offset="1" stop-color="#d8dde3"/>
        </linearGradient>
        <linearGradient id="glass" x1="0" y1="0" x2="0" y2="1">
          <stop stop-color="#35404c"/>
          <stop offset="1" stop-color="#111720"/>
        </linearGradient>
        <filter id="s" x="-35%" y="-25%" width="170%" height="175%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.2" flood-color="#101426" flood-opacity=".35"/>
        </filter>
      </defs>
      <g filter="url(#s)">
        <rect x="6" y="14" width="5" height="12" rx="2.5" fill="#151a22"/>
        <rect x="37" y="14" width="5" height="12" rx="2.5" fill="#151a22"/>
        <rect x="6" y="40" width="5" height="12" rx="2.5" fill="#151a22"/>
        <rect x="37" y="40" width="5" height="12" rx="2.5" fill="#151a22"/>
        <path d="M24 2.5C15 2.5 10.5 8.2 9.5 17l-1.2 29.6c-.4 9.6 5.5 14.9 15.7 14.9s16.1-5.3 15.7-14.9L38.5 17C37.5 8.2 33 2.5 24 2.5Z" fill="url(#body)" stroke="#202630" stroke-width="1.4"/>
        <path d="M14.2 17.4c1.5-6.7 4.2-9.4 9.8-9.4s8.3 2.7 9.8 9.4l-2.7 6.1H16.9l-2.7-6.1Z" fill="url(#glass)"/>
        <path d="M14.9 45.8h18.2l1 7.8c-2.8 3.1-6.1 4.5-10.1 4.5s-7.3-1.4-10.1-4.5l1-7.8Z" fill="#141a22"/>
        <path d="M15.8 25.2 14.9 43h18.2l-.9-17.8H15.8Z" fill="#dfe4e9" stroke="#a9b1bc" stroke-width=".8"/>
        <path d="M10.3 30.5h3.5M34.2 30.5h3.5" stroke="${accent}" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M14.2 6.8c2.8-2.8 6-4.1 9.8-4.1s7 1.3 9.8 4.1" fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round" opacity=".9"/>
        <rect x="7.6" y="22" width="4" height="7" rx="2" fill="#eef1f4" stroke="#343b45" stroke-width=".8"/>
        <rect x="36.4" y="22" width="4" height="7" rx="2" fill="#eef1f4" stroke="#343b45" stroke-width=".8"/>
        <circle cx="24" cy="34" r="7" fill="#f8fafc" stroke="#202630" stroke-width="1.4"/>
        <circle cx="24" cy="34" r="4.4" fill="#3f4854" stroke="#0f141b" stroke-width="1"/>
        <circle cx="24" cy="34" r="2.1" fill="#d7dde3"/>
        <circle cx="22.6" cy="32.9" r=".75" fill="#147af3"/>
        <circle cx="25.4" cy="32.9" r=".75" fill="#12a36d"/>
        <circle cx="24" cy="35.5" r=".75" fill="#7957d5"/>
        <path d="M16 59c2.4 1.6 5.1 2.4 8 2.4s5.6-.8 8-2.4" fill="none" stroke="${accent}" stroke-width="1.5" stroke-linecap="round"/>
      </g>
    </svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

export interface RideMapProps {
  center: LatLng;
  radiusKm: number;
  pickup: Place | null;
  dropoff: Place | null;
  plan: RoutePlan | null;
  selectedId: string | null;
  onSelectRoute: (id: string) => void;
  onMapClick: (point: LatLng) => void;
  /** Metres travelled along the selected route while riding, else null. */
  progress: number | null;
  /** Keeps fitted routes clear of the side panel. */
  padding: google.maps.Padding;
}

export function RideMap(props: RideMapProps) {
  return (
    <Map
      key={`${props.center.lat},${props.center.lng}`}
      defaultCenter={props.center}
      defaultZoom={12}
      gestureHandling="greedy"
      disableDefaultUI
      zoomControl
      clickableIcons={false}
      renderingType={RenderingType.RASTER}
      styles={LIGHT_STYLES}
      className="ride-map"
      onClick={(event) => event.detail.latLng && props.onMapClick(event.detail.latLng)}
    >
      <Overlays {...props} />
    </Map>
  );
}

function Overlays({ center, radiusKm, pickup, dropoff, plan, selectedId, onSelectRoute, progress, padding }: RideMapProps) {
  const map = useMap();
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;

  // Service area: the radius the routing graph covers.
  useEffect(() => {
    if (!map) return;
    const circle = new google.maps.Circle({
      map, center, radius: radiusKm * 1000, clickable: false,
      strokeColor: COLORS.balanced, strokeOpacity: 0.2, strokeWeight: 1.5, fillOpacity: 0,
    });
    return () => circle.setMap(null);
  }, [map, center, radiusKm]);

  // Hex layer, under everything: the shift-score areas the selected route passes through, which
  // weight its intersections. Risk sites (the crash layer) sit on top.
  useEffect(() => {
    if (!map || !plan || !selected) return;
    const polygons = selected.hexes.flatMap((cell) => {
      const area = plan.areas[cell];
      if (!area) return [];
      const color = BAND_COLORS[area.band].hex;
      return [new google.maps.Polygon({
        map,
        paths: cellToBoundary(cell).map(([lat, lng]) => ({ lat, lng })),
        clickable: false,
        fillColor: color,
        fillOpacity: area.band === "red" ? 0.16 : 0.12,
        strokeColor: color,
        strokeOpacity: 0.45,
        strokeWeight: 1,
        zIndex: 1,
      })];
    });
    return () => polygons.forEach((polygon) => polygon.setMap(null));
  }, [map, plan, selected]);

  // Route options: one restrained active line, with quieter alternates underneath.
  useEffect(() => {
    if (!map || !plan) return;
    const lines: google.maps.Polyline[] = [];
    for (const route of plan.routes) {
      const path = route.path.map(([lat, lng]) => ({ lat, lng }));
      if (route.id === selectedId) {
        lines.push(new google.maps.Polyline({ map, path, strokeColor: COLORS.ink, strokeWeight: 8, strokeOpacity: 0.12, zIndex: 19, clickable: false }));
        lines.push(new google.maps.Polyline({ map, path, strokeColor: COLORS.casing, strokeWeight: 6.5, strokeOpacity: 0.86, zIndex: 20, clickable: false }));
        lines.push(new google.maps.Polyline({ map, path, strokeColor: routeColor(route.label), strokeWeight: 4.25, strokeOpacity: 0.96, zIndex: 21, clickable: false }));
      } else {
        const line = new google.maps.Polyline({ map, path, strokeColor: COLORS.alternate, strokeWeight: 2.5, strokeOpacity: 0.46, zIndex: 10 });
        const hitArea = new google.maps.Polyline({ map, path, strokeColor: COLORS.alternate, strokeWeight: 14, strokeOpacity: 0.01, zIndex: 9 });
        hitArea.addListener("click", () => onSelectRoute(route.id));
        lines.push(line, hitArea);
      }
    }
    return () => lines.forEach((line) => line.setMap(null));
  }, [map, plan, selectedId, onSelectRoute]);

  // Risk sites retain their true record coordinates. Shields distinguish them from trip endpoints.
  useEffect(() => {
    if (!map || !plan || !selected) return;
    const markers: google.maps.Marker[] = [];
    const add = (index: number, onRoute: boolean) => {
      const site = plan.crashes[String(index)];
      if (!site) return;
      markers.push(new google.maps.Marker({
        map,
        position: site,
        icon: riskSiteIcon(onRoute),
        opacity: onRoute ? 1 : 0.68,
        title: `${onRoute ? "Near your route" : "Avoided"} · ${site.street ?? "Risk area"} · ${describeRisk(site)}`,
        zIndex: onRoute ? 40 : 30,
      }));
    };
    selected.avoided_sites.forEach((i) => add(i, false));
    selected.crash_sites.forEach((i) => add(i, true));
    return () => markers.forEach((marker) => marker.setMap(null));
  }, [map, plan, selected]);

  // Pin endpoints to the routed road geometry, not the raw searched coordinate, so line and marker meet.
  useEffect(() => {
    if (!map) return;
    const markers: google.maps.Marker[] = [];
    const first = selected?.path[0];
    const last = selected?.path.at(-1);
    const pickupPosition = first ? { lat: first[0], lng: first[1] } : pickup;
    const dropoffPosition = last ? { lat: last[0], lng: last[1] } : dropoff;
    if (pickup && pickupPosition) {
      markers.push(new google.maps.Marker({ map, position: pickupPosition, zIndex: 60, title: `Pickup · ${pickup.label}`, icon: endpointIcon("pickup") }));
    }
    if (dropoff && dropoffPosition) {
      markers.push(new google.maps.Marker({
        map, position: dropoffPosition, zIndex: 60, title: `Drop-off · ${dropoff.label}`,
        icon: endpointIcon("dropoff"),
      }));
    }
    return () => markers.forEach((marker) => marker.setMap(null));
  }, [map, pickup, dropoff, selected]);

  // Frame the trip: every route option when a plan lands, else whichever endpoints exist.
  useEffect(() => {
    if (!map) return;
    const points = plan ? plan.routes.flatMap((r) => r.path.map(([lat, lng]) => ({ lat, lng }))) : [pickup, dropoff].filter((p): p is Place => Boolean(p));
    if (points.length === 0) return;
    if (points.length === 1) {
      map.panTo(points[0]);
      if ((map.getZoom() ?? 12) < 13) map.setZoom(14);
      return;
    }
    const bounds = new google.maps.LatLngBounds();
    points.forEach((p) => bounds.extend(p));
    map.fitBounds(bounds, padding);
    // Refit only when the trip changes, not on every padding object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, plan, pickup, dropoff]);

  // The ride: a compositor-friendly DOM overlay avoids reloading a rotated marker image each frame.
  const cum = useMemo(() => (selected ? cumulative(selected.path) : null), [selected]);
  const carRef = useRef<{ setPose: (position: google.maps.LatLngLiteral, heading: number) => void; setMap: (map: google.maps.Map | null) => void } | null>(null);
  const trailRef = useRef<google.maps.Polyline | null>(null);
  const headingRef = useRef<number | null>(null);

  useEffect(() => {
    if (!map || progress === null || !selected) return;
    const element = document.createElement("div");
    element.dataset.rideCar = "true";
    element.setAttribute("aria-hidden", "true");
    element.style.cssText = [
      "position:absolute",
      "width:32px",
      "height:43px",
      `background:url("${waymoCarImage(routeColor(selected.label))}") center/contain no-repeat`,
      "pointer-events:none",
      "transform:translate3d(-50%,-50%,0)",
      "transform-origin:center",
      "will-change:left,top,transform",
      "z-index:80",
    ].join(";");

    class CarOverlay extends google.maps.OverlayView {
      private position: google.maps.LatLngLiteral | null = null;
      private heading = 0;

      onAdd() {
        this.getPanes()?.overlayMouseTarget.appendChild(element);
      }

      draw() {
        if (!this.position) return;
        const projection = this.getProjection?.();
        if (!projection) return;
        const pixel = projection.fromLatLngToDivPixel(new google.maps.LatLng(this.position));
        if (!pixel) return;
        element.style.left = `${pixel.x}px`;
        element.style.top = `${pixel.y}px`;
        element.style.transform = `translate3d(-50%,-50%,0) rotate(${this.heading}deg)`;
      }

      setPose(position: google.maps.LatLngLiteral, heading: number) {
        this.position = position;
        this.heading = heading;
        this.draw();
      }

      onRemove() {
        element.remove();
      }
    }

    const car = new CarOverlay();
    car.setMap(map);
    carRef.current = car;
    headingRef.current = null;
    trailRef.current = new google.maps.Polyline({ map, strokeColor: COLORS.balanced, strokeWeight: 4, strokeOpacity: 0.92, zIndex: 25, clickable: false });
    return () => {
      carRef.current?.setMap(null);
      trailRef.current?.setMap(null);
      carRef.current = null;
      trailRef.current = null;
      headingRef.current = null;
    };
  }, [map, progress === null, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected || !cum || progress === null || !carRef.current || !trailRef.current) return;
    const at = pointAlong(selected.path, cum, progress);
    const accent = routeColor(selected.label);
    const previous = headingRef.current ?? at.heading;
    const delta = ((at.heading - previous + 540) % 360) - 180;
    const heading = (previous + delta * 0.16 + 360) % 360;
    headingRef.current = Math.abs(delta) < 0.2 ? at.heading : heading;
    carRef.current.setPose(at, headingRef.current);
    trailRef.current.setOptions({ strokeColor: accent });
    trailRef.current.setPath([...selected.path.slice(0, at.index).map(([lat, lng]) => ({ lat, lng })), at]);
  }, [selected, cum, progress]);

  return null;
}
