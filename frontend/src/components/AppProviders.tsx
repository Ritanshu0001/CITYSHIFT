"use client";

import { APIProvider } from "@vis.gl/react-google-maps";
import type { ReactNode } from "react";
import { MAPS_API_KEY } from "@/lib/constants";

export function AppProviders({ children }: { children: ReactNode }) {
  if (!MAPS_API_KEY) return children;

  return (
    <APIProvider apiKey={MAPS_API_KEY} libraries={["places"]} language="en">
      {children}
    </APIProvider>
  );
}
