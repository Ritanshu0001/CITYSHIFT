"use client";

import { CircleCheck, Navigation, ShieldCheck, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { describeRisk, formatDistance, formatExtra, formatMinutes, plural, streetsSummary, type CrashSite, type Place, type RideRoute, type RoutePlan } from "@/lib/ride";

export interface PassedSite {
  index: number;
  site: CrashSite;
}

interface RideProgressProps {
  plan: RoutePlan;
  route: RideRoute;
  fraction: number;
  stepIndex: number;
  passed: PassedSite | null;
  dropoff: Place;
  onEnd: () => void;
}

export function RideProgress({ plan, route, fraction, stepIndex, passed, dropoff, onEnd }: RideProgressProps) {
  const step = route.steps[stepIndex];
  const next = route.steps[stepIndex + 1];
  return (
    <section className="ride-live" aria-live="polite">
      <p className="ride-kicker"><span className="ride-live-pulse" aria-hidden="true" /> On your {route.label}</p>
      <div className="ride-live-eta">
        <strong>{formatMinutes(route.duration_s * (1 - fraction))}</strong>
        <span>to {dropoff.label}</span>
      </div>
      <div className="ride-live-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction * 100)}
        aria-label="Trip progress">
        <i style={{ width: `${fraction * 100}%` }} />
      </div>

      <div className="ride-live-step">
        <Navigation size={18} aria-hidden="true" />
        <div>
          <strong>{step?.instruction}</strong>
          {next && <small>Then: {next.instruction}{next.distance_m > 0 ? ` · ${formatDistance(next.distance_m)}` : ""}</small>}
        </div>
      </div>

      {passed ? (
        <p className="ride-live-note is-warn" key={passed.index}>
          Entering a recorded risk area{passed.site.street ? ` on ${passed.site.street}` : ""} · {describeRisk(passed.site)}
        </p>
      ) : route.avoided_sites.length > 0 ? (
        <p className="ride-live-note is-good">
          <ShieldCheck size={15} aria-hidden="true" />
          Steering around {plural(route.avoided_sites.length, "risk site")}: {streetsSummary(plan, route.avoided_sites, 2).join(" · ")}
        </p>
      ) : null}

      <button type="button" className="ride-secondary" onClick={onEnd}>Skip to arrival</button>
    </section>
  );
}

const TRADES_KEY = "safe-journey:trades";

interface Trade {
  extra_s: number;
  reduction_pct: number;
  worth_it: boolean;
}

function readTrades(): Trade[] {
  try {
    return JSON.parse(window.localStorage.getItem(TRADES_KEY) ?? "[]") as Trade[];
  } catch {
    return [];
  }
}

interface ArrivedProps {
  plan: RoutePlan;
  route: RideRoute;
  dropoff: Place;
  onReset: () => void;
}

export function Arrived({ plan, route, dropoff, onReset }: ArrivedProps) {
  const [vote, setVote] = useState<boolean | null>(null);
  const [history, setHistory] = useState<Trade[]>([]);
  const isFastest = route.id === plan.fastest_id;

  function record(worthIt: boolean) {
    const trades = [...readTrades(), { extra_s: route.extra_s, reduction_pct: route.exposure_reduction_pct, worth_it: worthIt }];
    window.localStorage.setItem(TRADES_KEY, JSON.stringify(trades.slice(-50)));
    setHistory(trades);
    setVote(worthIt);
  }

  const accepted = history.filter((t) => t.worth_it && t.extra_s >= 30).map((t) => t.extra_s);

  return (
    <section className="ride-arrived">
      <CircleCheck size={34} className="ride-arrived-icon" aria-hidden="true" />
      <h2>You&apos;ve arrived</h2>
      <p className="ride-arrived-to">{dropoff.label}{dropoff.detail ? ` · ${dropoff.detail}` : ""}</p>

      <dl className="ride-stats">
        <div><dt>Ride</dt><dd>{formatMinutes(route.duration_s)}</dd></div>
        <div><dt>Vs fastest</dt><dd>{isFastest ? "—" : formatExtra(route.extra_s)}</dd></div>
        <div><dt>Route risk</dt><dd>{isFastest ? "Baseline" : `−${Math.round(route.exposure_reduction_pct)}%`}</dd></div>
        <div><dt>Risk sites avoided</dt><dd>{route.avoided_sites.length}</dd></div>
      </dl>

      {!isFastest && route.avoided_sites.length > 0 && (
        <p className="ride-arrived-note">
          Your ride skipped {streetsSummary(plan, route.avoided_sites).join(" · ")}, where the fastest route passes
          recorded risk areas from 2020 to 2024.
        </p>
      )}

      {!isFastest && (
        <div className="ride-feedback">
          {vote === null ? (
            <>
              <p>Was {formatExtra(route.extra_s).toLowerCase()} worth {Math.round(route.exposure_reduction_pct)}% lower route risk?</p>
              <div>
                <button type="button" onClick={() => record(true)}><ThumbsUp size={15} aria-hidden="true" /> Worth it</button>
                <button type="button" onClick={() => record(false)}><ThumbsDown size={15} aria-hidden="true" /> Too slow</button>
              </div>
            </>
          ) : (
            <p>
              Thanks. {accepted.length
                ? `Across your rides you've accepted up to ${formatExtra(Math.max(...accepted)).toLowerCase()} for a safer route.`
                : "We'll suggest tighter trades next time."}
            </p>
          )}
        </div>
      )}

      <button type="button" className="ride-request" onClick={onReset}>
        <span>Plan another ride</span>
      </button>
    </section>
  );
}
