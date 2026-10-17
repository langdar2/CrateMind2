import { useEffect, useState } from "react";

// How long a wait has to last before the indicator shows up. The manual tab
// re-previews on every slider move and usually answers within a blink; a bar
// flashing on and off under the slider would be worse than none.
const SHOW_AFTER_MS = 500;

// Shown while something slow runs. The backend reports no progress, so this
// makes no claim about how far along it is: an animation that says "working",
// the real elapsed time, and a hint naming what takes the time.
export default function Busy({ active, hint }) {
  const [visible, setVisible] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!active) {
      setVisible(false);
      setSeconds(0);
      return;
    }
    const started = Date.now();
    const reveal = setTimeout(() => setVisible(true), SHOW_AFTER_MS);
    const tick = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500);
    return () => {
      clearTimeout(reveal);
      clearInterval(tick);
    };
  }, [active]);

  if (!active || !visible) return null;

  return (
    <div className="busy" role="status" aria-live="polite">
      <div className="busy-bars" aria-hidden="true">
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <span key={i} style={{ animationDelay: `${i * 0.12}s` }} />
        ))}
      </div>
      <div className="busy-text">
        <span className="busy-hint">{hint || "Arbeite..."}</span>
        <span className="busy-time">{seconds} s</span>
      </div>
    </div>
  );
}
