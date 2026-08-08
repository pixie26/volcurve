"""Normalized store: standardized observations as Parquet (derivable from raw)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from app.domain.observations import StandardObservation
from app.domain.surfaces import StandardSurfaceObservation


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


def surface_observations_to_frame(
    observations: list[StandardSurfaceObservation],
) -> pd.DataFrame:
    """Flatten maturity-major surface points while preserving their coordinates."""
    records = []
    for observation in observations:
        snapshot_flags = "|".join(flag.value for flag in observation.quality_flags)
        for point in observation.points:
            records.append(
                {
                    "date": observation.date,
                    "instrument_code": observation.instrument_code,
                    "maturity_rule": observation.maturity_rule,
                    "strike_rule": observation.strike_rule,
                    "volatility_convention": observation.volatility_convention,
                    "spot": observation.spot,
                    "maturity": point.maturity,
                    "strike": point.strike,
                    "maturity_index": point.maturity_index,
                    "strike_index": point.strike_index,
                    "forward": observation.forward_curve[point.maturity_index],
                    "discount_factor": (
                        observation.discount_factors[point.maturity_index]
                        if point.maturity_index < len(observation.discount_factors)
                        else None
                    ),
                    "raw_implied_vol": point.raw_implied_vol,
                    "implied_vol": point.implied_vol,
                    "quality_flags": "|".join(flag.value for flag in point.quality_flags),
                    "snapshot_quality_flags": snapshot_flags,
                    "source_time": observation.source_time,
                    "source_timezone": observation.source_timezone,
                    "source_timestamp": observation.source_timestamp,
                }
            )
    frame = pd.DataFrame(records)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


class NormalizedStore:
    def __init__(self, normalized_dir: Path):
        self._dir = normalized_dir

    def save_implied_vol(self, request_hash: str, observations: list[StandardObservation]) -> Path:
        out_dir = self._dir / "implied_vol"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_hash}.parquet"
        self._atomic_parquet(observations_to_frame(observations), path)
        return path

    def save_implied_vol_surface(
        self, request_hash: str, observations: list[StandardSurfaceObservation]
    ) -> Path:
        out_dir = self._dir / "implied_vol_surface"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{request_hash}.parquet"
        self._atomic_parquet(surface_observations_to_frame(observations), path)
        return path

    def save_instruments(self, instruments: list[dict]) -> Path:
        out_dir = self._dir / "instruments"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "instruments.parquet"
        self._atomic_parquet(pd.DataFrame(instruments), path)
        return path

    def delete_request(self, request_hash: str) -> None:
        for directory in ("implied_vol", "implied_vol_surface"):
            path = self._dir / directory / f"{request_hash}.parquet"
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
        os.close(fd)
        try:
            frame.to_parquet(temp_name, index=False)
            # Windows requires a writable descriptor for FlushFileBuffers,
            # which is what os.fsync delegates to here.
            with open(temp_name, "rb+") as fh:
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
