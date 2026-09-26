import type { Metadata } from "next";
import Script from "next/script";
import "@fontsource-variable/manrope";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";
import { AppProviders } from "@/components/AppProviders";
import { REFERENCE_LABEL } from "@/lib/constants";

export const metadata: Metadata = {
  title: "CityShift — Find the scenario worth testing",
  description: `Compare any city's driving environment with ${REFERENCE_LABEL} using public data.`,
};

// Dev only. Some browser extensions (Urban VPN Proxy, for one) stamp bis_* attributes on every element
// before React hydrates, which trips the hydration-mismatch overlay. Next runs this right before hydrating;
// the observer catches late stamps and stops once the page has loaded.
const STRIP_EXTENSION_ATTRS = `(() => {
  const isExt = (name) => name.startsWith("bis_");
  const clean = (el) => { for (const { name } of [...el.attributes]) if (isExt(name)) el.removeAttribute(name); };
  document.querySelectorAll("*").forEach(clean);
  const observer = new MutationObserver((records) => {
    for (const r of records) if (r.attributeName && isExt(r.attributeName)) r.target.removeAttribute(r.attributeName);
  });
  observer.observe(document.documentElement, { attributes: true, subtree: true });
  const stop = () => setTimeout(() => observer.disconnect(), 5000);
  if (document.readyState === "complete") stop(); else addEventListener("load", stop);
})();`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body suppressHydrationWarning>
        <AppProviders>{children}</AppProviders>
        {process.env.NODE_ENV === "development" && (
          <Script id="strip-extension-attrs" strategy="beforeInteractive">{STRIP_EXTENSION_ATTRS}</Script>
        )}
      </body>
    </html>
  );
}
