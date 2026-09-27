"use client";

import { ChevronDown, ShieldCheck, TriangleAlert } from "lucide-react";
import { formatDistance, formatExtra, formatMinutes, plural, streetsSummary, type RideRoute, type RoutePlan } from "@/lib/ride";

interface RoutePanelProps {
  plan: RoutePlan;
  selected: RideRoute;
  onPick: (route: RideRoute) => void;
  onRequest: () => void;
}

export function RoutePanel({ plan, selected, onPick, onRequest }: RoutePanelProps) {
  const fastest = plan.routes[0];
  const recommended = plan.routes.find((r) => r.id === plan.recommended_id) ?? fastest;
  const single = plan.routes.length === 1;

  return (
    <div className="ride-options">
      <ul className="ride-routes" aria-label="Route options">
        {plan.routes.map((route) => {
          const relative = Math.max(0, 100 - route.exposure_reduction_pct);
          return (
            <li key={route.id}>
              <button type="button" className={`ride-route${route.id === selected.id ? " is-selected" : ""}`}
                aria-pressed={route.id === selected.id} onClick={() => onPick(route)}>
                <span className="ride-route-top">
                  <span className="ride-route-name">
                    {route.label}
                    {route.id === plan.recommended_id && !single && <em>Recommended</em>}
                  </span>
                  <span className="ride-route-time">{formatMinutes(route.duration_s)}</span>
                </span>
                <span className="ride-route-meta">
                  <span>{route.id === fastest.id ? "Quickest arrival" : formatExtra(route.extra_s)} · {formatDistance(route.distance_m)}</span>
                  <span>{route.crash_sites.length ? `Passes ${plural(route.crash_sites.length, "crash site")}` : "No crash sites passed"}</span>
                </span>
                <span className="ride-exposure" aria-hidden="true">
                  <i style={{ width: `${Math.max(3, relative)}%`, ["--level" as string]: relative / 100 }} />
                </span>
                <span className="ride-route-foot">
                  {route.id === fastest.id ? "Baseline crash exposure" : `${Math.round(route.exposure_reduction_pct)}% less crash exposure`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <section className="ride-why" aria-label="Why this route">
        {selected.id === fastest.id && !single ? (
          <>
            <p className="ride-why-line is-warn">
              <TriangleAlert size={16} aria-hidden="true" />
              <span>
                Fastest, but it passes {plural(selected.crash_sites.length, "fatal-crash site")}
                {selected.crash_sites.length > 0 && <>: {streetsSummary(plan, selected.crash_sites).join(" · ")}</>}.
              </span>
            </p>
            {recommended.id !== fastest.id && (
              <button type="button" className="ride-why-nudge" onClick={() => onPick(recommended)}>
                {formatExtra(recommended.extra_s)} cuts crash exposure by {Math.round(recommended.exposure_reduction_pct)}% →
              </button>
            )}
          </>
        ) : (
          <>
            {selected.avoided_sites.length > 0 && (
              <p className="ride-why-line is-good">
                <ShieldCheck size={16} aria-hidden="true" />
                <span>
                  Steers around {plural(selected.avoided_sites.length, "fatal-crash site")} on the fastest route:{" "}
                  {streetsSummary(plan, selected.avoided_sites).join(" · ")}.
                </span>
              </p>
            )}
            <p className="ride-why-line">
              <span className="ride-why-dot" aria-hidden="true" />
              <span>
                {selected.crash_sites.length
                  ? <>Still passes {plural(selected.crash_sites.length, "site")}: {streetsSummary(plan, selected.crash_sites).join(" · ")}.</>
                  : "Passes no recorded fatal-crash sites."}
              </span>
            </p>
          </>
        )}
      </section>

      <details className="ride-directions">
        <summary>
          <span>Directions · {plural(selected.steps.length - 1, "step")}</span>
          <ChevronDown size={16} aria-hidden="true" />
        </summary>
        <ol>
          {selected.steps.map((step, i) => (
            <li key={i}>
              <span>{step.instruction}</span>
              {step.distance_m > 0 && <small>{formatDistance(step.distance_m)}</small>}
            </li>
          ))}
        </ol>
      </details>

      <p className="ride-method">
        Crash exposure: {plan.method.source}, weighted by how closely the route passes each one. ETAs are
        free-flow estimates with a {plan.method.intersection_delay_s}-second allowance per intersection.
      </p>

      <div className="ride-request-dock">
        <button type="button" className="ride-request" onClick={onRequest}>
          <span>Request Waymo · {selected.label}</span>
          <small>Arrive in about {formatMinutes(selected.duration_s)}</small>
        </button>
      </div>
    </div>
  );
}
