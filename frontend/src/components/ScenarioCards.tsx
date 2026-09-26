import { Building2, ChevronRight, MapPinned } from "lucide-react";
import type { Scenario } from "@/lib/types";

interface ScenarioCardsProps {
  scenarios: Scenario[];
  activeScenario: string | null;
  onHighlight: (scenario: Scenario | null) => void;
}

// A scenario's areas show on the map only while its card is hovered or focused. Leaving a card
// falls back to whichever card still holds the other one; with neither, the map clears.
const scenarioOf = (scenarios: Scenario[], el: Element | null | undefined) =>
  scenarios.find((s) => s.id === (el as HTMLElement | null)?.dataset?.scenarioId) ?? null;

export function ScenarioCards({ scenarios, activeScenario, onHighlight }: ScenarioCardsProps) {
  return (
    <div className="scenario-list">
      <div className="scenario-intro">Prioritized from the size of each shift and the number of affected areas.</div>
      {scenarios.map((scenario, index) => (
        <article
          key={scenario.id}
          data-scenario-id={scenario.id}
          className={`scenario-card${activeScenario === scenario.id ? " is-active" : ""}`}
          tabIndex={0}
          onMouseEnter={() => onHighlight(scenario)}
          onMouseLeave={() => onHighlight(scenarioOf(scenarios, document.activeElement))}
          onFocus={() => onHighlight(scenario)}
          onBlur={(event) => {
            if (scenarioOf(scenarios, event.relatedTarget)) return; // the next card's onFocus takes over
            onHighlight(scenarioOf(scenarios, event.currentTarget.parentElement?.querySelector(".scenario-card:hover")));
          }}
          onClick={() => onHighlight(scenario)}
        >
          <div className="scenario-rank"><span>{String(index + 1).padStart(2, "0")}</span><small>Priority {scenario.priority.toFixed(1)}</small></div>
          <h3>{scenario.title}</h3>
          <p>{scenario.description}</p>
          <div className="scenario-scope">
            {scenario.scope === "city" ? <Building2 size={14} /> : <MapPinned size={14} />}
            {scenario.scope === "city" ? "City-wide" : `${scenario.hex_ids.length} mapped ${scenario.hex_ids.length === 1 ? "area" : "areas"}`}
          </div>
          <div className="trigger-list">
            <small>Triggered by</small>
            {scenario.triggered_by.map((trigger) => <span key={trigger}>{trigger}</span>)}
          </div>
          <ChevronRight className="scenario-arrow" size={20} />
        </article>
      ))}
    </div>
  );
}
