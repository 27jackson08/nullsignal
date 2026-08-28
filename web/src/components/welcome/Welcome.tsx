import { useEffect, useRef } from "react";

import "./welcome.css";

const STORAGE_KEY = "nullsignal.welcomed";

/** The scenario that makes the argument fastest. */
export const HEADLINE_SCENARIO = "heatwave-transit-silent-failure";

export function hasBeenWelcomed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // Private browsing and blocked storage both throw here. Showing the card
    // twice is a far smaller failure than refusing to render the app.
    return false;
  }
}

function remember() {
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* nothing to do: the card simply appears again next visit */
  }
}

interface Props {
  residents: number | null;
  unknownCount: number | null;
  onDismiss: () => void;
  onLoadScenario: (name: string) => void;
}

export function Welcome({ residents, unknownCount, onDismiss, onLoadScenario }: Props) {
  const primary = useRef<HTMLButtonElement>(null);

  function close() {
    remember();
    onDismiss();
  }

  useEffect(() => {
    primary.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="welcome-scrim" onClick={close}>
      <section
        className="welcome"
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
        onClick={(event) => event.stopPropagation()}
      >
        <p className="welcome-eyebrow">NullSignal</p>
        <h2 id="welcome-title">Don&rsquo;t confuse silence with safety</h2>

        <p>
          Every census tract in New York, on real public data. Most monitoring
          systems record <em>no data</em> as <em>no problem</em>. This one
          refuses to.
        </p>

        <dl className="welcome-key">
          <div>
            <dt><span className="swatch swatch-low" aria-hidden="true" /> Green</dt>
            <dd>Checked, and the evidence supports calling it fine.</dd>
          </div>
          <div>
            <dt><span className="swatch swatch-unknown" aria-hidden="true" /> Hatched</dt>
            <dd>We can&rsquo;t tell &mdash; and that is never shown as safe.</dd>
          </div>
        </dl>

        {residents !== null && unknownCount !== null && (
          <p className="welcome-stat">
            <strong>{residents.toLocaleString()}</strong> New Yorkers, across{" "}
            {unknownCount} tracts, are being called safe right now on evidence
            nobody actually has.
          </p>
        )}

        <div className="welcome-actions">
          <button
            ref={primary}
            type="button"
            className="welcome-primary"
            onClick={() => {
              remember();
              onLoadScenario(HEADLINE_SCENARIO);
              onDismiss();
            }}
          >
            Watch a dashboard get it wrong
          </button>
          <button type="button" className="welcome-secondary" onClick={close}>
            Explore the map
          </button>
        </div>
      </section>
    </div>
  );
}
