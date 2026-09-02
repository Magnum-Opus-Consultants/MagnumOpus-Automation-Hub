"use client";

import { useEffect, useState } from "react";
import { type Me } from "@/components/Sidebar";
import { AppShell, PageHead, EmptyState } from "@/components/ui";

/**
 * Placeholder. Deliberately has no content yet — it exists so Reporting has a
 * home in the navigation while it is being designed.
 */
export default function ReportingPage() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setMe)
      .catch(() => (window.location.href = "/login"));
  }, []);

  return (
    <AppShell active="Reporting" me={me}>
      <PageHead title="Reporting" />
      <EmptyState
        icon="analysis"
        title="Still under development"
        hint="This section is being built. Nothing to show here yet."
      />
    </AppShell>
  );
}
