import os
import time
import json
from datetime import datetime, timedelta, timezone
import requests
import gspread
from google.oauth2.service_account import Credentials

def get_gspread_client():
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS") or os.environ.get("SERVICE_ACCOUNT_JSON")
    if not sa_key:
        raise RuntimeError("未找到 GCP_SA_KEY 或 GOOGLE_CREDENTIALS 密钥，请检查 GitHub Secrets！")
    
    if sa_key.strip().startswith("{"):
        sa = json.loads(sa_key)
    else:
        for fn in ["credentials.json", "service_account.json", "gcp_key.json"]:
            if os.path.exists(fn):
                with open(fn, "r", encoding="utf-8") as f:
                    sa = json.load(f)
                break
        else:
            raise RuntimeError("无法解析 Google 服务账号密钥！")
            
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    return gspread.authorize(Credentials.from_service_account_info(sa, scopes=scopes))

def open_health_sheet(gc):
    sheet_id = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID")
    if sheet_id and sheet_id.strip():
        try:
            return gc.open_by_key(sheet_id.strip())
        except Exception:
            pass
    return gc.open("每周健康- 训练与运动数据")

def fetch_keep_records():
    mobile = os.environ.get("KEEP_PHONE") or os.environ.get("KEEP_MOBILE") or "19933193369"
    password = os.environ.get("KEEP_PASSWORD") or "CHeng123"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Keep/7.0.0 (iPhone)"
    }
    for attempt in range(2):
        try:
            lr = requests.post(
                "https://api.gotokeep.com/v1.1/users/login",
                json={"mobile": mobile, "password": password, "areaCode": "86"},
                headers=headers,
                timeout=20
            )
            ld = lr.json()
            if ld.get("ok"):
                token = ld["data"].get("token") or ld["data"].get("accessToken")
                r = requests.get(
                    "https://api.gotokeep.com/pd/v3/stats/detail?dateUnit=all&type=all",
                    headers={"Authorization": f"Bearer {token}", "User-Agent": headers["User-Agent"]},
                    timeout=30
                )
                d = r.json()
                if d.get("ok"):
                    return d.get("data", {}).get("records", [])
        except Exception as e:
            print(f"⚠️ Keep 请求异常 (尝试 {attempt+1}/2): {e}")
        if attempt == 0:
            time.sleep(5)
    return []

def is_pure_running(l):
    km = float(l.get("kmDistance") or 0)
    dur = float(l.get("duration") or 0)
    if km <= 0.05:
        return False
    dt = (l.get("dataType") or "").lower()
    name = (l.get("name") or "").lower()
    tp = (l.get("type") or "").lower()

    # 铁律：只要带有越野跑标识，无条件直接纳入跑量统计
    if "trail" in dt or "越野" in name:
        return True

    if any(k in dt for k in ["walking", "stair", "warmup", "stretching"]):
        return False
    if any(k in name for k in ["行走", "步行", "爬楼", "热身", "拉伸"]):
        return False

    is_run = (tp == "running") or ("running" in dt)
    if not is_run:
        return False

    if dur > 0 and (dur / km) > 660:
        return False
    return True

def is_valid_strength(l):
    dt = (l.get("dataType") or "")
    name = (l.get("name") or "")
    dur = float(l.get("duration") or 0)
    if dur < 60:
        return False
    if any(k in name for k in ["热身", "拉伸", "放松", "行走", "步行", "爬楼"]):
        return False
    return (
        dt in ["traditionalGymTraining", "manualStrengthTraining", "equipmentFunctionalTraining"]
        or ("力量" in name)
        or ("平板支撑" in name)
    )

def main():
    gc = get_gspread_client()
    sh = open_health_sheet(gc)
    ws_train = sh.worksheet("训练记录")
    ws_ana = sh.worksheet("每日分析")

    records = fetch_keep_records()
    cleaned_by_date = {}
    new_rows = []

    for rc in records:
        logs_raw = rc.get("logs", [])
        for lg in logs_raw:
            s = lg.get("stats") if isinstance(lg, dict) else lg
            if not isinstance(s, dict) or not s.get("doneDate"):
                continue
            done_date = str(s["doneDate"])
            iso = done_date.split("T")[0]
            name = str(s.get("name", ""))
            dur = int(float(s.get("duration", 0) or 0))
            km = float(s.get("kmDistance", 0) or 0)
            cal = int(float(s.get("calorie", 0) or 0))
            hr = s.get("heartRate") if isinstance(s.get("heartRate"), dict) else {}
            avg_hr = float(hr.get("averageHeartRate", 0) or 0)
            max_hr = float(hr.get("maxHeartRate", 0) or 0)
            elev = float(s.get("accumulativeUpliftedHeight", 0) or 0)
            pace = float(s.get("averagePace", 0) or 0)
            load = float(s.get("trainingLoadScore", 0) or 0)
            tp = str(s.get("type", ""))
            dt = str(s.get("dataType", ""))

            item = {
                "isoDate": iso, "type": tp, "name": name,
                "kmDistance": round(km, 2), "duration": dur, "calorie": cal,
                "avgHR": avg_hr if avg_hr > 0 else "", "maxHR": max_hr if max_hr > 0 else "",
                "elevation": round(elev, 1), "doneDate": done_date, "dataType": dt,
                "pace": round(pace, 1), "loadScore": round(load, 1)
            }
            cleaned_by_date.setdefault(iso, []).append(item)

            if is_pure_running(item):
                run_dtype = "trailRunning" if ("trail" in dt.lower() or "越野" in name) else "outdoorRunning"
                new_rows.append([
                    iso, "running", f"{name} (Keep)", item["kmDistance"],
                    item["duration"], item["calorie"], item["avgHR"], item["maxHR"],
                    item["elevation"], item["pace"], item["loadScore"], done_date, run_dtype
                ])
            elif is_valid_strength(item):
                new_rows.append([
                    iso, "training", f"{name} (Keep)", 0,
                    item["duration"], item["calorie"], item["avgHR"], item["maxHR"],
                    0, 0, item["loadScore"], done_date, dt
                ])

    existing_train = ws_train.get_all_values()
    existing_keys = set()
    for r in existing_train[1:]:
        if len(r) > 11 and r[11]:
            existing_keys.add(str(r[11]))
        elif len(r) > 3:
            existing_keys.add(f"{r[0]}_{r[2]}_{r[3]}")

    to_append = []
    for r in new_rows:
        k = str(r[11])
        if k not in existing_keys:
            to_append.append(r)
            existing_keys.add(k)

    if to_append:
        to_append.sort(key=lambda x: str(x[11]))
        ws_train.append_rows(to_append, value_input_option="USER_ENTERED")
        print(f"✅ 已向《训练记录》底部正序追加 {len(to_append)} 条新记录。")

    all_train = ws_train.get_all_values()[1:]
    tz_cn = timezone(timedelta(hours=8))
    now_cn = datetime.now(tz_cn)
    yd_dt = (now_cn - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ymd = yd_dt.strftime("%Y-%m-%d")

    pst_dt = datetime(2026, 9, 15, tzinfo=tz_cn)
    dss = (yd_dt - pst_dt).days
    wn = max(1, (dss // 7) + 1)
    wi = (wn - 1) % 8
    WT = [14, 16, 18, 16, 14, 18, 16, 14]
    target_km = WT[wi]

    d7_start = (yd_dt - timedelta(days=6)).strftime("%Y-%m-%d")
    d60_start = (yd_dt - timedelta(days=59)).strftime("%Y-%m-%d")
    wk_start = (yd_dt - timedelta(days=yd_dt.weekday())).strftime("%Y-%m-%d")

    r7_km, r7_cnt, r7_hr_s, r7_hr_n = 0.0, 0, 0.0, 0
    wk_km = 0.0
    s7_cnt, z2_c, z2_t, trail_7d = 0, 0, 0, 0
    yd_run_km, yd_str_cnt = 0.0, 0
    load_7d, load_60d = 0.0, 0.0

    for row in all_train:
        if len(row) < 13:
            continue
        rd, rt = row[0], row[1]
        try:
            km = float(row[3] or 0)
        except Exception:
            km = 0.0
        try:
            hr = float(row[6]) if row[6] and str(row[6]).strip() != "" else 0.0
        except Exception:
            hr = 0.0
        try:
            load_val = float(row[10] or 0)
        except Exception:
            load_val = km * 10 if km > 0 else 5.0

        dtype = row[12]

        if d60_start <= rd <= ymd:
            load_60d += load_val
        if wk_start <= rd <= ymd and rt == "running":
            wk_km += km
        if d7_start <= rd <= ymd:
            load_7d += load_val
            if rt == "running" and km > 0:
                r7_km += km
                r7_cnt += 1
                if "trail" in dtype.lower() or "越野" in row[2]:
                    trail_7d = 1
                if hr > 0:
                    r7_hr_s += hr
                    r7_hr_n += 1
                    z2_t += 1
                    if 139 <= hr < 157:
                        z2_c += 1
            elif rt == "training":
                s7_cnt += 1
        if rd == ymd:
            if rt == "running":
                yd_run_km += km
            elif rt == "training":
                yd_str_cnt += 1

    acwr = round((load_7d * 60.0) / (load_60d * 7.0), 2) if load_60d > 0 else 0.0
    r7_hr = round(r7_hr_s / r7_hr_n) if r7_hr_n > 0 else 0
    z2_r = round((z2_c / z2_t) * 100) if z2_t > 0 else 0

    PLAN_CYCLE = [
        ("上肢力量", 0, 0, "上肢力量强化"),
        ("Z2跑 7km", 7, 0, "控制心率139-157bpm"),
        ("腿膝力量", 0, 0, "腿膝力量强化"),
        ("休息", 0, 0, "主动恢复"),
        ("上肢力量", 0, 0, "上肢力量维持"),
        ("越野跑 10km/300m", 10, 300, "长距离有氧耐力"),
        ("休息", 0, 0, "周日恢复与拉伸")
    ]
    t_plan, p_km, p_elev, s_goal = PLAN_CYCLE[(dss + 1) % 7]

    warns = []
    if acwr > 1.3:
        warns.append("ACWR>1.3超负荷")
    if z2_r < 40 and r7_cnt > 0:
        warns.append("Z2占比偏低(<40%)")
    if s7_cnt < 3:
        warns.append("力量训练不足3次")
    warn_str = "；".join(warns) if warns else "Status OK"

    yd_logs = cleaned_by_date.get(ymd, [])
    sync_ts = now_cn.strftime("%Y-%m-%d %H:%M:%S")

    ana_row = [
        ymd, round(wk_km, 2), r7_cnt, s7_cnt, r7_hr, z2_r,
        acwr, trail_7d, round(yd_run_km, 2), yd_str_cnt,
        json.dumps(yd_logs, ensure_ascii=False), warn_str,
        s_goal, wn, target_km, t_plan, p_km, p_elev, "自动同步", sync_ts
    ]

    ana_all = ws_ana.get_all_values()
    found_idx = None
    for idx, r_val in enumerate(ana_all[1:], start=2):
        if r_val and r_val[0] == ymd:
            found_idx = idx
            break

    if found_idx:
        ws_ana.update(range_name=f"A{found_idx}:T{found_idx}", values=[ana_row], value_input_option="USER_ENTERED")
    else:
        ws_ana.append_row(ana_row, value_input_option="USER_ENTERED")
    print(f"✅ 《每日分析》同步完成 | 全运动 ACWR={acwr}")

if __name__ == "__main__":
    main()
