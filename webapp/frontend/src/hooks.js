import { useEffect, useRef } from "react";

// ponytail: passing delayMs=null pauses polling (no interval created/cleared).
export function useInterval(callback, delayMs) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (delayMs === null) return;
    const id = setInterval(() => callbackRef.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}
