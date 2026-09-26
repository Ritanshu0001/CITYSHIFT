import { ArrowLeft, Check, LoaderCircle, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { JOB_STEPS, JOB_STEP_LABELS, REFERENCE_LABEL } from "@/lib/constants";
import type { JobStatus } from "@/lib/types";

export function ProgressScreen({ cityName, job }: { cityName: string; job: JobStatus | null }) {
  const hasError = job?.status === "error";
  return (
    <main className="progress-page">
      <div className="progress-card">
        <div className="progress-orbit" aria-hidden="true"><span /><span /><span /></div>
        <p className="eyebrow"><span>{hasError ? "!" : "LIVE"}</span> Public data analysis</p>
        <h1>{hasError ? "Analysis stopped" : `Reading ${cityName.replaceAll("-", " ")}`}</h1>
        <p className="progress-lede">Building a comparable 8 km driving fingerprint against {REFERENCE_LABEL}.</p>

        <div className="progress-list">
          {JOB_STEPS.map((step, index) => {
            const done = job?.steps_done.includes(step) ?? false;
            const active = job?.step === step && !hasError;
            return (
              <div className={`progress-step${done ? " is-done" : ""}${active ? " is-active" : ""}`} key={step}>
                <span className="step-marker">
                  {done ? <Check size={15} /> : active ? <LoaderCircle className="spin" size={15} /> : String(index + 1).padStart(2, "0")}
                </span>
                <div><b>{JOB_STEP_LABELS[step]}</b>{active && job?.message && <small>{job.message}</small>}</div>
              </div>
            );
          })}
        </div>

        {hasError && (
          <div className="progress-error" role="alert">
            <OctagonAlert size={20} /><div><b>Couldn’t finish this city</b><p>{job?.error ?? "The analysis pipeline returned an error."}</p></div>
          </div>
        )}
        {hasError && <Link className="back-link" href="/"><ArrowLeft size={16} /> Back to search</Link>}
        {!hasError && <p className="progress-footnote">Keep this tab open · most cities finish in under two minutes</p>}
      </div>
    </main>
  );
}
