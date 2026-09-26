"use client";

import { ArrowRight, LoaderCircle, LocateFixed } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { analyze } from "@/lib/api";

interface SelectedPlace {
  name: string;
  lat: number;
  lng: number;
  country_code: string | null;
}

const DEMO_PLACES: Record<string, SelectedPlace> = {
  "new york": { name: "New York, NY, USA", lat: 40.7128, lng: -74.006, country_code: "US" },
  london: { name: "London, UK", lat: 51.5072, lng: -0.1276, country_code: "GB" },
  phoenix: { name: "Phoenix, AZ, USA", lat: 33.4484, lng: -112.074, country_code: "US" },
  tokyo: { name: "Tokyo, Japan", lat: 35.6762, lng: 139.6503, country_code: "JP" },
};

function countryCode(components?: google.maps.GeocoderAddressComponent[]) {
  return components?.find((part) => part.types.includes("country"))?.short_name ?? null;
}

export function SearchBox({ hero = false }: { hero?: boolean }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<SelectedPlace | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let autocomplete: google.maps.places.Autocomplete | undefined;
    let tries = 0;

    const attach = () => {
      if (!inputRef.current || !window.google?.maps?.places?.Autocomplete) return false;
      autocomplete = new google.maps.places.Autocomplete(inputRef.current, {
        types: ["(cities)"],
        fields: ["geometry", "name", "formatted_address", "address_components"],
      });
      autocomplete.addListener("place_changed", () => {
        const place = autocomplete?.getPlace();
        const location = place?.geometry?.location;
        if (!place || !location) return;
        const picked = {
          name: place.formatted_address ?? place.name ?? inputRef.current?.value ?? "Selected city",
          lat: location.lat(),
          lng: location.lng(),
          country_code: countryCode(place.address_components),
        };
        setSelection(picked);
        setQuery(picked.name);
      });
      return true;
    };

    if (attach()) return () => google.maps.event.clearInstanceListeners(autocomplete!);
    const timer = window.setInterval(() => {
      tries += 1;
      if (attach() || tries > 20) window.clearInterval(timer);
    }, 400);

    return () => {
      window.clearInterval(timer);
      if (autocomplete && window.google) google.maps.event.clearInstanceListeners(autocomplete);
    };
  }, []);

  async function resolvePlace(): Promise<SelectedPlace> {
    if (selection) return selection;

    const normalized = query.trim().toLowerCase();
    const demo = Object.entries(DEMO_PLACES).find(([key]) => normalized.includes(key))?.[1];
    if (demo) return demo;

    if (window.google?.maps?.Geocoder) {
      const response = await new google.maps.Geocoder().geocode({ address: query });
      const result = response.results[0];
      if (result) {
        return {
          name: result.formatted_address,
          lat: result.geometry.location.lat(),
          lng: result.geometry.location.lng(),
          country_code: countryCode(result.address_components),
        };
      }
    }

    return { ...DEMO_PLACES["new york"], name: query.trim() || DEMO_PLACES["new york"].name };
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) {
      inputRef.current?.focus();
      return;
    }

    setError(null);
    setIsLoading(true);
    try {
      const place = await resolvePlace();
      const response = await analyze(place);
      router.push(`/city/${response.slug}?job=${response.job_id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "City lookup failed. Try a more specific name.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className={hero ? "search-shell search-shell-hero" : "search-shell"}>
      <form className="search-form" onSubmit={handleSubmit}>
        <LocateFixed size={18} aria-hidden="true" />
        <label htmlFor={hero ? "hero-city-search" : "city-search"} className="sr-only">
          Search for a city
        </label>
        <input
          ref={inputRef}
          id={hero ? "hero-city-search" : "city-search"}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelection(null);
          }}
          placeholder="Enter any city"
          autoComplete="off"
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? <LoaderCircle className="spin" size={18} /> : <ArrowRight size={18} />}
          <span>{isLoading ? "Starting" : "Analyze"}</span>
        </button>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div>
  );
}
