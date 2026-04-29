"""Descarga y acumulación de exportes Interactive Brokers Flex Query."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import pandas as pd

from options_dashboard.config import IMPORT_SUMMARY_FILE, LATEST_DATA_FILE, MASTER_DATA_FILE

IB_SEND_REQUEST_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
IB_GET_STATEMENT_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"

REQUIRED_IB_COLUMNS = {
    "TradeID",
    "UnderlyingSymbol",
    "Description",
    "TradeDate",
    "Buy/Sell",
    "Quantity",
    "NetCash",
    "AssetClass",
}


def _fetch_text(url: str, params: dict[str, str]) -> str:
    query = urlencode(params)
    with urlopen(f"{url}?{query}") as response:
        return response.read().decode("utf-8", errors="replace")


def _looks_like_xml(text: str) -> bool:
    return text.lstrip().startswith("<?xml") or text.lstrip().startswith("<Flex")


def _extract_reference_code(send_request_xml: str) -> str:
    root = ET.fromstring(send_request_xml)
    status = (root.findtext(".//Status") or "").strip().lower()
    if status and status != "success":
        raise ValueError(root.findtext(".//ErrorMessage") or "IB SendRequest failed")
    ref_code = (root.findtext(".//ReferenceCode") or "").strip()
    if not ref_code:
        raise ValueError("No se encontró ReferenceCode en la respuesta de IB.")
    return ref_code


def download_latest_ib_csv(token: str, query_id: str, latest_file: Path = LATEST_DATA_FILE) -> tuple[Path, str]:
    """Descarga CSV de IB Flex Query y lo guarda como Consulta_latest.csv."""
    send_request_response = _fetch_text(
        IB_SEND_REQUEST_URL,
        {"t": token, "q": query_id, "v": "3", "f": "csv"},
    )
    reference_code = _extract_reference_code(send_request_response)
    csv_text = ""
    last_message = ""
    for _ in range(12):
        response_text = _fetch_text(
            IB_GET_STATEMENT_URL,
            {"t": token, "q": reference_code, "v": "3"},
        )
        if not _looks_like_xml(response_text):
            csv_text = response_text
            break

        root = ET.fromstring(response_text)
        status = (root.findtext(".//Status") or "").strip().lower()
        last_message = (root.findtext(".//ErrorMessage") or root.findtext(".//ErrorCode") or "").strip()

        # Si devuelve una URL con el statement, descargar desde ahí.
        statement_url = (root.findtext(".//Url") or "").strip()
        if statement_url:
            csv_text = _fetch_text(statement_url, {})
            break

        if status == "success" and root.find(".//FlexStatement") is not None:
            csv_text = response_text
            break

        if "generation" in last_message.lower() or "wait" in last_message.lower() or status in {"inprogress", ""}:
            time.sleep(2)
            continue

        raise ValueError(last_message or "GetStatement falló al generar el reporte.")

    if not csv_text:
        raise ValueError(last_message or "IB no devolvió CSV. Reintenta en unos segundos.")

    latest_file.parent.mkdir(parents=True, exist_ok=True)
    latest_file.write_text(csv_text, encoding="utf-8")
    return latest_file, reference_code


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def _clean_trade_id(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    values = values.str.replace(r"\.0$", "", regex=True)
    values = values.str.replace(r"\s+", "", regex=True)
    return values


def merge_latest_into_master(
    latest_file: Path = LATEST_DATA_FILE,
    master_file: Path = MASTER_DATA_FILE,
    summary_file: Path = IMPORT_SUMMARY_FILE,
) -> dict:
    """Acumula nuevas filas (por TradeID) desde latest hacia master."""
    latest_df = _load_csv(latest_file)
    master_df = _load_csv(master_file)

    warnings: list[str] = []
    missing_cols = sorted(REQUIRED_IB_COLUMNS.difference(set(latest_df.columns)))
    if missing_cols:
        warnings.append(f"missing required columns: {', '.join(missing_cols)}")

    latest_rows_downloaded = int(len(latest_df))
    latest_df["TradeID"] = _clean_trade_id(latest_df.get("TradeID", pd.Series(dtype=str)))
    latest_with_tradeid = latest_df[latest_df["TradeID"] != ""].copy()
    dropped_without_tradeid = latest_rows_downloaded - len(latest_with_tradeid)

    if "AssetClass" in latest_with_tradeid.columns:
        unsupported_asset_rows = int((latest_with_tradeid["AssetClass"].fillna("").str.upper() != "OPT").sum())
        if unsupported_asset_rows:
            warnings.append(f"unsupported AssetClass rows: {unsupported_asset_rows}")
    else:
        unsupported_asset_rows = 0

    master_rows_before = int(len(master_df))
    if not master_df.empty:
        master_df["TradeID"] = _clean_trade_id(master_df.get("TradeID", pd.Series(dtype=str)))
    master_trade_ids = set(master_df.get("TradeID", pd.Series(dtype=str)).dropna().astype(str))

    existing_mask = latest_with_tradeid["TradeID"].isin(master_trade_ids)
    already_existing = int(existing_mask.sum())
    new_rows = latest_with_tradeid[~existing_mask].copy()
    new_rows_added = int(len(new_rows))

    updated_master = pd.concat([master_df, new_rows], ignore_index=True) if not master_df.empty else new_rows.copy()
    updated_master["TradeID"] = _clean_trade_id(updated_master.get("TradeID", pd.Series(dtype=str)))
    updated_master = updated_master[updated_master["TradeID"] != ""].copy()
    updated_master.drop_duplicates(subset=["TradeID"], keep="first", inplace=True)
    updated_master.to_csv(master_file, index=False)

    unique_trade_ids = int(updated_master["TradeID"].nunique()) if not updated_master.empty else 0
    duplicated_trade_ids = int(len(updated_master) - unique_trade_ids)

    invalid_dates = 0
    if "TradeDate" in latest_with_tradeid.columns:
        parsed_dates = pd.to_datetime(latest_with_tradeid["TradeDate"], errors="coerce")
        invalid_dates = int(parsed_dates.isna().sum())
        if invalid_dates:
            warnings.append(f"invalid dates: {invalid_dates}")

    if dropped_without_tradeid:
        warnings.append(f"empty TradeID dropped rows: {dropped_without_tradeid}")
    if duplicated_trade_ids:
        warnings.append(f"duplicated TradeID in master: {duplicated_trade_ids}")

    import_summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "success": True,
        "source_used": "ib_flex_query",
        "file_loaded": str(master_file),
        "rows_downloaded_latest": latest_rows_downloaded,
        "rows_with_tradeid": int(len(latest_with_tradeid)),
        "rows_without_tradeid_dropped": int(dropped_without_tradeid),
        "rows_already_existing_master": already_existing,
        "new_rows_added_to_master": new_rows_added,
        "total_rows_master": int(len(updated_master)),
        "unique_tradeid_count": unique_trade_ids,
        "duplicated_tradeid_count": duplicated_trade_ids,
        "master_rows_before": master_rows_before,
        "warnings": warnings,
        "missing_required_columns": missing_cols,
        "invalid_dates_count": invalid_dates,
        "unsupported_assetclass_rows": unsupported_asset_rows,
        "new_trades_added": new_rows[
            [
                c
                for c in ["TradeID", "UnderlyingSymbol", "Description", "TradeDate", "Buy/Sell", "Quantity", "NetCash", "AssetClass"]
                if c in new_rows.columns
            ]
        ].head(200).to_dict(orient="records"),
    }

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(import_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return import_summary


def merge_uploaded_csv_into_master(
    uploaded_df: pd.DataFrame,
    master_file: Path = MASTER_DATA_FILE,
    summary_file: Path = IMPORT_SUMMARY_FILE,
) -> dict:
    """Acumula nuevas filas (por TradeID) desde un CSV subido manualmente hacia master."""
    master_df = _load_csv(master_file)
    import_df = uploaded_df.copy()

    warnings: list[str] = []
    missing_cols = sorted(REQUIRED_IB_COLUMNS.difference(set(import_df.columns)))
    if missing_cols:
        warnings.append(f"missing required columns: {', '.join(missing_cols)}")

    uploaded_rows = int(len(import_df))
    import_df["TradeID"] = _clean_trade_id(import_df.get("TradeID", pd.Series(dtype=str)))
    with_tradeid = import_df[import_df["TradeID"] != ""].copy()
    dropped_without_tradeid = uploaded_rows - len(with_tradeid)

    master_rows_before = int(len(master_df))
    if not master_df.empty:
        master_df["TradeID"] = _clean_trade_id(master_df.get("TradeID", pd.Series(dtype=str)))
    master_trade_ids = set(master_df.get("TradeID", pd.Series(dtype=str)).dropna().astype(str))

    existing_mask = with_tradeid["TradeID"].isin(master_trade_ids)
    already_existing = int(existing_mask.sum())
    new_rows = with_tradeid[~existing_mask].copy()
    new_rows_added = int(len(new_rows))

    updated_master = pd.concat([master_df, new_rows], ignore_index=True) if not master_df.empty else new_rows.copy()
    updated_master["TradeID"] = _clean_trade_id(updated_master.get("TradeID", pd.Series(dtype=str)))
    updated_master = updated_master[updated_master["TradeID"] != ""].copy()
    updated_master.drop_duplicates(subset=["TradeID"], keep="first", inplace=True)
    updated_master.to_csv(master_file, index=False)

    unique_trade_ids = int(updated_master["TradeID"].nunique()) if not updated_master.empty else 0
    duplicated_trade_ids = int(len(updated_master) - unique_trade_ids)

    if dropped_without_tradeid:
        warnings.append(f"empty TradeID dropped rows: {dropped_without_tradeid}")
    if duplicated_trade_ids:
        warnings.append(f"duplicated TradeID in master: {duplicated_trade_ids}")

    import_summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "success": True,
        "source_used": "manual_csv_upload",
        "file_loaded": str(master_file),
        "rows_uploaded": uploaded_rows,
        "rows_with_tradeid": int(len(with_tradeid)),
        "rows_without_tradeid_dropped": int(dropped_without_tradeid),
        "rows_already_existing_master": already_existing,
        "new_rows_added_to_master": new_rows_added,
        "total_rows_master": int(len(updated_master)),
        "unique_tradeid_count": unique_trade_ids,
        "duplicated_tradeid_count": duplicated_trade_ids,
        "master_rows_before": master_rows_before,
        "warnings": warnings,
        "missing_required_columns": missing_cols,
        "new_trades_added": new_rows[
            [
                c
                for c in ["TradeID", "UnderlyingSymbol", "Description", "TradeDate", "Buy/Sell", "AssetClass", "Quantity", "NetCash"]
                if c in new_rows.columns
            ]
        ].head(200).to_dict(orient="records"),
    }

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(import_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return import_summary


def load_import_summary(summary_file: Path = IMPORT_SUMMARY_FILE) -> dict | None:
    if not summary_file.exists():
        return None
    return json.loads(summary_file.read_text(encoding="utf-8"))
