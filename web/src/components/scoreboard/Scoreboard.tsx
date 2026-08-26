import type { Playback } from "../../lib/playback";
import "./scoreboard.css";

interface ScoreboardProps {
  playback: Playback;
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

/** What the run actually showed.
 *
 *  Both engines see the same corrupted evidence and neither sees ground truth,
 *  so every number here is a measurement rather than a demonstration. */
export function Scoreboard({ playback }: ScoreboardProps) {
  const board = playback.scoreboard;
  const [theirs, ours] = board.engines;

  return (
    <div className="scoreboard">
      <header>
        <p className="label">Measured result &middot; {playback.name}</p>
        <p className="at-risk">
          <span className="numeric">{board.residents_at_risk.toLocaleString()}</span>
          residents in genuinely endangered tracts
        </p>
      </header>

      <div className="verdicts">
        <article>
          <p className="who">Conventional dashboard</p>
          <p className="big bad numeric">{percent(theirs.false_reassurance_rate)}</p>
          <p className="what">of endangered tracts called safe</p>
          <p className="residents numeric">
            {theirs.residents_falsely_reassured.toLocaleString()} residents
          </p>
        </article>

        <article className="is-ours">
          <p className="who">NullSignal</p>
          <p className="big good numeric">{percent(ours.false_reassurance_rate)}</p>
          <p className="what">of endangered tracts called safe</p>
          <p className="residents numeric">
            {ours.residents_falsely_reassured.toLocaleString()} residents
          </p>
        </article>
      </div>

      <table>
        <thead>
          <tr>
            <th></th>
            <th>False alarm</th>
            <th>Unresolved</th>
            <th>Warning</th>
          </tr>
        </thead>
        <tbody>
          {[theirs, ours].map((engine) => (
            <tr key={engine.engine} className={engine.engine === "nullsignal" ? "is-ours" : undefined}>
              <td>{engine.engine === "nullsignal" ? "NullSignal" : "Conventional"}</td>
              <td className="numeric">{percent(engine.false_alarm_rate)}</td>
              <td className="numeric">{percent(engine.unresolved_rate)}</td>
              <td className="numeric">
                {engine.warning_hours === null ? "none" : `${engine.warning_hours}h`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="gloss">
        <strong>False alarm</strong> claims danger when nothing is wrong.
        <strong> Unresolved</strong> declines to confirm safety &mdash; it asserts
        nothing about danger, so it is not folded into the same number.
      </p>

      <div className="concentration">
        <p className="label">Who is standing in the blind spots</p>
        <p>
          <span className="big bad numeric">
            {percent(board.blind_spot_concentration)}
          </span>
          of the residents the conventional dashboard kept calling safe are in the
          most vulnerable quintile &mdash; against{" "}
          <span className="numeric">{percent(board.citywide_top_quintile_share)}</span>{" "}
          citywide. <strong>{board.concentration_ratio.toFixed(2)}&times;</strong>.
        </p>
      </div>

      {board.baseline_alarms_indiscriminately && (
        <p className="caveat">
          The conventional dashboard scores well on false reassurance here only by
          claiming danger {percent(theirs.false_alarm_rate)} of the time when nothing
          is wrong. A stopped clock.
        </p>
      )}

      {board.nullsignal_is_beaten && (
        <p className="caveat is-loss">
          <strong>NullSignal is beaten in this scenario.</strong> Reported rather than
          hidden &mdash; a scoreboard that only shows wins is a slide, not a
          measurement.
        </p>
      )}
    </div>
  );
}
