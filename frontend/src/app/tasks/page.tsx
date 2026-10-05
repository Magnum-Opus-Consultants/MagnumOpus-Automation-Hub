"use client";

import { Suspense } from "react";
import { TrackerBoard } from "@/components/tracker-board";

/**
 * `useSearchParams` opts a route out of static prerendering unless it sits
 * inside a Suspense boundary - `next build` fails on it even though `next dev`
 * does not. The boundary keeps /tasks prerenderable and shows the same loading
 * state the page uses for its own data.
 */
export default function TasksPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-sm text-ink-2">Loading work items…</div>
      }
    >
      <TrackerBoard />
    </Suspense>
  );
}
