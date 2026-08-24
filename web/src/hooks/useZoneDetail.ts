import { useEffect, useState } from "react";

import { fetchZoneDetail, type ZoneDetail } from "../lib/api";

export function useZoneDetail(geoid: string | null) {
  const [detail, setDetail] = useState<ZoneDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!geoid) {
      setDetail(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);

    fetchZoneDetail(geoid)
      .then((next) => { if (!cancelled) setDetail(next); })
      .catch((err: Error) => { if (!cancelled) setError(err.message); });

    return () => { cancelled = true; };
  }, [geoid]);

  return { detail, error };
}
