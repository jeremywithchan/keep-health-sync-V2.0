import os
import sys
import time
import json
import traceback
from datetime import datetime, timedelta, timezone
import requests
import gspread
from google.oauth2.service_account import Credentials

def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None and str(val).strip() != "" else default
    except:
        return default

def safe_int(val, default=0):
    try:
        return int(float(val)) if val is not None and str(val).strip() != "" else default
    except:
        return default

# 1. 严格使用与 backfill 跑通版本 100% 一致的 Google 表格认证
def get_sheets():
    sa_key = (
        os.environ.get("GCP_SA_KEY") 
        or os.environ.get("GOOGLE_CREDENTIALS") 
        or os.environ.get("SERVICE_ACCOUNT_JSON")
    )
    if not sa_key:
        print("❌ 错误: 未找到 Google 服务账号密钥 (GCP_SA_KEY)，请检查 GitHub Secrets！")
        sys.exit(1)

    try:
        sa = json.loads(sa_key)
        # 只请求表格权限，避免 Drive 权限不足导致 403
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        client = gspread.authorize(Credentials.from_service_account_info(sa, scopes=scopes))
        
        sheet_id = (
            os.environ.get("SPREADSHEET_ID") 
            or os.environ.get("GOOGLE_SHEET_ID")
            or "DtTMPFXAJGhF"
        )
        sh = client.open_by_key(sheet_id.strip())
        return sh
    except Exception as e:
        print(f"❌ Google 表格连接失败: {e}")
        traceback.print_exc()
        sys.exit(1)

# 2. 严格使用与 backfill 跑通版本一致的 Keep 登录与抓取
def fetch_keep_records():
    phone = (
        os.environ.get("KEEP_PHONE") 
        or os.environ.get("KEEP_MOBILE") 
        or "19933193369"
    )
    password = os.environ.get("KEEP_PASSWORD") or "CHeng123"
    
    login_url = "https://api.gotokeep.com/v1.1/users/login"
    payload = {"mobile": phone, "password": password, "areaCode": "86"}
    headers = {"Content-Type": "application/json", "User-Agent": "Keep/7.0.0 (iPhone)"}
    
    try:
        res = requests.post(login_url, json=payload, headers=headers, timeout=20)
        data = res.json()
        token = data.get("data", {}).get("token") or data.get("data", {}).get("accessToken")
        if not token:
            print(f"⚠️ Keep 登录未获得 Token: {data}")
            return []
            
        fetch_url = "https://api.gotokeep.com/pd/v3/stats/detail?dateUnit=all&type=all"
        req_headers = {"Authorization": f"Bearer {token}", "User-Agent": "Keep/7.0.0 (iPhone)"}
        d_res = requests.get(fetch_url, headers=req_headers, timeout=30)
        d_json = d_res.json()
        return d_json.get("data", {}).get("records", [])
    except Exception as e:
        print(f"⚠️ Keep API 请求异常: {e}")
        return []

# 3. 铁律规则：越野跑无条件豁免，常规跑剔除散步与热身
def is_pure_running(l):
    km = safe_float(l.get("kmDistance"))
    dur = safe_float(l.get("duration"))
    if km <= 0.05:
        return False
    dt = (l.get("dataType") or "").lower()
    name = (l.get("name") or "").lower()
    tp = (l.get("type") or "").lower()

    # 铁律：只要有越野跑标识，无条件直接计入跑量，不设距离与时间门槛
    if "trail" in dt or "越野" in name:
        return True

    if any(k in dt for k in ["walking", "stair", "warmup", "stretching"]):
        return False
    if any(k in name for k in ["行走", "步行", "爬楼", "热身", "拉伸"]):
        return False

    is_run = (tp == "running") or ("running" in dt)
    if not is_run:
        return False

    if dur > 0 and (dur / km) > 660:  # 配速慢于 11 分/公里拦截
        return False
    return True

def is_valid_strength(l):
    dt = (l.get("dataType") or "")
    name = (l.get("name") or "")
    dur = safe_float(l.get("duration"))
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
    print("🚀 启动 Daily Keep Sync V2.0...")
    sh = get_sheets()
    ws_train = sh.worksheet("训练记录")
    ws_ana = sh.worksheet("每日分析")

    records = fetch_keep_records()
    print(f"📦 Keep 抓取到记录批次: {len(records)}")
    
    cleaned_by_date = {}
    new_rows = []

    for rc in records:
        for lg in rc.get("logs", []):
            s = lg.get("stats") if isinstance(lg, dict) else lg
            if not isinstance(s, dict) or not s.get("doneDate"):
                continue
            done_date = str(s["doneDate"])
            iso = done_date.split("T")[0]
            name = str(s.get("name", ""))
            dur = safe_int(s.get("duration"))
            km = safe_float(s.get("kmDistance"))
            cal = safe_int(s.get("calorie"))
            hr = s.get("heartRate") if isinstance(s.get("heartRate"), dict) else {}
            avg_hr = safe_float(hr.get("averageHeartRate"))
            max_hr = safe_float(hr.get("maxHeartRate"))
            elev = safe_float(s.get("accumulativeUpliftedHeight"))
            pace = safe_float(s.get("averagePace"))
            load = safe_float(s.get("trainingLoadScore"))
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

    # 4. 安全排重并正序追加至《训练记录》
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
        print(f"✅ 《训练记录》已追加 {len(to_append)} 条新数据。")
    else:
        print("ℹ️ 《训练记录》无新运动数据需追加。")

    # 5. 基于全运动负荷重新计算每日指标
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
        km = safe_float(row[3])
        hr = safe_float(row[6]) if row[6] and str(row[6]).strip() != "" else 0.0
        load_val = safe_float(row[10]) if row[10] else (km * 10 if km > 0 else 5.0)
        dtype = row[12]

        # 核心铁律：ACWR 统计全部运动情况
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
    warn_str = "；".join(warns) if warns else "状态良好"

    yd_logs = cleaned_by_date.get(ymd, [])
    sync_ts = now_cn.strftime("%Y-%m-%d %H:%M:%S")

    ana_row = [
        ymd, round(wk_km, 2), r7_cnt, s7_cnt, r7_hr, z2_r,
        acwr, trail_7d, round(yd_run_km, 2), yd_str_cnt,
        json.dumps(yd_logs, ensure_ascii=False), warn_str,
        s_goal, wn, target_km, t_plan, p_km, p_elev, "自动同步", sync_ts
    ]

    # 更新或追加到《每日分析》
    ana_all = ws_ana.get_all_values()
    found_idx = next((idx for idx, r_val in enumerate(ana_all[1:], start=2) if r_val and r_val[0] == ymd), None)

    if found_idx:
        ws_ana.update(range_name=f"A{found_idx}:T{found_idx}", values=[ana_row], value_input_option="USER_ENTERED")
        print(f"✅ 已更新《每日分析》 {ymd} | 全运动 ACWR={acwr}")
    else:
        ws_ana.append_row(ana_row, value_input_option="USER_ENTERED")
        print(f"✅ 已追加《每日分析》 {ymd} | 全运动 ACWR={acwr}")

    print("🎉 Daily Keep Sync V2.0 执行成功！")

if __name__ == "__main__":
    main()
