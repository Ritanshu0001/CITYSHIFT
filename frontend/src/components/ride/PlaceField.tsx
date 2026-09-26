"use client";

import { MapPin, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { LatLng, Place } from "@/lib/ride";

interface Suggestion {
  prediction: google.maps.places.PlacePrediction;
  main: string;
  secondary: string;
}

interface PlaceFieldProps {
  id: string;
  label: string;
  placeholder: string;
  value: Place | null;
  center: LatLng;
  radiusKm: number;
  kind: "pickup" | "dropoff";
  active: boolean;
  disabled?: boolean;
  onFocus: () => void;
  onChange: (place: Place | null) => void;
}

/** Address search limited to the city's service area (Places API New, same pattern as SearchBox). */
export function PlaceField({ id, label, placeholder, value, center, radiusKm, kind, active, disabled, onFocus, onChange }: PlaceFieldProps) {
  const apiRef = useRef<typeof google.maps.places.AutocompleteSuggestion | null>(null);
  const tokenFactoryRef = useRef<typeof google.maps.places.AutocompleteSessionToken | null>(null);
  const tokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const sequenceRef = useRef(0);
  const [query, setQuery] = useState(value?.label ?? "");
  const [typing, setTyping] = useState(false);
  const [focused, setFocused] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  // A pick from the map or a preset replaces whatever was typed.
  const [shownValue, setShownValue] = useState(value);
  if (value !== shownValue) {
    setShownValue(value);
    setQuery(value?.label ?? "");
    setTyping(false);
  }

  useEffect(() => {
    let live = true;
    (async () => {
      if (!window.google?.maps?.importLibrary) return;
      try {
        const { AutocompleteSessionToken, AutocompleteSuggestion } = await google.maps.importLibrary("places") as google.maps.PlacesLibrary;
        if (!live) return;
        apiRef.current = AutocompleteSuggestion;
        tokenFactoryRef.current = AutocompleteSessionToken;
        tokenRef.current = new AutocompleteSessionToken();
      } catch {
        // No Places: map taps and presets still work.
      }
    })();
    return () => {
      live = false;
      sequenceRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const text = query.trim();
    if (!typing || text.length < 2 || !apiRef.current) {
      setSuggestions([]);
      return;
    }
    const sequence = ++sequenceRef.current;
    const dLat = radiusKm / 110.54;
    const dLng = radiusKm / (111.32 * Math.cos((center.lat * Math.PI) / 180));
    const timer = window.setTimeout(async () => {
      try {
        const { suggestions: results } = await apiRef.current!.fetchAutocompleteSuggestions({
          input: text,
          locationRestriction: { south: center.lat - dLat, north: center.lat + dLat, west: center.lng - dLng, east: center.lng + dLng },
          origin: center,
          sessionToken: tokenRef.current ?? undefined,
        });
        if (sequence !== sequenceRef.current) return;
        setSuggestions(results.flatMap((s) => {
          const p = s.placePrediction;
          return p ? [{ prediction: p, main: p.mainText?.text ?? p.text.text, secondary: p.secondaryText?.text ?? "" }] : [];
        }).slice(0, 5));
      } catch {
        if (sequence === sequenceRef.current) setSuggestions([]);
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, typing, center, radiusKm]);

  async function choose(s: Suggestion) {
    setSuggestions([]);
    try {
      const place = s.prediction.toPlace();
      await place.fetchFields({ fields: ["displayName", "formattedAddress", "location"] });
      if (!place.location) return;
      onChange({ label: s.main, detail: s.secondary || place.formattedAddress || undefined, lat: place.location.lat(), lng: place.location.lng() });
      if (tokenFactoryRef.current) tokenRef.current = new tokenFactoryRef.current();
    } catch {
      // Leave the typed text; the rider can tap the map instead.
    }
  }

  return (
    <div className={`ride-field${active ? " is-active" : ""}`}>
      <span className={`ride-field-dot is-${kind}`} aria-hidden="true" />
      <label htmlFor={id} className="sr-only">{label}</label>
      <input
        id={id}
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={focused && suggestions.length > 0}
        aria-controls={`${id}-suggestions`}
        onFocus={() => {
          setFocused(true);
          onFocus();
        }}
        onBlur={() => window.setTimeout(() => setFocused(false), 120)}
        onChange={(event) => {
          setQuery(event.target.value);
          setTyping(true);
        }}
      />
      {value && !disabled && (
        <button type="button" className="ride-field-clear" aria-label={`Clear ${label.toLowerCase()}`} onClick={() => onChange(null)}>
          <X size={14} />
        </button>
      )}
      {focused && suggestions.length > 0 && (
        <div id={`${id}-suggestions`} className="ride-suggestions" role="listbox" aria-label={`${label} suggestions`}>
          {suggestions.map((s) => (
            <button key={s.prediction.placeId} type="button" role="option" aria-selected="false"
              onMouseDown={(event) => event.preventDefault()} onClick={() => choose(s)}>
              <MapPin size={15} aria-hidden="true" />
              <span><strong>{s.main}</strong>{s.secondary && <small>{s.secondary}</small>}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
