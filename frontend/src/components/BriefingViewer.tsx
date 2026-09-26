"use client";

import { Download, FileJson, FileText, LoaderCircle, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { briefingUrl } from "@/lib/api";

type BriefingViewerProps = {
  cityName: string;
  slug: string;
  onDownload: (format: "md" | "json") => void;
};

export function BriefingViewer({ cityName, slug, onDownload }: BriefingViewerProps) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!open) return;

    const controller = new AbortController();

    void fetch(briefingUrl(slug, "md"), { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Briefing unavailable (${response.status})`);
        return response.text();
      })
      .then(setContent)
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "The briefing could not be loaded.");
      });

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      controller.abort();
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [close, open, slug]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="briefing-view-button"
        onClick={() => {
          setContent("");
          setError("");
          setOpen(true);
        }}
        aria-haspopup="dialog"
      >
        <FileText size={17} />
        View briefing
      </button>

      {open && (
        <div
          className="briefing-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close();
          }}
        >
          <section
            className="briefing-viewer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="briefing-viewer-title"
          >
            <header className="briefing-viewer-header">
              <div>
                <span>City readiness briefing</span>
                <h2 id="briefing-viewer-title">{cityName}</h2>
              </div>
              <div className="briefing-viewer-actions">
                <button type="button" onClick={() => onDownload("md")}>
                  <Download size={15} /> <FileText size={14} /> Markdown
                </button>
                <button type="button" onClick={() => onDownload("json")}>
                  <Download size={15} /> <FileJson size={14} /> JSON
                </button>
                <button ref={closeRef} type="button" className="briefing-close" onClick={close} aria-label="Close briefing">
                  <X size={19} />
                </button>
              </div>
            </header>

            <div className="briefing-viewer-body">
              {!content && !error && (
                <div className="briefing-loading" role="status">
                  <LoaderCircle size={24} />
                  Building the briefing…
                </div>
              )}
              {error && <p className="briefing-error" role="alert">{error}</p>}
              {content && <article className="briefing-markdown"><ReactMarkdown>{content}</ReactMarkdown></article>}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
