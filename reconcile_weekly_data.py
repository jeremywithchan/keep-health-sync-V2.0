from datetime import datetime, timedelta, timezone
from sync_keep_data import get_gspread_client, open_health_sheet, main as run_sync

def reconcile_past_7_days():
    run_sync()
    gc = get_gspread_client()
    sh = open_health_sheet(gc)
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
                try:
                    km = float(tr[3] or 0)
                    load_val = float(tr[10] or 0)
                except Exception:
                    load_val = 5.0
                if d60_start <= rd <= ymd:
                    load_60d += load_val
                if d7_start <= rd <= ymd:
                    load_7d += load_val

        real_acwr = round((load_7d * 60.0) / (load_60d * 7.0), 2) if load_60d > 0 else 0.0
        if abs(float(row[6] or 0) - real_acwr) > 0.05:
            ws_ana.update_cell(idx, 7, real_acwr)
            ws_ana.update_cell(idx, 19, "周日自动对账校准")
            ws_ana.update_cell(idx, 20, sync_ts)
            print(f"🔧 已校准 {ymd} 全运动 ACWR: {row[6]} -> {real_acwr}")

    print("🎉 周日对账与历史 ACWR 校准完成！")

if __name__ == "__main__":
    reconcile_past_7_days()
