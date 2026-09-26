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

interface CitySuggestion {
  prediction: google.maps.places.PlacePrediction;
  main: string;
  secondary: string;
  requestQuery: string;
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

function normalizedPlaceText(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function SearchBox({ hero = false }: { hero?: boolean }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const suggestionApiRef = useRef<typeof google.maps.places.AutocompleteSuggestion | null>(null);
  const tokenFactoryRef = useRef<typeof google.maps.places.AutocompleteSessionToken | null>(null);
  const sessionTokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null);
  const requestSequenceRef = useRef(0);
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<SelectedPlace | null>(null);
  const [placesReady, setPlacesReady] = useState(false);
  const [suggestions, setSuggestions] = useState<CitySuggestion[]>([]);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const [searchFocused, setSearchFocused] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadPlaces() {
      if (!window.google?.maps?.importLibrary) return;
      try {
        const { AutocompleteSessionToken, AutocompleteSuggestion } = await google.maps.importLibrary("places") as google.maps.PlacesLibrary;
        if (!active) return;
        suggestionApiRef.current = AutocompleteSuggestion;
        tokenFactoryRef.current = AutocompleteSessionToken;
        sessionTokenRef.current = new AutocompleteSessionToken();
        setPlacesReady(true);
      } catch {
        if (active) setPlacesReady(false);
      }
    }

    loadPlaces();

    return () => {
      active = false;
      requestSequenceRef.current += 1;
      suggestionApiRef.current = null;
      tokenFactoryRef.current = null;
      sessionTokenRef.current = null;
    };
  }, []);

  useEffect(() => {
    const text = query.trim();
    if (!placesReady || selection || text.length < 2 || !suggestionApiRef.current) {
      setSuggestions([]);
      setActiveSuggestion(-1);
      return;
    }

    const sequence = ++requestSequenceRef.current;
    const timer = window.setTimeout(async () => {
      try {
        const response = await suggestionApiRef.current!.fetchAutocompleteSuggestions({
          input: text,
          includedPrimaryTypes: ["locality", "sublocality", "administrative_area_level_1", "administrative_area_level_2", "country"],
          language: "en",
          sessionToken: sessionTokenRef.current ?? undefined,
        });
        if (sequence !== requestSequenceRef.current) return;
        const normalizedQuery = normalizedPlaceText(text);
        const nextSuggestions = response.suggestions.flatMap((suggestion) => {
          const prediction = suggestion.placePrediction;
          if (!prediction) return [];
          const nextSuggestion = {
            prediction,
            main: prediction.mainText?.text ?? prediction.text.text,
            secondary: prediction.secondaryText?.text ?? "",
            requestQuery: text,
          };
          const candidateText = normalizedPlaceText(`${nextSuggestion.main} ${nextSuggestion.secondary}`);
          return candidateText.includes(normalizedQuery) ? [nextSuggestion] : [];
        }).slice(0, 5);
        setSuggestions(nextSuggestions);
        setActiveSuggestion(nextSuggestions.length ? 0 : -1);
      } catch {
        if (sequence === requestSequenceRef.current) {
          setSuggestions([]);
          setActiveSuggestion(-1);
        }
      }
    }, 250);

    return () => window.clearTimeout(timer);
  }, [placesReady, query, selection]);

  async function chooseSuggestion(suggestion: CitySuggestion) {
    if (suggestion.requestQuery !== query.trim()) {
      setSuggestions([]);
      setActiveSuggestion(-1);
      return;
    }

    setSuggestions([]);
    setActiveSuggestion(-1);
    setError(null);
    try {
      const place = suggestion.prediction.toPlace();
      await place.fetchFields({
        fields: ["displayName", "formattedAddress", "location", "addressComponents"],
      });
      if (!place.location) throw new Error("That city did not include map coordinates.");

      const name = place.formattedAddress ?? place.displayName ?? suggestion.prediction.text.text;
      const picked = {
        name,
        lat: place.location.lat(),
        lng: place.location.lng(),
        country_code: place.addressComponents
          ?.find((component) => component.types.includes("country"))
          ?.shortText ?? null,
      };
      setSelection(picked);
      setQuery(name);
      if (tokenFactoryRef.current) sessionTokenRef.current = new tokenFactoryRef.current();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "City lookup failed. Try a more specific name.");
    }
  }

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

    throw new Error("City lookup is unavailable. Choose a suggested city or try again in a moment.");
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
        <div className="search-input-slot">
          <label htmlFor={hero ? "hero-city-search" : "city-search"} className="sr-only">
            Search for a city
          </label>
          <input
            ref={inputRef}
            id={hero ? "hero-city-search" : "city-search"}
            value={query}
            onChange={(event) => {
              requestSequenceRef.current += 1;
              setQuery(event.target.value);
              setSelection(null);
              setActiveSuggestion(-1);
              setError(null);
            }}
            onKeyDown={(event) => {
              if (!suggestions.length) return;
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveSuggestion((current) => current >= suggestions.length - 1 ? 0 : current + 1);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveSuggestion((current) => current <= 0 ? suggestions.length - 1 : current - 1);
              } else if (event.key === "Enter" && activeSuggestion >= 0) {
                event.preventDefault();
                void chooseSuggestion(suggestions[activeSuggestion]);
              } else if (event.key === "Escape") {
                setSuggestions([]);
                setActiveSuggestion(-1);
              }
            }}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => window.setTimeout(() => setSearchFocused(false), 120)}
            placeholder="Enter any city"
            autoComplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-controls={`${hero ? "hero-" : ""}city-suggestions`}
            aria-expanded={searchFocused && suggestions.length > 0}
            aria-activedescendant={activeSuggestion >= 0 ? `${hero ? "hero-" : ""}city-suggestion-${activeSuggestion}` : undefined}
          />
          {searchFocused && suggestions.length > 0 && (
            <div
              id={`${hero ? "hero-" : ""}city-suggestions`}
              className="city-suggestions"
              role="listbox"
              aria-label="City suggestions"
            >
              <div className="city-suggestions-label">Suggested cities</div>
              {suggestions.map((suggestion, index) => (
                <button
                  key={suggestion.prediction.placeId}
                  id={`${hero ? "hero-" : ""}city-suggestion-${index}`}
                  type="button"
                  role="option"
                  aria-selected={activeSuggestion === index}
                  className={activeSuggestion === index ? "is-active" : ""}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveSuggestion(index)}
                  onClick={() => chooseSuggestion(suggestion)}
                >
                  <span className="suggestion-icon"><LocateFixed size={16} aria-hidden="true" /></span>
                  <span>
                    <strong>{suggestion.main}</strong>
                    {suggestion.secondary && <small>{suggestion.secondary}</small>}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="search-submit" type="submit" disabled={isLoading}>
          {isLoading ? <LoaderCircle className="spin" size={18} /> : <ArrowRight size={18} />}
          <span>{isLoading ? "Starting" : "Analyze"}</span>
        </button>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div>
  );
}
