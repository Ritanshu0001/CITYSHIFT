import { ArrowLeft, Check, Clock3, LoaderCircle, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { JOB_STEPS, JOB_STEP_LABELS, REFERENCE_LABEL } from "@/lib/constants";
import type { JobStatus } from "@/lib/types";

export function ProgressScreen({ cityName, job }: { cityName: string; job: JobStatus | null }) {
  const hasError = job?.status === "error";
  const isCancelled = job?.status === "cancelled";
  const isQueued = job?.status === "queued";
  return (
    <main className="progress-page">
      <div className="progress-card">
        <p className="progress-label">Public data analysis</p>
        <h1>{hasError ? "Analysis stopped" : isCancelled ? "Analysis replaced" : isQueued ? `${cityName.replaceAll("-", " ")} is queued` : `Reading ${cityName.replaceAll("-", " ")}`}</h1>
        <p className="progress-lede">
          {isCancelled
            ? "A newer city search took priority, so this city was removed from the queue."
            : isQueued
              ? "The analysis will start automatically as soon as the current city finishes."
              : `Building a comparable 8 km driving fingerprint against ${REFERENCE_LABEL}.`}
        </p>

        {isQueued && (
          <div className="progress-queued" role="status">
            <Clock3 size={18} />
            <div><b>Waiting in the analysis queue</b><p>{job.message ?? "Another city is being processed."}</p></div>
          </div>
        )}

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
        {isCancelled && (
          <div className="progress-cancelled" role="status">
            <ArrowLeft size={18} /><div><b>Newer search is running</b><p>{job.message}</p></div>
          </div>
        )}
        {(hasError || isCancelled) && <Link className="back-link" href="/"><ArrowLeft size={16} /> Back to search</Link>}
        {!hasError && !isCancelled && <p className="progress-footnote">{isQueued ? "This tab will update automatically" : "Keep this tab open · processing live public data"}</p>}
      </div>
    </main>
  );
}
