"""Watch what the renderers are playing and turn it into play counts.

The Apple export is a frozen snapshot: it covers a third of the library and
stops at the day it was downloaded. Counting plays here is the only way the
other 21k tracks ever earn a score.

VUIO reports a renderer's `current_url` (e.g. http://host/media/34910.m4a)
and nothing about progress, so a play is recognised by watching the same URL
persist across polls. Everything in this module is pure state handling; the
polling and database writes live in app.py.
"""

import re

MEDIA_URL = re.compile(r"/media/(\d+)")

# Seconds a track must stay on a renderer to count as played rather than
# skipped. The usual streaming-service convention.
MIN_PLAY_SECONDS = 30


def media_id_from_url(url) -> int:
    """The VUIO media id inside a stream URL, or None if it is not one.

    Anything the renderer is playing from elsewhere (radio, another server)
    simply has no id and is ignored.
    """
    if not isinstance(url, str):
        return None
    match = MEDIA_URL.search(url)
    return int(match.group(1)) if match else None


def current_media_id(status: dict):
    """The media id playing right now, across VUIO's renderer list."""
    if not isinstance(status, dict):
        return None
    for renderer in status.get("renderers") or []:
        if not isinstance(renderer, dict):
            continue
        # "stopped"/"paused" still report the last URL, so a paused track
        # would otherwise keep accruing time.
        if renderer.get("state") in ("stopped", "paused", "idle"):
            continue
        media_id = media_id_from_url(renderer.get("current_url"))
        if media_id is not None:
            return media_id
    return None


class PlayTracker:
    """Turns a sequence of observations into finished listening events.

    Call observe() once per poll. It returns a finished event as
    (media_id, seconds, completed) when the renderer moves on, else None.
    """

    def __init__(self, min_play_seconds: float = MIN_PLAY_SECONDS):
        self.min_play_seconds = min_play_seconds
        self.media_id = None
        self.first_seen = 0.0
        self.last_seen = 0.0

    def _finish(self):
        if self.media_id is None:
            return None
        # Measured span, not track length: polling can only ever see how long
        # the URL stayed put, which understates by up to one interval.
        seconds = self.last_seen - self.first_seen
        event = (self.media_id, seconds, seconds >= self.min_play_seconds)
        self.media_id = None
        return event

    def observe(self, media_id, now: float):
        if media_id == self.media_id:
            if media_id is not None:
                self.last_seen = now
            return None

        finished = self._finish()
        if media_id is not None:
            self.media_id = media_id
            self.first_seen = now
            self.last_seen = now
        return finished

    def flush(self):
        """Close out whatever is playing, e.g. when shutting down."""
        return self._finish()
