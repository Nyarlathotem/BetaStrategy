"""Reproducible AKShare ETF EOD source audit; this is not a backtest engine."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

# Support both ``python -m src.data_audit...`` and direct script execution.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data_audit.akshare_etf_quality import (
    classify_request_outcome,
    collect_anomalies,
    compare_adjustments,
    dataframe_sha256,
    json_compact,
    normalize_code,
    validate_history,
)


CHINA_TZ = ZoneInfo("Asia/Shanghai")
ANCHORS = {
    "510300.SH": "SSE",
    "159919.SZ": "SZSE",
    "513100.SH": "SSE",
    "518880.SH": "SSE",
    "515930.SH": "SSE",
}


@dataclass
class RequestRecord:
    interface: str
    canonical_code: str | None
    akshare_symbol: str | None
    start_date: str | None
    end_date: str | None
    period: str | None
    adjust_mode: str | None
    requested_at_cst: str
    completed_at_cst: str
    duration_seconds: float
    akshare_version: str
    status: str
    attempts: int
    retries: int
    row_count: int | None
    first_date: str | None
    last_date: str | None
    sha256: str | None
    cache_file: str | None
    error_type: str | None
    error_message: str | None


class AkshareClient:
    """Serial, cached AKShare client with bounded incremental retries."""

    def __init__(
        self,
        cache_dir: Path,
        interval_seconds: float = 2.0,
        max_retries: int = 3,
    ) -> None:
        import akshare as ak

        self.ak = ak
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.max_retries = max_retries
        self.last_request_monotonic: float | None = None
        self.manifest_jsonl = self.cache_dir / "request_manifest.jsonl"

    def _wait(self) -> None:
        if self.last_request_monotonic is None:
            return
        elapsed = time.monotonic() - self.last_request_monotonic
        if elapsed < self.interval_seconds:
            time.sleep(self.interval_seconds - elapsed)

    def _append_manifest(self, record: RequestRecord) -> None:
        with self.manifest_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def _request(
        self,
        interface: str,
        callback: Callable[[], pd.DataFrame],
        cache_file: Path,
        canonical_code: str | None = None,
        symbol: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = None,
        adjust: str | None = None,
        refresh: bool = False,
    ) -> tuple[pd.DataFrame | None, RequestRecord]:
        requested_at = datetime.now(CHINA_TZ)
        if cache_file.exists() and not refresh:
            frame = pd.read_csv(cache_file)
            validation = validate_history(frame) if "日期" in frame.columns else {}
            record = RequestRecord(
                interface=interface,
                canonical_code=canonical_code,
                akshare_symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period=period,
                adjust_mode=adjust,
                requested_at_cst=requested_at.isoformat(timespec="seconds"),
                completed_at_cst=datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                duration_seconds=0.0,
                akshare_version=self.ak.__version__,
                status="cache_hit",
                attempts=0,
                retries=0,
                row_count=int(len(frame)),
                first_date=validation.get("first_date"),
                last_date=validation.get("last_date"),
                sha256=dataframe_sha256(frame),
                cache_file=str(cache_file),
                error_type=None,
                error_message=None,
            )
            self._append_manifest(record)
            return frame, record

        started = time.monotonic()
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts += 1
            try:
                self._wait()
                frame = callback()
                self.last_request_monotonic = time.monotonic()
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"{interface} returned {type(frame)!r}, not DataFrame")
                frame.to_csv(cache_file, index=False, encoding="utf-8-sig")
                validation = validate_history(frame) if "日期" in frame.columns else {}
                status = classify_request_outcome(frame)
                record = RequestRecord(
                    interface=interface,
                    canonical_code=canonical_code,
                    akshare_symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    period=period,
                    adjust_mode=adjust,
                    requested_at_cst=requested_at.isoformat(timespec="seconds"),
                    completed_at_cst=datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                    duration_seconds=round(time.monotonic() - started, 6),
                    akshare_version=self.ak.__version__,
                    status=status,
                    attempts=attempts,
                    retries=attempts - 1,
                    row_count=int(len(frame)),
                    first_date=validation.get("first_date"),
                    last_date=validation.get("last_date"),
                    sha256=dataframe_sha256(frame),
                    cache_file=str(cache_file),
                    error_type=None,
                    error_message=None,
                )
                self._append_manifest(record)
                return frame, record
            except Exception as exc:  # request errors must not become empty data
                self.last_request_monotonic = time.monotonic()
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(float(attempt + 1))

        record = RequestRecord(
            interface=interface,
            canonical_code=canonical_code,
            akshare_symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
            adjust_mode=adjust,
            requested_at_cst=requested_at.isoformat(timespec="seconds"),
            completed_at_cst=datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            duration_seconds=round(time.monotonic() - started, 6),
            akshare_version=self.ak.__version__,
            status="request_failed",
            attempts=attempts,
            retries=attempts - 1,
            row_count=None,
            first_date=None,
            last_date=None,
            sha256=None,
            cache_file=None,
            error_type=type(last_error).__name__ if last_error else None,
            error_message=str(last_error)[:1000] if last_error else None,
        )
        self._append_manifest(record)
        return None, record

    def history(
        self,
        canonical_code: str,
        exchange: str,
        start_date: str,
        end_date: str,
        adjust: str,
        refresh: bool = False,
        cache_tag: str = "",
    ) -> tuple[pd.DataFrame | None, RequestRecord]:
        normalized = normalize_code(canonical_code, exchange)
        adjust_label = adjust or "raw"
        suffix = f"_{cache_tag}" if cache_tag else ""
        cache_file = self.cache_dir / (
            f"hist_{normalized.akshare_symbol}_{start_date}_{end_date}_{adjust_label}{suffix}.csv"
        )
        return self._request(
            interface="fund_etf_hist_em",
            callback=lambda: self.ak.fund_etf_hist_em(
                symbol=normalized.akshare_symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            ),
            cache_file=cache_file,
            canonical_code=normalized.canonical_code,
            symbol=normalized.akshare_symbol,
            start_date=start_date,
            end_date=end_date,
            period="daily",
            adjust=adjust,
            refresh=refresh,
        )

    def spot(self, refresh: bool = False) -> tuple[pd.DataFrame | None, RequestRecord]:
        cache_file = self.cache_dir / "fund_etf_spot_em.csv"
        return self._request(
            interface="fund_etf_spot_em",
            callback=self.ak.fund_etf_spot_em,
            cache_file=cache_file,
            refresh=refresh,
        )


def _flatten_summary(
    canonical_code: str,
    exchange: str,
    adjust: str,
    record: RequestRecord,
    validation: dict,
) -> dict:
    return {
        "canonical_code": canonical_code,
        "exchange": exchange,
        "akshare_symbol": record.akshare_symbol,
        "adjust_mode": adjust or "raw",
        "request_status": record.status,
        "attempts": record.attempts,
        "retries": record.retries,
        "duration_seconds": record.duration_seconds,
        "row_count": record.row_count,
        "first_date": record.first_date,
        "last_date": record.last_date,
        "sha256": record.sha256,
        "duplicate_dates": validation.get("duplicate_dates"),
        "invalid_dates": validation.get("invalid_dates"),
        "weekend_rows": validation.get("weekend_rows"),
        "sorted_ascending": validation.get("sorted_ascending"),
        "nonpositive_price_rows": validation.get("nonpositive_price_rows"),
        "invalid_ohlc_rows": validation.get("invalid_ohlc_rows"),
        "negative_volume_rows": validation.get("negative_成交量_rows"),
        "negative_amount_rows": validation.get("negative_成交额_rows"),
        "zero_volume_with_price_rows": validation.get("zero_volume_with_price_rows"),
        "zero_amount_with_volume_rows": validation.get("zero_amount_with_volume_rows"),
        "pct_check_eligible_rows": validation.get("pct_check_eligible_rows"),
        "pct_inconsistent_rows_0_02pp": validation.get("pct_inconsistent_rows_0_02pp"),
        "extreme_rows_1000x_median": validation.get("extreme_rows_1000x_median"),
        "nonnull_counts": json_compact(validation.get("nonnull_counts", {})),
        "nonnull_rates": json_compact(validation.get("nonnull_rates", {})),
        "unit_inference": json_compact(validation.get("unit_inference", {})),
        "error_type": record.error_type,
        "error_message": record.error_message,
    }


def run_histories(
    client: AkshareClient,
    universe: pd.DataFrame,
    start_date: str,
    end_date: str,
    output_dir: Path,
    all_adjustments: bool,
    max_symbols: int | None,
    resume: bool,
    stop_on_failure: bool = False,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    if max_symbols is not None:
        universe = universe.head(max_symbols)
    summaries: list[dict] = []
    adjustment_summaries: list[dict] = []
    anomalies: list[pd.DataFrame] = []
    failed = False
    for row in universe.itertuples(index=False):
        canonical = str(row.canonical_code)
        exchange = str(row.exchange)
        is_anchor = canonical in ANCHORS
        adjust_test = str(getattr(row, "adjust_test", "")).lower() in {
            "1",
            "true",
            "yes",
        }
        modes = ("", "qfq", "hfq") if all_adjustments or is_anchor or adjust_test else ("",)
        frames: dict[str, pd.DataFrame] = {}
        for adjust in modes:
            frame, record = client.history(
                canonical,
                exchange,
                start_date,
                end_date,
                adjust,
                refresh=not resume,
            )
            validation = validate_history(frame) if frame is not None else {}
            summaries.append(
                _flatten_summary(canonical, exchange, adjust, record, validation)
            )
            if frame is None:
                failed = True
                if stop_on_failure:
                    break
                continue
            frames[adjust or "raw"] = frame
            issue_rows = collect_anomalies(frame)
            if not issue_rows.empty:
                issue_rows.insert(0, "adjust_mode", adjust or "raw")
                issue_rows.insert(0, "canonical_code", canonical)
                anomalies.append(issue_rows.head(50))
        if failed and stop_on_failure:
            break
        if {"raw", "qfq", "hfq"}.issubset(frames):
            comparison = compare_adjustments(
                frames["raw"], frames["qfq"], frames["hfq"]
            )
            comparison.update({"canonical_code": canonical, "exchange": exchange})
            adjustment_summaries.append(comparison)
    pd.DataFrame(summaries).to_csv(
        output_dir / "hist_request_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(adjustment_summaries).to_csv(
        output_dir / "adjustment_summary.csv", index=False, encoding="utf-8-sig"
    )
    anomaly_frame = (
        pd.concat(anomalies, ignore_index=True)
        if anomalies
        else pd.DataFrame(columns=["canonical_code", "adjust_mode", "日期", "anomaly"])
    )
    anomaly_frame.to_csv(
        output_dir / "anomaly_samples.csv", index=False, encoding="utf-8-sig"
    )
    return 2 if failed else 0


def run_smoke(client: AkshareClient, args: argparse.Namespace) -> int:
    universe = pd.DataFrame(
        [{"canonical_code": "510300.SH", "exchange": "SSE", "adjust_test": True}]
    )
    status = run_histories(
        client,
        universe,
        args.start_date,
        args.as_of,
        args.output_dir,
        all_adjustments=True,
        max_symbols=1,
        resume=args.resume,
        stop_on_failure=True,
    )
    if status != 0:
        pd.DataFrame(
            [
                {
                    "canonical_code": "510300.SH",
                    "window_start": args.start_date,
                    "window_end": args.as_of,
                    "first_status": "not_run_after_smoke_failure",
                    "second_status": "not_run_after_smoke_failure",
                    "identical": False,
                }
            ]
        ).to_csv(
            args.output_dir / "repeatability_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        return status
    first, first_record = client.history(
        "510300.SH", "SSE", args.start_date, args.as_of, "", refresh=True, cache_tag="repeat1"
    )
    second, second_record = client.history(
        "510300.SH", "SSE", args.start_date, args.as_of, "", refresh=True, cache_tag="repeat2"
    )
    stable = {
        "canonical_code": "510300.SH",
        "window_start": args.start_date,
        "window_end": args.as_of,
        "first_status": first_record.status,
        "second_status": second_record.status,
        "first_rows": first_record.row_count,
        "second_rows": second_record.row_count,
        "first_sha256": first_record.sha256,
        "second_sha256": second_record.sha256,
        "identical": bool(
            first is not None
            and second is not None
            and first_record.sha256 == second_record.sha256
        ),
    }
    pd.DataFrame([stable]).to_csv(
        args.output_dir / "repeatability_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    if first is None or second is None:
        return 2
    return status


def run_current_universe(client: AkshareClient, args: argparse.Namespace) -> int:
    if args.universe_csv is None:
        raise ValueError("--universe-csv is required for current-universe mode")
    oracle = pd.read_csv(args.universe_csv, dtype=str)
    required = {"canonical_code", "exchange"}
    if not required.issubset(oracle.columns):
        raise ValueError(f"universe CSV requires columns: {sorted(required)}")
    spot, record = client.spot(refresh=not args.resume)
    if spot is None:
        return 2
    if "代码" not in spot.columns:
        raise ValueError(f"spot result lacks 代码; columns={list(spot.columns)}")
    spot_codes = set(spot["代码"].astype(str).str.zfill(6))
    oracle = oracle.copy()
    oracle["akshare_symbol"] = [
        normalize_code(code, exchange).akshare_symbol
        for code, exchange in zip(oracle["canonical_code"], oracle["exchange"])
    ]
    symbol_counts = oracle.groupby("akshare_symbol")["canonical_code"].nunique()
    ambiguous_symbols = set(symbol_counts[symbol_counts > 1].index)
    oracle_symbols = set(oracle["akshare_symbol"])
    intersection = oracle_symbols & spot_codes
    summary = {
        "as_of": args.as_of,
        "wdzx_etf_count": int(oracle["canonical_code"].nunique()),
        "wdzx_six_digit_count": len(oracle_symbols),
        "akshare_spot_row_count": int(len(spot)),
        "akshare_spot_code_count": len(spot_codes),
        "intersection_six_digit_count": len(intersection),
        "coverage_rate": len(intersection) / len(oracle_symbols) if oracle_symbols else None,
        "wdzx_only_count": len(oracle_symbols - spot_codes),
        "akshare_only_count": len(spot_codes - oracle_symbols),
        "ambiguous_six_digit_count": len(ambiguous_symbols),
        "spot_status": record.status,
        "spot_sha256": record.sha256,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_csv(
        args.output_dir / "current_universe_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    oracle[oracle["akshare_symbol"].isin(oracle_symbols - spot_codes)].to_csv(
        args.output_dir / "wdzx_only_codes.csv", index=False, encoding="utf-8-sig"
    )
    spot[spot["代码"].astype(str).str.zfill(6).isin(spot_codes - oracle_symbols)].to_csv(
        args.output_dir / "akshare_only_codes.csv", index=False, encoding="utf-8-sig"
    )
    oracle[oracle["akshare_symbol"].isin(ambiguous_symbols)].to_csv(
        args.output_dir / "ambiguous_codes.csv", index=False, encoding="utf-8-sig"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("smoke", "sample", "current-universe", "full"), required=True
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/akshare_etf_audit/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path(".cache/akshare_etf_audit/output"))
    parser.add_argument("--universe-csv", type=Path)
    parser.add_argument("--as-of", required=True, help="latest fully closed date, YYYYMMDD")
    parser.add_argument("--start-date", default="20000101")
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--all-adjustments", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = AkshareClient(args.cache_dir, args.interval_seconds, args.max_retries)
    if args.mode == "smoke":
        return run_smoke(client, args)
    if args.mode == "current-universe":
        return run_current_universe(client, args)
    if args.universe_csv is None:
        raise ValueError("--universe-csv is required for sample/full mode")
    universe = pd.read_csv(args.universe_csv, dtype=str)
    if args.mode == "full" and not args.resume:
        raise ValueError("full mode requires --resume to make recovery explicit")
    return run_histories(
        client,
        universe,
        args.start_date,
        args.as_of,
        args.output_dir,
        all_adjustments=args.all_adjustments,
        max_symbols=args.max_symbols,
        resume=args.resume,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        traceback.print_exc()
        print(f"AUDIT_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
