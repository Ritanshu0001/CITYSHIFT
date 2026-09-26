"use client";

import { Map, RenderingType, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useMemo, useRef } from "react";
import { cumulative, describeCrash, pointAlong, type LatLng, type Place, type RoutePlan } from "@/lib/ride";

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
  selected: "#0b72ff",
  casing: "#0a3f93",
  alternate: "#a9b1c3",
  trail: "#00b39f",
  onRoute: "#f8bf47",
  avoided: "#ff5262",
  ink: "#101426",
};

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

function circleIcon(fill: string, stroke: string, scale: number, fillOpacity = 1): google.maps.Symbol {
  return { path: google.maps.SymbolPath.CIRCLE, fillColor: fill, fillOpacity, strokeColor: stroke, strokeWeight: 2, scale };
}

function Overlays({ center, radiusKm, pickup, dropoff, plan, selectedId, onSelectRoute, progress, padding }: RideMapProps) {
  const map = useMap();
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;

  // Service area: the radius the routing graph covers.
  useEffect(() => {
    if (!map) return;
    const circle = new google.maps.Circle({
      map, center, radius: radiusKm * 1000, clickable: false,
      strokeColor: COLORS.selected, strokeOpacity: 0.25, strokeWeight: 1.5, fillOpacity: 0,
    });
    return () => circle.setMap(null);
  }, [map, center, radiusKm]);

  // Route options: alternates in grey (click to pick), the selected one on top with a casing.
  useEffect(() => {
    if (!map || !plan) return;
    const lines: google.maps.Polyline[] = [];
    for (const route of plan.routes) {
      const path = route.path.map(([lat, lng]) => ({ lat, lng }));
      if (route.id === selectedId) {
        lines.push(new google.maps.Polyline({ map, path, strokeColor: COLORS.casing, strokeWeight: 10, strokeOpacity: 0.9, zIndex: 20, clickable: false }));
        lines.push(new google.maps.Polyline({ map, path, strokeColor: COLORS.selected, strokeWeight: 6, zIndex: 21, clickable: false }));
      } else {
        const line = new google.maps.Polyline({ map, path, strokeColor: COLORS.alternate, strokeWeight: 6, strokeOpacity: 0.85, zIndex: 10 });
        line.addListener("click", () => onSelectRoute(route.id));
        lines.push(line);
      }
    }
    return () => lines.forEach((line) => line.setMap(null));
  }, [map, plan, selectedId, onSelectRoute]);

  // Crash sites: amber on the selected route, red rings where it steers around the fastest route's sites.
  useEffect(() => {
    if (!map || !plan || !selected) return;
    const markers: google.maps.Marker[] = [];
    const add = (index: number, onRoute: boolean) => {
      const site = plan.crashes[String(index)];
      if (!site) return;
      markers.push(new google.maps.Marker({
        map,
        position: site,
        icon: onRoute ? circleIcon(COLORS.onRoute, COLORS.ink, 6) : circleIcon(COLORS.avoided, COLORS.avoided, 6, 0.18),
        title: `${onRoute ? "On your route" : "Avoided"} · ${site.street ?? "Fatal crash site"} · ${describeCrash(site)}`,
        zIndex: onRoute ? 40 : 30,
      }));
    };
    selected.avoided_sites.forEach((i) => add(i, false));
    selected.crash_sites.forEach((i) => add(i, true));
    return () => markers.forEach((marker) => marker.setMap(null));
  }, [map, plan, selected]);

  // Pickup (round) and drop-off (square), like a ride app.
  useEffect(() => {
    if (!map) return;
    const markers: google.maps.Marker[] = [];
    if (pickup) {
      markers.push(new google.maps.Marker({ map, position: pickup, zIndex: 60, title: `Pickup · ${pickup.label}`, icon: circleIcon(COLORS.ink, "#ffffff", 8) }));
    }
    if (dropoff) {
      markers.push(new google.maps.Marker({
        map, position: dropoff, zIndex: 60, title: `Drop-off · ${dropoff.label}`,
        icon: { path: "M -7 -7 L 7 -7 L 7 7 L -7 7 Z", fillColor: COLORS.ink, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2.5, scale: 1 },
      }));
    }
    return () => markers.forEach((marker) => marker.setMap(null));
  }, [map, pickup, dropoff]);

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

  // The ride: a car arrow moving along the route, with the driven part drawn as a trail.
  const cum = useMemo(() => (selected ? cumulative(selected.path) : null), [selected]);
  const carRef = useRef<google.maps.Marker | null>(null);
  const trailRef = useRef<google.maps.Polyline | null>(null);

  useEffect(() => {
    if (!map || progress === null) return;
    carRef.current = new google.maps.Marker({ map, zIndex: 80, clickable: false });
    trailRef.current = new google.maps.Polyline({ map, strokeColor: COLORS.trail, strokeWeight: 6, zIndex: 25, clickable: false });
    return () => {
      carRef.current?.setMap(null);
      trailRef.current?.setMap(null);
      carRef.current = null;
      trailRef.current = null;
    };
  }, [map, progress === null]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected || !cum || progress === null || !carRef.current || !trailRef.current) return;
    const at = pointAlong(selected.path, cum, progress);
    carRef.current.setPosition(at);
    carRef.current.setIcon({
      path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
      scale: 6, rotation: at.heading, fillColor: "#ffffff", fillOpacity: 1, strokeColor: COLORS.ink, strokeWeight: 2.5,
    });
    trailRef.current.setPath([...selected.path.slice(0, at.index).map(([lat, lng]) => ({ lat, lng })), at]);
  }, [selected, cum, progress]);

  return null;
}
