"use client";

import { Eye, ImageOff } from "lucide-react";
import { cellToLatLng } from "h3-js";
import { useEffect, useRef, useState } from "react";
import { MAPS_API_KEY } from "@/lib/constants";

export function StreetViewPanel({ h3 }: { h3: string }) {
  const elementRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "missing">(MAPS_API_KEY ? "loading" : "missing");

  useEffect(() => {
    if (!MAPS_API_KEY) return;

    let active = true;
    let timer: number | undefined;
    const initialize = () => {
      if (!window.google?.maps?.StreetViewService || !elementRef.current) {
        timer = window.setTimeout(initialize, 250);
        return;
      }
      const [lat, lng] = cellToLatLng(h3);
      const location = { lat, lng };
      new google.maps.StreetViewService().getPanorama(
        { location, radius: 100 },
        (result, requestStatus) => {
          if (!active) return;
          if (requestStatus === google.maps.StreetViewStatus.OK && result?.location?.latLng && elementRef.current) {
            new google.maps.StreetViewPanorama(elementRef.current, {
              position: result.location.latLng,
              pov: { heading: 34, pitch: 0 },
              zoom: 1,
              addressControl: false,
              fullscreenControl: false,
              motionTracking: false,
            });
            setStatus("ready");
          } else {
            setStatus("missing");
          }
        },
      );
    };
    initialize();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [h3]);

  return (
    <section className="streetview-section">
      <div className="mini-heading"><span><Eye size={14} /> Street view</span><small>Nearest panorama · 100 m</small></div>
      <div className={`streetview-frame is-${status}`} ref={elementRef}>
        {status === "loading" && <p>Finding the nearest street…</p>}
        {status === "missing" && <p><ImageOff size={18} /> {MAPS_API_KEY ? "No Street View here" : "Add a Google Maps key to preview the street"}</p>}
      </div>
    </section>
  );
}
