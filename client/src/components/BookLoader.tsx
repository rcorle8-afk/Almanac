const PAGES = [0, 1, 2, 3, 4];

// index.html repeats this markup so the book shows before the JavaScript loads.
export function BookLoader({ label }: { label: string }) {
  return (
    <div className="loader" role="status">
      <div className="loader-book" aria-hidden="true">
        <div className="loader-cover" />
        <div className="loader-side loader-left" />
        <div className="loader-side loader-right" />
        {PAGES.map((page) => (
          <div key={page} className={`loader-page loader-page-${page}`} />
        ))}
      </div>
      <p className="loader-label">{label}</p>
    </div>
  );
}
