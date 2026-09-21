"use client";

/**
 * The motion the sidebar uses.
 *
 * Two rules behind the numbers below:
 *
 *   - **Short.** Navigation chrome is something people move through dozens of
 *     times an hour. 180ms reads as responsive; past ~250ms it reads as the
 *     app being slow, which is the opposite of the intent.
 *   - **Honest about height.** A list that expands has no height until it is
 *     measured, so these animate `height: auto` via the layout system rather
 *     than guessing a pixel value that breaks the moment a project is added.
 *
 * Everything here respects `prefers-reduced-motion`: for a viewer who has
 * asked for less movement, the transitions collapse to an instant state
 * change rather than being merely faster. Motion is decoration on a sidebar -
 * nobody should have to feel unwell to read their projects.
 */
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

/** The house curve: quick, with just enough ease to not feel mechanical. */
export const EASE = [0.32, 0.72, 0, 1] as const;
export const DURATION = 0.18;

/**
 * A section that opens and closes by height.
 *
 * Used for the workspace and project tree, where the content's height is not
 * knowable in advance.
 */
export function Collapse({ open, children }: {
  open: boolean; children: React.ReactNode;
}) {
  const still = useReducedMotion();
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={still ? false : { height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={still ? { height: 0, opacity: 0 } : { height: 0, opacity: 0 }}
          transition={still ? { duration: 0 }
                            : { duration: DURATION, ease: EASE }}
          // Children must not spill while the box is shorter than they are.
          style={{ overflow: "hidden" }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * A popover that lifts into place.
 *
 * Rises a few pixels rather than sliding far: the menu is anchored to the
 * thing that opened it, so a big movement would break that connection.
 */
export function Pop({ open, className = "", children }: {
  open: boolean; className?: string; children: React.ReactNode;
}) {
  const still = useReducedMotion();
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={className}
          initial={still ? false : { opacity: 0, y: 6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: still ? 0 : 4, scale: still ? 1 : 0.99 }}
          transition={still ? { duration: 0 }
                            : { duration: 0.15, ease: EASE }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * The marker that follows the active nav item.
 *
 * One element shared across every row via `layoutId`, so it travels between
 * them instead of each row fading its own bar in and out. That movement is
 * the whole point: it shows *where you came from*, which a crossfade cannot.
 */
export function ActiveMarker({ id = "sidebar-active" }: { id?: string }) {
  const still = useReducedMotion();
  return (
    <motion.span
      layoutId={still ? undefined : id}
      className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-brand"
      transition={{ duration: DURATION, ease: EASE }}
      aria-hidden
    />
  );
}

export { motion, AnimatePresence, useReducedMotion };
