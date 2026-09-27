"use client";

import { ArrowDownUp, LoaderCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { MAPS_API_KEY } from "@/lib/constants";
import {
  cityStatus, cumulative, distanceAlong, getRideCities, planRoutes, prepareCity, PRESET_TRIPS, RideError,
  type LatLng, type Place, type RideCity, type RoutePlan, type RoutingState,
} from "@/lib/ride";
import { PlaceField } from "./PlaceField";
import { RideMap } from "./RideMap";
import { RoutePanel } from "./RoutePanel";
import { Arrived, RideProgress, type PassedSite } from "./RideStatus";

type Phase = "plan" | "riding" | "arrived";
type Field = "pickup" | "dropoff";

const DEFAULT_CITY = "new-york-ny-usa";
const PANEL_PADDING = { top: 60, right: 60, bottom: 60, left: 470 };
const MOBILE_PADDING = { top: 40, right: 30, bottom: 380, left: 30 };
// A ride plays at about one second per trip minute, within bounds that keep it watchable.
const RIDE_SECONDS = (tripS: number) => Math.min(40, Math.max(12, tripS / 60));

const DROPPED_PIN = "Dropped pin";

/** Once a plan names the street a pin snapped to, "Dropped pin" becomes "Near West Street". */
function nameDroppedPin(place: Place | null, street: string | null): Place | null {
  return place && place.label === DROPPED_PIN && street ? { ...place, label: `Near ${street}` } : place;
}

export function SafeJourney() {
  const [cities, setCities] = useState<RideCity[] | null>(null);
  const [citiesError, setCitiesError] = useState<string | null>(null);
  const [slug, setSlug] = useState(DEFAULT_CITY);
  const [routing, setRouting] = useState<{ status: RoutingState; error: string | null }>({ status: "idle", error: null });
  const [pickup, setPickup] = useState<Place | null>(null);
  const [dropoff, setDropoff] = useState<Place | null>(null);
  const [activeField, setActiveField] = useState<Field>("pickup");
  const [result, setResult] = useState<{ trip: string; plan?: RoutePlan; error?: string } | null>(null);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("plan");
  const [progress, setProgress] = useState(0);
  const [mobile, setMobile] = useState(false);

  const city = cities?.find((c) => c.slug === slug) ?? null;

  useEffect(() => {
    getRideCities()
      .then((list) => {
        setCities(list);
        if (list.length && !list.some((c) => c.slug === DEFAULT_CITY)) setSlug(list[0].slug);
      })
      .catch((caught) => setCitiesError(caught instanceof Error ? caught.message : "Could not load cities"));
  }, []);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  // Build (or load) the city's routing graph, then poll until it's ready.
  useEffect(() => {
    if (!city) return;
    let live = true;
    let timer: number | undefined;
    const poll = async (first: boolean) => {
      try {
        const state = first ? await prepareCity(city.slug) : await cityStatus(city.slug);
        if (!live) return;
        setRouting(state);
        if (state.status === "building") timer = window.setTimeout(() => poll(false), 1500);
      } catch (caught) {
        if (live) setRouting({ status: "error", error: caught instanceof Error ? caught.message : "Routing unavailable" });
      }
    };
    poll(true);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [city]);

  // Keyed on coordinates, so relabelling a dropped pin with its street name doesn't re-plan.
  const origin = useMemo(() => (pickup ? { lat: pickup.lat, lng: pickup.lng } : null), [pickup?.lat, pickup?.lng]); // eslint-disable-line react-hooks/exhaustive-deps
  const destination = useMemo(() => (dropoff ? { lat: dropoff.lat, lng: dropoff.lng } : null), [dropoff?.lat, dropoff?.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  // Plan as soon as both ends are set and the network is ready. Each result is tagged with the
  // trip it answers, so a stale response never shows for a different pickup or drop-off.
  const trip = city && origin && destination
    ? `${city.slug}|${origin.lat},${origin.lng}|${destination.lat},${destination.lng}`
    : null;
  const current = result && result.trip === trip ? result : null;
  const plan = current?.plan ?? null;
  const planError = current?.error ?? null;
  const planning = Boolean(trip && routing.status === "ready" && !current);

  useEffect(() => {
    if (!trip || !city || !origin || !destination || routing.status !== "ready") return;
    let live = true;
    planRoutes(city.slug, origin, destination)
      .then((next) => {
        if (!live) return;
        setResult({ trip, plan: next });
        setPickedId(null);
        // Relabelling keeps the coordinates, so the trip key (and this plan) stays valid.
        setPickup((p) => nameDroppedPin(p, next.origin_street));
        setDropoff((p) => nameDroppedPin(p, next.destination_street));
      })
      .catch((caught) => {
        if (live) setResult({ trip, error: caught instanceof RideError || caught instanceof Error ? caught.message : "Routing failed" });
      });
    return () => {
      live = false;
    };
  }, [trip, city, origin, destination, routing.status]);

  const selected = useMemo(() => {
    if (!plan) return null;
    return plan.routes.find((r) => r.id === (pickedId ?? plan.recommended_id)) ?? plan.routes[0];
  }, [plan, pickedId]);

  // Once riding, the map shows only the chosen route. Memoized: the ride re-renders every frame.
  const mapPlan = useMemo(
    () => (phase === "plan" ? plan : plan && selected ? { ...plan, routes: [selected] } : null),
    [phase, plan, selected],
  );

  const choosePlace = useCallback((field: Field, place: Place | null) => {
    if (field === "pickup") setPickup(place);
    else setDropoff(place);
    if (place) setActiveField(field === "pickup" ? "dropoff" : "pickup");
  }, []);

  const onMapClick = useCallback((point: LatLng) => {
    if (phase !== "plan") return;
    const field: Field = !pickup ? "pickup" : !dropoff ? "dropoff" : activeField;
    choosePlace(field, { ...point, label: DROPPED_PIN });
  }, [phase, pickup, dropoff, activeField, choosePlace]);

  function changeCity(next: string) {
    setSlug(next);
    setPickup(null);
    setDropoff(null);
    setActiveField("pickup");
    setRouting({ status: "idle", error: null });
  }

  // ---- the ride ------------------------------------------------------------------------
  const cum = useMemo(() => (selected ? cumulative(selected.path) : null), [selected]);
  const total = cum?.at(-1) ?? 0;

  useEffect(() => {
    if (phase !== "riding" || !selected || !total) return;
    const duration = RIDE_SECONDS(selected.duration_s) * 1000;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setProgress(t * total);
      if (t < 1) frame = requestAnimationFrame(tick);
      else setPhase("arrived");
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [phase, selected, total]);

  const stepIndex = useMemo(() => {
    if (!selected || !total) return 0;
    const scale = selected.distance_m / total;
    let run = 0;
    for (let i = 0; i < selected.steps.length - 1; i += 1) {
      run += selected.steps[i].distance_m;
      if (progress * scale < run) return i;
    }
    return selected.steps.length - 1;
  }, [selected, total, progress]);

  const sitesAlong = useMemo(() => {
    if (!plan || !selected || !cum) return [];
    return selected.crash_sites
      .map((index) => ({ index, site: plan.crashes[String(index)], at: distanceAlong(selected.path, cum, plan.crashes[String(index)]) }))
      .filter((s) => s.site)
      .sort((a, b) => a.at - b.at);
  }, [plan, selected, cum]);

  // Show a passing note from 150 m before a site until 250 m after it.
  const passed: PassedSite | null = sitesAlong.find((s) => progress > s.at - 150 && progress < s.at + 250) ?? null;

  function startRide() {
    setProgress(0);
    setPhase("riding");
  }

  function reset() {
    setPhase("plan");
    setProgress(0);
    setPickup(null);
    setDropoff(null);
    setActiveField("pickup");
  }

  if (!MAPS_API_KEY) {
    return (
      <main className="ride-app ride-app-empty">
        <p>Safe Journey needs a Google Maps key. Set <code>GOOGLE_MAPS_KEY</code> in <code>frontend/.env.local</code> and restart the dev server.</p>
      </main>
    );
  }

  const presets = PRESET_TRIPS[slug] ?? [];

  return (
    <main className="ride-app">
      {city && (
        <RideMap
          center={city.center}
          radiusKm={city.radius_km}
          pickup={pickup}
          dropoff={dropoff}
          plan={mapPlan}
          selectedId={selected?.id ?? null}
          onSelectRoute={setPickedId}
          onMapClick={onMapClick}
          progress={phase === "riding" ? progress : null}
          padding={mobile ? MOBILE_PADDING : PANEL_PADDING}
        />
      )}

      <aside className="ride-panel" aria-label="Plan a Safe Journey ride">
        <header className="ride-brand">
          <span className="ride-logo"><ShieldCheck size={18} aria-hidden="true" /></span>
          <span className="ride-brand-text">
            <strong>Safe Journey</strong>
            <small>Risk-aware rides</small>
          </span>
          {cities && cities.length > 0 && (
            <label className="ride-city">
              <span className="sr-only">City</span>
              <select value={slug} disabled={phase !== "plan"} onChange={(event) => changeCity(event.target.value)}>
                {cities.map((c) => <option key={c.slug} value={c.slug}>{c.name.replace(/, USA$/, "")}</option>)}
              </select>
            </label>
          )}
        </header>

        {citiesError && <p className="ride-error" role="alert">Can&apos;t reach the ride service: {citiesError}</p>}

        {phase === "plan" && city && (
          <>
            <div className="ride-trip">
              <h1>Where to?</h1>
              <div className="ride-fields">
                <PlaceField id="ride-pickup" label="Pickup" placeholder="Pickup location" kind="pickup" value={pickup}
                  center={city.center} radiusKm={city.radius_km} active={activeField === "pickup"}
                  onFocus={() => setActiveField("pickup")} onChange={(p) => choosePlace("pickup", p)} />
                <PlaceField id="ride-dropoff" label="Drop-off" placeholder="Where are you going?" kind="dropoff" value={dropoff}
                  center={city.center} radiusKm={city.radius_km} active={activeField === "dropoff"}
                  onFocus={() => setActiveField("dropoff")} onChange={(p) => choosePlace("dropoff", p)} />
                <button type="button" className="ride-swap" aria-label="Swap pickup and drop-off"
                  disabled={!pickup && !dropoff}
                  onClick={() => {
                    setPickup(dropoff);
                    setDropoff(pickup);
                  }}>
                  <ArrowDownUp size={15} />
                </button>
              </div>
              {!plan && !planning && (
                <p className="ride-hint">
                  Search, or tap the map to set your {activeField === "pickup" ? "pickup" : "drop-off"}.
                </p>
              )}
              {!pickup && !dropoff && presets.length > 0 && (
                <div className="ride-presets">
                  <span>Try a trip</span>
                  {presets.map((trip) => (
                    <button key={trip.name} type="button" onClick={() => {
                      setPickup(trip.from);
                      setDropoff(trip.to);
                    }}>{trip.name}</button>
                  ))}
                </div>
              )}
            </div>

            {routing.status === "building" && (
              <p className="ride-status">
                <LoaderCircle size={16} className="spin" aria-hidden="true" />
                Loading {city.name.split(",")[0]} streets and crash history. First visit takes up to a minute.
              </p>
            )}
            {routing.status === "error" && <p className="ride-error" role="alert">Routing unavailable: {routing.error}</p>}
            {planning && (
              <p className="ride-status">
                <LoaderCircle size={16} className="spin" aria-hidden="true" />
                Weighing routes against five years of fatal-crash records…
              </p>
            )}
            {planError && <p className="ride-error" role="alert">{planError}</p>}

            {plan && selected && (
              <RoutePanel plan={plan} selected={selected} onPick={(route) => setPickedId(route.id)} onRequest={startRide} />
            )}
          </>
        )}

        {phase === "riding" && plan && selected && dropoff && (
          <RideProgress plan={plan} route={selected} fraction={total ? progress / total : 0} stepIndex={stepIndex}
            passed={passed} dropoff={dropoff} onEnd={() => setPhase("arrived")} />
        )}

        {phase === "arrived" && plan && selected && dropoff && (
          <Arrived plan={plan} route={selected} dropoff={dropoff} onReset={reset} />
        )}

        <footer className="ride-footer">
          <Link href="/">Operator view →</Link>
        </footer>
      </aside>

      {phase !== "arrived" && plan && (
        <div className="ride-legend" aria-hidden="true">
          <span><i className="is-route" /> Your route</span>
          {phase === "plan" && plan.routes.length > 1 && <span><i className="is-alt" /> Other options</span>}
          <span><i className="is-on" /> Crash site on route</span>
          <span><i className="is-avoided" /> Crash site avoided</span>
        </div>
      )}
    </main>
  );
}
