# CrateMind2 Frontend Redesign — Design

## Goal

Replace the current unstyled, plain-HTML frontend with a cohesive, polished visual design ("Midnight Glass"), a sidebar-based layout, and live-updating data (analysis progress, renderer playback status) without manual refresh clicks.

## Visual Design System ("Midnight Glass")

- **Background:** dark purple-to-navy gradient, `#161227` → `#0c0f22`, applied once at the app root.
- **Cards/tiles:** translucent glass panels — `rgba(255,255,255,0.06)` background, `backdrop-filter: blur(6px)`, `1px solid rgba(255,255,255,0.1)` border, soft drop shadow, ~14-16px border radius.
- **Accent:** gradient `#7c5cff → #5ce1ff`, used for progress bars, active nav item, primary buttons, links.
- **Typography:** Inter, loaded via a single `@import url(...)` in `index.css` (Google Fonts) — no new npm dependency. `system-ui` remains the fallback stack.
- **Tokens:** defined as CSS custom properties on `:root` in `index.css` (`--bg-grad-start`, `--bg-grad-end`, `--glass-bg`, `--glass-border`, `--accent-from`, `--accent-to`, `--text-primary`, `--text-secondary`, `--danger`) so every component references the same palette instead of repeating literals.
- **Icons:** 3 hand-written inline SVGs (dashboard/grid icon, playlist/list icon, renderer/speaker icon) embedded directly in the sidebar component. No icon library dependency.

This direction and the layout below were validated visually with the user via the brainstorming visual companion (Midnight Glass over "Studio Dark" and "Minimal Mono"; Sidebar + live status bar over plain Top-Nav and plain Sidebar).

## Layout

- **Sidebar** (replaces the current `.top-nav` top bar): fixed-width (~70px) vertical bar on the left. Contains: brand mark (small gradient square logo), then the 3 nav icons (Dashboard, Playlists, Renderer) as `NavLink`s, active item highlighted with the accent gradient.
- **Main content area:** to the right of the sidebar, keeps the existing `.tile-grid` concept for arranging cards, just restyled per the tokens above.
- **Persistent live status bar:** a bar docked to the bottom of the viewport, spanning the width of the main content area (not covering the sidebar). It is conditionally rendered:
  - Shown when a renderer is actively casting (playback status shows a currently-playing track), and/or the analysis pipeline is not yet at 100% (`status_counts` has trackable non-terminal progress — i.e. `pending` count > 0).
  - Hidden entirely otherwise (no empty/idle state to build or show).
  - Shows, left side: currently playing track name + target renderer name (when casting). Right side: analysis progress percentage (when pipeline is still running).
  - Lives in `App.jsx` (above `<Routes>`, below/alongside the sidebar) so it persists across page navigation, sourcing its data from the same polled state described below (lifted into `App.jsx` via a small shared polling hook call, passed down or re-fetched independently — see Data Flow).

## Data Flow / Realtime Updates

- **New hook:** `src/hooks.js` exports `useInterval(callback, delayMs)` — a standard `setInterval`-in-`useEffect` hook (the well-known pattern: stores the latest callback in a ref, re-subscribes only when `delayMs` changes). This is the one new abstraction, justified because it's needed in at least 2 independent places (Dashboard stats, Renderer playback status) plus the status bar.
- **Dashboard (`Dashboard.jsx`):** in addition to the existing one-shot `getStats()` on mount, poll `getStats()` every 3000ms via `useInterval` **only while** `status_counts.pending > 0` (or pending is unknown/undefined, to be safe on first load) — stops polling once the pipeline has nothing left to process, to avoid pointless requests once analysis is done.
- **Renderers (`Renderers.jsx`):** for a renderer whose status has already been fetched at least once (i.e. present in `status` state), poll `getPlaybackStatus(rendererId)` every 3000ms via `useInterval` instead of requiring a manual "Status abfragen" click each time. The manual button remains for the first fetch / manual refresh.
- **Status bar (`App.jsx` / new `StatusBar.jsx`):** polls `getStats()` every 3000ms (same pending-based stop condition as Dashboard) for the analysis-progress side. For the "currently casting" side, it polls `getRenderers()` every 3000ms, then calls `getPlaybackStatus(r.id)` for each returned renderer and shows the first one whose status response indicates an active/playing track. This is the simplest approach (no shared cross-page state needed) and is acceptable given the expected renderer count on a home network (a handful of devices).
- No WebSocket/SSE server, no new backend endpoints — everything rides on existing REST endpoints (`/api/stats`, `/api/playback-status`, `/api/renderers`) via polling.

## Pages

- **Dashboard:** existing tiles restyled with the glass look; the "Analyse-Fortschritt" tile gets an actual gradient progress bar (percentage = `ok / (ok + failed + pending)`) instead of just a status/count list (the list of counts stays below the bar). Failed-tracks search/pagination UI unchanged functionally, just restyled inputs/list items.
- **Playlists:** same functionality (preset/seed mode, preview, reorder, create, cast), restyled: seed search results rendered as small glass cards instead of bare `<li>`/`<button>`, preview list items as glass rows with the existing reorder/remove buttons restyled.
- **Renderers:** each renderer becomes a glass card; playback status (once available) rendered as a small readable block (track name, play/pause indicator) instead of a raw `<pre>{JSON.stringify(...)}</pre>` dump — still showing all fields VuIO returns, just formatted, not literal JSON.

## Error Handling

Unchanged from today: existing `error`/`.error` display pattern (red text via `--danger`) stays as the mechanism for surfacing fetch failures on every page. Polling failures follow the same pattern as existing one-shot fetch failures (caught, message shown) but must not spam the UI on every 3s retry — if a poll fails, keep showing the last known good data and only surface the error state if there was no previous successful fetch yet.

## Testing

No new automated frontend tests are added for pure styling changes (nothing there to assert on). The one new piece of logic, `useInterval`, is simple enough (standard, widely-used pattern) that it's verified manually: after implementation, open the browser Network tab and confirm `/api/stats` and `/api/playback-status` requests recur on their interval and stop/behave as specified (e.g. stats polling stops once `pending` reaches 0). No new test framework is introduced for this.

## Out of Scope

- No backend/API changes.
- No WebSocket or Server-Sent-Events push mechanism.
- No new UI component library (no Tailwind, MUI, etc.) — plain CSS + React continues.
- No redesign of the underlying data model or endpoints.
