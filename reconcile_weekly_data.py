import os
import json
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
from sync_keep_data import safe_float, main as run_sync

def get_gspread_client():
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS")
    sa = json.loads(sa_key)
    return gspread.authorize(Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]))

def reconcile_past_7_days():
    run_sync()
    gc = get_gspread_client()
    sheet_id = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID")
    sh = gc.open_by_key(sheet_id.strip())
    ws_train = sh.worksheet("训练记录")
    ws_ana = sh.worksheet("每日分析")

    all_train = ws_train.get_all_values()[1:]
    ana_all = ws_ana.get_all_values()

    tz_cn = timezone(timedelta(hours=8))
    sync_ts = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M:%S")

    for idx, row in enumerate(ana_all[1:], start=2):
        if not row or len(row) < 7:
            continue
        ymd = row[0]
        try:
            target_dt = datetime.strptime(ymd, "%Y-%m-%d")
        except Exception:
            continue

        d7_start = (target_dt - timedelta(days=6)).strftime("%Y-%m-%d")
        d60_start = (target_dt - timedelta(days=59)).strftime("%Y-%m-%d")

        load_7d, load_60d = 0.0, 0.0
        for tr in all_train:
            if len(tr) >= 11:
                rd = tr[0]
                km = safe_float(tr[3])
                load_val = safe_float(tr[10]) if tr[10] else (km * 10 if km > 0 else 5.0)

                if d60_start <= rd <= ymd:
                    load_60d += load_val
                if d7_start <= rd <= ymd:
                    load_7d += load_val

        real_acwr = round((load_7d * 60.0) / (load_60d * 7.0), 2) if load_60d > 0 else 0.0
        if abs(safe_float(row[6]) - real_acwr) > 0.05:
            ws_ana.update_cell(idx, 7, real_acwr)
            ws_ana.update_cell(idx, 19, "周日自动对账校准")
            ws_ana.update_cell(idx, 20, sync_ts)

    print("🎉 周日对账与全运动 ACWR 检查校准完成！")

if __name__ == "__main__":
    reconcile_past_7_days()
