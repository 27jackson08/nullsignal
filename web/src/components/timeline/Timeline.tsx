import type { Playback, TickView } from "../../lib/playback";
import "./timeline.css";

interface TimelineProps {
  playback: Playback;
  view: TickView | null;
  tick: number;
  isPlaying: boolean;
  onSeek: (tick: number) => void;
  onTogglePlay: () => void;
  onExit: () => void;
}

export function Timeline({
  playback, view, tick, isPlaying, onSeek, onTogglePlay, onExit,
}: TimelineProps) {
  const lastTick = playback.ticks.length - 1;
  const currentEvent = playback.events.find((e) => e.hour === view?.hour);

  return (
    <section className="timeline" aria-label="Scenario playback">
      <header>
        <div className="scenario-id">
          <p className="label">Scenario</p>
          <h2>{playback.name}</h2>
        </div>
        <div className="transport">
          <button type="button" onClick={onTogglePlay}
                  aria-label={isPlaying ? "Pause" : "Play"}>
            {isPlaying ? "Pause" : "Play"}
          </button>
          <button type="button" className="ghost" onClick={onExit}>
            Back to live
          </button>
        </div>
      </header>

      <div className="track">
        <input
          type="range" min={0} max={lastTick} step={1} value={tick}
          onChange={(event) => onSeek(Number(event.target.value))}
          aria-label={`Hour ${view?.hour ?? 0} of ${playback.ticks[lastTick].hour}`}
        />
        <div className="marks" aria-hidden="true">
          {playback.events.map((event) => (
            <span
              key={`${event.hour}-${event.note}`}
              className={event.inject ? "mark is-fault" : "mark"}
              style={{ left: `${(event.hour / playback.ticks[lastTick].hour) * 100}%` }}
              title={event.note}
            />
          ))}
        </div>
      </div>

      <div className="readout">
        <span className="hour numeric">t + {view?.hour ?? 0}h</span>
        {view?.faults.length ? (
          <span className="faults">
            {view.faults.map((fault) => (
              <span key={fault} className="fault-chip">{fault}</span>
            ))}
          </span>
        ) : (
          <span className="faults quiet">no active faults</span>
        )}
        {currentEvent && <span className="event-note">{currentEvent.note}</span>}
      </div>
    </section>
  );
}
