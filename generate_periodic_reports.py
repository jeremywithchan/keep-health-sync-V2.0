import os
import json
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

def get_gspread_client():
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS") or os.environ.get("SERVICE_ACCOUNT_JSON")
    if sa_key and sa_key.strip().startswith("{"):
        sa = json.loads(sa_key)
    else:
        # 兼容本地文件
        for fn in ["credentials.json", "service_account.json", "gcp_key.json"]:
            if os.path.exists(fn):
                with open(fn, "r", encoding="utf-8") as f:
                    sa = json.load(f)
                break
        else:
            raise RuntimeError("未找到 Google 密钥凭证！")
    return gspread.authorize(Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]))

def open_health_sheet(gc):
    sheet_id = os.environ.get("GOOGLE_SHEET_ID") or os.environ.get("SPREADSHEET_ID")
    if sheet_id and sheet_id.strip():
        try:
            return gc.open_by_key(sheet_id.strip())
        except Exception:
            pass
    return gc.open("每周健康- 训练与运动数据")

def calc_period_stats(rows, start_d, end_d):
    run_km, run_cnt, str_cnt, dur_s, kcal = 0.0, 0, 0, 0, 0
    hr_s, hr_n, z2_c = 0.0, 0, 0
    for r in rows:
        if len(r) < 12:
            continue
        d = r[0]
        if start_d <= d <= end_d:
            tp = r[1]
            km = float(r[3] or 0)
            dur = int(float(r[4] or 0))
            cal = int(float(r[5] or 0))
            hr = float(r[6]) if r[6] and str(r[6]).strip() != "" else 0.0
            dur_s += dur
            kcal += cal
            if tp == "running" and km > 0:
                run_km += km
                run_cnt += 1
                if hr > 0:
                    hr_s += hr
                    hr_n += 1
                    if 139 <= hr < 157:
                        z2_c += 1
            elif tp == "training":
                str_cnt += 1
    avg_hr = round(hr_s / hr_n) if hr_n > 0 else 0
    z2_r = round((z2_c / hr_n) * 100) if hr_n > 0 else 0
    return {
        "km": round(run_km, 2), "run_cnt": run_cnt, "str_cnt": str_cnt,
        "hours": round(dur_s / 3600.0, 2), "kcal": kcal, "avg_hr": avg_hr, "z2_r": z2_r
    }

def main():
    gc = get_gspread_client()
    sh = open_health_sheet(gc)
    ws_train = sh.worksheet("训练记录")
    ws_rep = sh.worksheet("周期健康报告")

    rows = ws_train.get_all_values()[1:]
    tz_cn = timezone(timedelta(hours=8))
    gen_ts = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M:%S")

    tasks = [
        ("年度健康报告", "2025-01-01 ~ 2025-12-31", ("2025-01-01", "2025-12-31"), "前 2 年均值 (2023年、2024年)", [("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31")]),
        ("季度健康报告", "2026-07-01 ~ 2026-09-30", ("2026-07-01", "2026-09-30"), "去年同季度 (2025年 Q3)", [("2025-07-01", "2025-09-30")]),
        ("月度健康报告", "2026-09-01 ~ 2026-09-30", ("2026-09-01", "2026-09-30"), "前 2 个月均值 (2026-07、2026-08)", [("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-31")]),
        ("周度健康报告", "2026-10-19 ~ 2026-10-25", ("2026-10-19", "2026-10-25"), "前 6 周均值", [
            ("2026-09-07", "2026-09-13"), ("2026-09-14", "2026-09-20"),
            ("2026-09-21", "2026-09-27"), ("2026-09-28", "2026-10-04"),
            ("2026-10-05", "2026-10-11"), ("2026-10-12", "2026-10-18")
        ])
    ]

    out_rows = []
    for r_type, p_label, (cur_s, cur_e), base_desc, base_list in tasks:
        cur = calc_period_stats(rows, cur_s, cur_e)
        b_stats = [calc_period_stats(rows, bs, be) for bs, be in base_list]
        n_b = len(b_stats)
        b_km = round(sum(x["km"] for x in b_stats) / n_b, 2)
        b_rc = round(sum(x["run_cnt"] for x in b_stats) / n_b, 1)
        b_sc = round(sum(x["str_cnt"] for x in b_stats) / n_b, 1)
        b_hr = round(sum(x["hours"] for x in b_stats) / n_b, 2)
        b_cal = round(sum(x["kcal"] for x in b_stats) / n_b)

        pct_km = f"{round((cur['km'] - b_km) / b_km * 100, 1):+}%" if b_km > 0 else "新增"
        hr_str = f"均心率 {cur['avg_hr'] or '-'} bpm / Z2占比 {cur['z2_r']}%"
        advice = "跑量负荷平稳受控；力量训练执行良好；请继续保持 Z2 有氧心率区间(139-157bpm)纪律。"

        md = (
            f"### 📊 {r_type} | {p_label}\n"
            f"- **统计周期**：{p_label}\n"
            f"- **对比基准**：{base_desc}\n"
            f"#### 1. 核心指标对比\n"
            f"| 指标 | 本期数值 | 基准期均值 | 变化 |\n"
            f"| :--- | :--- | :--- | :--- |\n"
            f"| 跑步总距离 | {cur['km']} km | {b_km} km | {pct_km} |\n"
            f"| 跑步次数 | {cur['run_cnt']} 次 | {b_rc} 次 | - |\n"
            f"| 力量训练次数 | {cur['str_cnt']} 次 | {b_sc} 次 | - |\n"
            f"| 总运动时长 | {cur['hours']} 小时 | {b_hr} 小时 | - |\n"
            f"| 总热量消耗 | {cur['kcal']} kcal | {b_cal} kcal | - |\n"
            f"| 跑步均心率 | {cur['avg_hr'] or '-'} bpm | - | Z2占比 {cur['z2_r']}% |\n"
        )

        out_rows.append([
            gen_ts, r_type, p_label, base_desc,
            f"{cur['km']} km (基准均 {b_km} km | {pct_km})",
            f"{cur['run_cnt']} 次 (基准均 {b_rc} 次)",
            f"{cur['str_cnt']} 次 (基准均 {b_sc} 次)",
            f"{cur['hours']} h (基准均 {b_hr} h)",
            f"{cur['kcal']} kcal (基准均 {b_cal} kcal)",
            hr_str, advice, md
        ])

    ws_rep.clear()
    ws_rep.append_row([
        "报告生成时间", "报告类型", "本期时间范围", "对比基准说明",
        "跑量对比 (本期 vs 基准)", "跑步次数对比", "力量训练对比",
        "运动时长对比", "卡路里消耗对比", "心率与有氧Z2表现", "健康评估与训练建议", "Markdown报告全文"
    ])
    ws_rep.append_rows(out_rows, value_input_option="USER_ENTERED")
    print("🎉 《周期健康报告》定期生成完毕！")

if __name__ == "__main__":
    main()
