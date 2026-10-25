import os
import json
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials

def main():
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS")
    sheet_id = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID")
    sa = json.loads(sa_key)
    client = gspread.authorize(Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    sh = client.open_by_key(sheet_id)
    ws_ana = sh.worksheet("每日分析")
    ws_rep = sh.worksheet("每日日报")

    ana_rows = ws_ana.get_all_values()
    if len(ana_rows) < 2: return

    latest = ana_rows[-1]
    ymd, wk_km, r7_cnt, s7_cnt, r7_hr, z2_r, acwr = latest[0], latest[1], latest[2], latest[3], latest[4], latest[5], float(latest[6] or 0)
    yd_logs_str = latest[10] if len(latest) > 10 else "[]"
    wn = latest[13] if len(latest) > 13 else "6"
    target_km = latest[14] if len(latest) > 14 else "18"
    today_plan = latest[15] if len(latest) > 15 else "休息"

    try: yd_logs = json.loads(yd_logs_str)
    except: yd_logs = []

    if yd_logs:
        yd_summary = "；".join([f"{lg.get('name', '训练')} ({lg.get('kmDistance', 0)}km, {round(float(lg.get('duration', 0))/60)}分钟, 均心率:{lg.get('avgHR') or '-'}bpm)" for lg in yd_logs])
    else: yd_summary = "昨日无运动记录（休息日）"

    if "上肢" in today_plan:
        macro, spec = "碳水 4 g/kg | 蛋白质 1.8 g/kg", "训练后补充乳清蛋白/鸡蛋 + 香蕉，促进上肢肌群修复"
        meals = "- **早餐**：全麦面包2片 + 水煮蛋2个\n- **午餐**：杂粮饭150g + 瘦牛肉150g + 西兰花\n- **晚餐**：蒸红薯150g + 清蒸鱼虾150g"
    elif "腿膝" in today_plan:
        macro, spec = "碳水 4 g/kg | 蛋白质 1.8 g/kg", "训练后补充胶原蛋白肽 + 维生素C，强化膝关节软骨与肌腱"
        meals = "- **早餐**：燕麦片60g + 水煮蛋2个\n- **午餐**：糙米饭150g + 去皮鸡胸肉180g\n- **晚餐**：紫薯150g + 三文鱼/鳕鱼150g"
    elif "越野" in today_plan:
        macro, spec = "碳水 6 g/kg | 蛋白质 1.5 g/kg", "运动中每 45 分钟补充能量胶 1 支 + 盐丸 1-2 粒"
        meals = "- **早餐**：白米粥 + 鸡蛋2个 + 香蕉1根\n- **午餐**：面条200g + 瘦牛肉150g\n- **晚餐**：蒸土豆180g + 清蒸海鱼150g"
    elif "跑" in today_plan or "Z2" in today_plan:
        macro, spec = "碳水 5 g/kg | 蛋白质 1.5 g/kg", "运动前 1 小时全麦面包 + 花生酱，稳定有氧供能"
        meals = "- **早餐**：燕麦牛奶粥 + 水煮蛋2个\n- **午餐**：杂粮米饭180g + 鸡胸肉160g\n- **晚餐**：藜麦饭120g + 虾仁豆腐煲"
    else:
        macro, spec = "碳水 3-4 g/kg | 蛋白质 1.6 g/kg", "增加优质脂肪，全天饮水 2L+"
        meals = "- **早餐**：无糖希腊酸奶 + 坚果\n- **午餐**：杂粮饭120g + 鸡胸肉150g\n- **晚餐**：豆腐菌菇煲 + 虾仁120g"

    anti_inf = "\n- ⚠️ **高负荷抗炎加餐（ACWR>1.3 触发）**：补充蓝莓、酸樱桃汁及 Omega-3。" if acwr > 1.3 else ""

    md = (
        f"# 🏃 训练日报 ({ymd}) | 第 {wn} 周 | 维持体重·保持活力\n"
        f"### 1. 近 7 天训练概览\n- **跑量**：{wk_km} km | **力量**：{s7_cnt}次 | **均心率**：{r7_hr} bpm | **ACWR**：{acwr}\n"
        f"### 2. 核心达标监控\n- **本周跑量进度**：{wk_km} / {target_km} km\n- **ACWR 负荷比**：{acwr}（安全区间 0.8-1.3）\n- **Z2 心率占比**：{z2_r}%\n"
        f"### 3. 昨日训练明细\n- {yd_summary}\n"
        f"### 4. 今日营养建议（适配：{today_plan}）\n- **宏量目标**：{macro}\n- **专项补给**：{spec}{anti_inf}\n{meals}\n"
        f"### 5. 今日训练重点\n> **{today_plan}**"
    )

    tz_cn = timezone(timedelta(hours=8))
    gen_ts = datetime.now(tz_cn).strftime("%Y-%m-%d %H:%M:%S")

    rep_all = ws_rep.get_all_values()
    found_idx = next((idx for idx, r_val in enumerate(rep_all[1:], start=2) if r_val and r_val[0] == ymd), None)

    if found_idx:
        ws_rep.update(range_name=f"A{found_idx}:C{found_idx}", values=[[ymd, md, gen_ts]], value_input_option="USER_ENTERED")
    else:
        ws_rep.append_row([ymd, md, gen_ts], value_input_option="USER_ENTERED")

if __name__ == "__main__":
    main()
