"use client";

import { ChevronDown, ShieldCheck, TriangleAlert } from "lucide-react";
import { REFERENCE_LABEL } from "@/lib/constants";
import { areaSummary, formatDistance, formatExtra, formatMinutes, plural, streetsSummary, type RideRoute, type RoutePlan } from "@/lib/ride";

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
          const tone = route.label === "Fastest" ? "is-fastest" : route.label === "Balanced" ? "is-balanced" : "is-safest";
          return (
            <li key={route.id}>
              <button type="button" className={`ride-route ${tone}${route.id === selected.id ? " is-selected" : ""}`}
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
                  <span>{plural(route.intersections, "intersection")} · {plural(route.crash_sites.length, "risk site")}</span>
                </span>
                <span className="ride-route-foot">
                  {route.id === fastest.id ? "Baseline route risk" : `${Math.round(route.risk_reduction_pct)}% lower route risk`}
                  <small> · {Math.round(route.area_mix.red)}% in strong-shift areas</small>
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
              <span>Fastest, but it {areaSummary(selected)}.</span>
            </p>
            <p className="ride-why-line">
              <span className="ride-why-dot" aria-hidden="true" />
              <span>
                {selected.crash_sites.length
                  ? <>Passes {plural(selected.crash_sites.length, "risk site")}: {streetsSummary(plan, selected.crash_sites).join(" · ")}.</>
                  : "Passes no recorded risk sites."}
              </span>
            </p>
            {recommended.id !== fastest.id && (
              <button type="button" className="ride-why-nudge" onClick={() => onPick(recommended)}>
                {formatExtra(recommended.extra_s)} reduces route risk by {Math.round(recommended.risk_reduction_pct)}% →
              </button>
            )}
          </>
        ) : (
          <>
            {selected.avoided_sites.length > 0 && (
              <p className="ride-why-line is-good">
                <ShieldCheck size={16} aria-hidden="true" />
                <span>
                  Steers around {plural(selected.avoided_sites.length, "risk site")} on the fastest route:{" "}
                  {streetsSummary(plan, selected.avoided_sites).join(" · ")}.
                </span>
              </p>
            )}
            {single ? (
              <p className="ride-why-line">
                <span className="ride-why-dot" aria-hidden="true" />
                <span>No slower route is meaningfully safer. This one {areaSummary(selected)}.</span>
              </p>
            ) : (
              <AreaChange route={selected} fastest={fastest} />
            )}
            <p className="ride-why-line">
              <span className="ride-why-dot" aria-hidden="true" />
              <span>
                {selected.crash_sites.length
                  ? <>{single ? "Passes" : "Still passes"} {plural(selected.crash_sites.length, "risk site")}: {streetsSummary(plan, selected.crash_sites).join(" · ")}.</>
                  : "Passes no recorded risk sites."}
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
        Route risk: every intersection crossed and every 100 m driven, weighted by how unlike {REFERENCE_LABEL} the area is
        (its shift score; strong-shift areas count most). Risk sites weigh more: an NHTSA FARS fatal-crash record from 2020–2024
        on the route counts like several strong-shift intersections, less the farther the route passes from it. ETAs are free-flow estimates with
        a {plan.method.intersection_delay_s}-second allowance per intersection.
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

/** How the route compares with the fastest one on the hex layer: a gain, or the intersections it trades for fewer risk sites. */
function AreaChange({ route, fastest }: { route: RideRoute; fastest: RideRoute }) {
  const fewer = fastest.intersections - route.intersections;
  const red = Math.round(route.area_mix.red);
  const fastestRed = Math.round(fastest.area_mix.red);
  let text: string;
  if (fewer > 0 && fastestRed - red >= 3) {
    text = `Crosses ${plural(fewer, "fewer intersection")} than the fastest route, with ${red}% of the way in strong-shift areas instead of ${fastestRed}%.`;
  } else if (fewer > 0) {
    text = `Crosses ${plural(fewer, "fewer intersection")} than the fastest route (${route.intersections} in all).`;
  } else if (fastestRed - red >= 3) {
    text = `Spends less of the trip in strong-shift areas: ${red}% of the way instead of ${fastestRed}%.`;
  } else if (fewer <= -3) {
    return (
      <p className="ride-why-line">
        <span className="ride-why-dot" aria-hidden="true" />
        <span>Trade-off: crosses {plural(-fewer, "more intersection")} than the fastest route ({route.intersections} in all).</span>
      </p>
    );
  } else {
    return null;
  }
  return (
    <p className="ride-why-line is-good">
      <ShieldCheck size={16} aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}
