/**
 * Sprint U-20 (Roadmap-Punkt 20, 2026-06-04): React-Router v6 Future-Flags.
 *
 * Bewusst in eigenes Modul ausgelagert damit Tests den Constant
 * importieren koennen ohne main.tsx's ReactDOM.createRoot()-Side-
 * Effect.
 *
 * Flags
 * -----
 * - v7_startTransition: Updates innerhalb React.startTransition wrappen.
 * - v7_relativeSplatPath: Relative Pfade unter Splat (`*`) folgen v7.
 * - v7_fetcherPersist: fetcher-Status persistiert ueber Navigation.
 * - v7_normalizeFormMethod: HTTP-Method-Strings case-insensitive.
 * - v7_partialHydration: Server-Rendering Partial-Hydration.
 * - v7_skipActionErrorRevalidation: Loader-Revalidation nach
 *   Action-Error wird übersprungen.
 */
export const ROUTER_FUTURE_FLAGS = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialHydration: true,
  v7_skipActionErrorRevalidation: true,
} as const;
