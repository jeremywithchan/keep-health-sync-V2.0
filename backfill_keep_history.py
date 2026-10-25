import os
import json
import time
from datetime import datetime
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

def get_keep_token(phone, password):
    url = "https://api.gotokeep.com/v1.1/users/login"
    payload = {"mobile": phone, "password": password, "areaCode": "86"}
    headers = {"Content-Type": "application/json", "User-Agent": "Keep/7.0.0 (iPhone)"}
    res = requests.post(url, json=payload, headers=headers, timeout=15)
    data = res.json()
    return data["data"].get("token") or data["data"].get("accessToken")

def fetch_all_keep_logs(token):
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "Keep/7.0.0 (iPhone)"}
    url = "https://api.gotokeep.com/pd/v3/stats/detail?dateUnit=all&type=all"
    res = requests.get(url, headers=headers, timeout=25)
    d = res.json()
    
    cleaned_rows = []
    for rc in d.get("data", {}).get("records", []):
        for lg in rc.get("logs", []):
            s = lg.get("stats") if isinstance(lg, dict) else lg
            if not isinstance(s, dict) or not s.get("doneDate"):
                continue
            done_date = str(s["doneDate"])
            iso_date = done_date.split("T")[0]
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
            
            cleaned_rows.append([
                iso_date, str(s.get("type", "")), name, km, dur, cal,
                avg_hr if avg_hr > 0 else "", max_hr if max_hr > 0 else "",
                elev, pace, load, done_date, str(s.get("dataType", ""))
            ])
    return cleaned_rows

if __name__ == "__main__":
    phone = os.environ.get("KEEP_PHONE") or os.environ.get("KEEP_MOBILE")
    password = os.environ.get("KEEP_PASSWORD")
    token = get_keep_token(phone, password)
    keep_rows = fetch_all_keep_logs(token)
    
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS")
    sa = json.loads(sa_key)
    client = gspread.authorize(Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    
    sheet_id = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID")
    sheet = client.open_by_key(sheet_id).worksheet("训练记录")
    
    existing_all = sheet.get_all_values()
    existing_keys = set()
    for r in existing_all[1:]:
        if len(r) > 11 and r[11]:
            existing_keys.add(str(r[11]))
        elif len(r) > 3:
            existing_keys.add(f"{r[0]}_{r[2]}_{r[3]}")
            
    new_to_insert = []
    for r in keep_rows:
        k = str(r[11])
        if k not in existing_keys:
            new_to_insert.append(r)
            existing_keys.add(k)
            
    if new_to_insert:
        new_to_insert.sort(key=lambda x: str(x[11]))
        sheet.append_rows(new_to_insert, value_input_option="USER_ENTERED")
        print(f"成功补充写入 {len(new_to_insert)} 条运动记录")
    else:
        print("表格已包含近期记录，无需重复追加。")
