// Line icons in the same hand as the navigation: 24px grid, 2px round strokes.
// Filled shapes only where a symbol has to read as solid (play, pause).
const base = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const IconPlay = () => (
  <svg {...base}><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z" fill="currentColor" stroke="none" /></svg>
);
export const IconPause = () => (
  <svg {...base}><rect x="6" y="5" width="4.2" height="14" rx="1.4" fill="currentColor" stroke="none" /><rect x="13.8" y="5" width="4.2" height="14" rx="1.4" fill="currentColor" stroke="none" /></svg>
);
export const IconPrev = () => (
  <svg {...base}><line x1="6" y1="5" x2="6" y2="19" /><path d="M18 6.2v11.6a.8.8 0 0 1-1.25.66l-8-5.8a.8.8 0 0 1 0-1.32l8-5.8A.8.8 0 0 1 18 6.2Z" fill="currentColor" stroke="none" /></svg>
);
export const IconNext = () => (
  <svg {...base}><line x1="18" y1="5" x2="18" y2="19" /><path d="M6 6.2v11.6a.8.8 0 0 0 1.25.66l8-5.8a.8.8 0 0 0 0-1.32l-8-5.8A.8.8 0 0 0 6 6.2Z" fill="currentColor" stroke="none" /></svg>
);
export const IconClose = () => (
  <svg {...base}><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
);
export const IconShuffle = () => (
  <svg {...base}><path d="M3 7h3.5c2 0 3.4 1 4.5 2.7l2 3.6c1.1 1.7 2.5 2.7 4.5 2.7H21" /><path d="M3 17h3.5c2 0 3.4-1 4.5-2.7" /><path d="M13 8.7C14.1 7.4 15.3 7 17 7h4" /><polyline points="18.5 4.5 21 7 18.5 9.5" /><polyline points="18.5 12.5 21 15 18.5 17.5" /></svg>
);
export const IconQueue = () => (
  <svg {...base}><line x1="4" y1="7" x2="15" y2="7" /><line x1="4" y1="12" x2="15" y2="12" /><line x1="4" y1="17" x2="10" y2="17" /><line x1="18" y1="14" x2="18" y2="20" /><line x1="15" y1="17" x2="21" y2="17" /></svg>
);
export const IconStop = () => (
  <svg {...base}><rect x="6" y="6" width="12" height="12" rx="2.4" fill="currentColor" stroke="none" /></svg>
);
export const IconDevice = () => (
  <svg {...base}><path d="M5 12a7 7 0 0 1 14 0" /><path d="M8.2 12a3.8 3.8 0 0 1 7.6 0" /><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" /><line x1="12" y1="13.5" x2="12" y2="19" /></svg>
);
export const IconFolder = () => (
  <svg {...base}><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.2l2 2.2h8.8A1.5 1.5 0 0 1 21 9.7v7.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5Z" /></svg>
);
export const IconUp = () => (
  <svg {...base}><polyline points="9 14 4 9 9 4" /><path d="M20 20v-7a4 4 0 0 0-4-4H4" /></svg>
);
export const IconBack = () => (
  <svg {...base}><polyline points="14 6 8 12 14 18" /></svg>
);
