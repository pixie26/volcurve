"""Normalized store: standardized observations as Parquet (derivable from raw)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.domain.observations import StandardObservation


def observations_to_frame(observations: list[StandardObservation]) -> pd.DataFrame:
    records = []
    for obs in observations:
        rec = obs.model_dump()
        rec["quality_flags"] = "|".join(f.value for f in obs.quality_flags)
        records.append(rec)
    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


class NormalizedStore:
    def __init__(self, normalized_dir: Path):
        self._dir = normalized_dir

    def save_implied_vol(self, request_hash: str, observations: list[StandardObservation]) -> Path:
        out_dir = self._dir / "implied_vol"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_hash}.parquet"
        observations_to_frame(observations).to_parquet(path, index=False)
        return path

    def save_instruments(self, instruments: list[dict]) -> Path:
        out_dir = self._dir / "instruments"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "instruments.parquet"
        pd.DataFrame(instruments).to_parquet(path, index=False)
        return path
