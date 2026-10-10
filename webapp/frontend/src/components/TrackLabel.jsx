// Artist, album and title instead of the raw path. The backend parses these
// out of the path (no tags are stored), so `display` can be absent on older
// responses - fall back to the filename rather than showing nothing.
export default function TrackLabel({ track }) {
  const d = track.display;
  if (!d) {
    return <span className="track-title">{track.path.split("/").pop()}</span>;
  }
  return (
    <>
      <span className="track-title">{d.title}</span>
      <span className="track-meta">
        {d.artist}
        {d.album ? ` · ${d.album}` : ""}
      </span>
    </>
  );
}
