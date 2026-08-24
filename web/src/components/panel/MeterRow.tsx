import "./meter-row.css";

interface MeterRowProps {
  label: string;
  /** null means not measured -- rendered as a void, never as a full bar. */
  value: number | null;
  note?: string;
}

export function MeterRow({ label, value, note }: MeterRowProps) {
  const isMeasured = value !== null;

  return (
    <div className={isMeasured ? "meter-row" : "meter-row is-unmeasured"}>
      <span className="meter-label">{label}</span>
      <span className="meter-track" role="img"
            aria-label={isMeasured ? `${label}: ${value.toFixed(2)} of 1` : `${label}: not measured`}>
        {isMeasured
          ? <span className="meter-fill" style={{ width: `${Math.round(value * 100)}%` }} />
          : <span className="meter-void" />}
      </span>
      <span className="meter-value numeric">
        {isMeasured ? value.toFixed(2) : "—"}
      </span>
      {note && <span className="meter-note">{note}</span>}
    </div>
  );
}
