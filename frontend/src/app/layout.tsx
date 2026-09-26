import type { Metadata } from "next";
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

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
