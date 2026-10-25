import os
import sys
import json
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials

def get_sheets():
    sa_key = os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_CREDENTIALS")
    if not sa_key:
        raise RuntimeError("未找到 GCP_SA_KEY 密钥！")
    sa = json.loads(sa_key)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    client = gspread.authorize(Credentials.from_service_account_info(sa, scopes=scopes))
    sheet_id = os.environ.get("SPREADSHEET_ID") or os.environ.get("GOOGLE_SHEET_ID")
    return client.open_by_key(sheet_id.strip())

# 当日当餐标准推荐营养库（保底库）
RECOMMENDED_MEALS = {
    "上肢力量": {
        "早餐": {"kcal": 450, "carb": 60, "protein": 25, "fat": 12, "fiber": 6, "water": 400, "sodium": 350, "potassium": 450, "magnesium": 60, "sugar": 8, "desc": "全麦面包2片 + 水煮蛋2个 + 无糖牛奶"},
        "午餐": {"kcal": 750, "carb": 90, "protein": 50, "fat": 20, "fiber": 10, "water": 500, "sodium": 650, "potassium": 700, "magnesium": 90, "sugar": 5, "desc": "杂粮饭150g + 瘦牛肉150g + 西兰花"},
        "加餐": {"kcal": 280, "carb": 35, "protein": 25, "fat": 3, "fiber": 4, "water": 400, "sodium": 150, "potassium": 420, "magnesium": 45, "sugar": 14, "desc": "乳清蛋白1勺 + 香蕉1根"},
        "晚餐": {"kcal": 620, "carb": 65, "protein": 45, "fat": 18, "fiber": 8, "water": 500, "sodium": 550, "potassium": 600, "magnesium": 75, "sugar": 6, "desc": "蒸红薯150g + 清蒸鱼虾150g + 绿叶蔬菜"}
    },
    "腿膝力量": {
        "早餐": {"kcal": 480, "carb": 65, "protein": 24, "fat": 14, "fiber": 8, "water": 400, "sodium": 320, "potassium": 460, "magnesium": 70, "sugar": 6, "desc": "燕麦片60g + 水煮蛋2个 + 奇亚籽牛奶"},
        "午餐": {"kcal": 780, "carb": 95, "protein": 52, "fat": 22, "fiber": 9, "water": 500, "sodium": 620, "potassium": 720, "magnesium": 85, "sugar": 4, "desc": "糙米饭150g + 去皮鸡胸肉180g + 彩椒芦笋"},
        "加餐": {"kcal": 220, "carb": 25, "protein": 15, "fat": 2, "fiber": 4, "water": 400, "sodium": 100, "potassium": 380, "magnesium": 40, "sugar": 16, "desc": "胶原蛋白肽10g + 奇异果1个"},
        "晚餐": {"kcal": 650, "carb": 70, "protein": 46, "fat": 20, "fiber": 9, "water": 500, "sodium": 580, "potassium": 650, "magnesium": 80, "sugar": 5, "desc": "紫薯150g + 三文鱼150g + 菠菜豆腐汤"}
    },
    "default": {  # 休息日及常规跑步日
        "早餐": {"kcal": 420, "carb": 45, "protein": 25, "fat": 16, "fiber": 6, "water": 400, "sodium": 300, "potassium": 400, "magnesium": 60, "sugar": 8, "desc": "无糖希腊酸奶 + 坚果一把 + 水煮蛋2个"},
        "午餐": {"kcal": 680, "carb": 75, "protein": 45, "fat": 22, "fiber": 8, "water": 500, "sodium": 600, "potassium": 650, "magnesium": 80, "sugar": 4, "desc": "杂粮饭120g + 鸡胸肉150g + 蔬菜沙拉"},
        "加餐": {"kcal": 180, "carb": 15, "protein": 14, "fat": 6, "fiber": 3, "water": 350, "sodium": 120, "potassium": 250, "magnesium": 35, "sugar": 4, "desc": "无糖豆浆 + 蛋白棒半根"},
        "晚餐": {"kcal": 550, "carb": 50, "protein": 40, "fat": 18, "fiber": 8, "water": 500, "sodium": 500, "potassium": 550, "magnesium": 70, "sugar": 4, "desc": "豆腐菌菇煲 + 虾仁120g + 清炒时蔬"}
    }
}

def reconcile_daily_diet():
    print("🚀 启动每日全天饮食仲裁与落盘...")
    sh = get_sheets()
    ws_ana = sh.worksheet("每日分析")
    ws_diet = sh.worksheet("历史饮食记录")

    tz_cn = timezone(timedelta(hours=8))
    now_cn = datetime.now(tz_cn)
    ymd = (now_cn - timedelta(days=1)).strftime("%Y-%m-%d")

    plan_type = "default"
    for r in ws_ana.get_all_values()[1:]:
        if r and r[0] == ymd and len(r) > 15:
            if "上肢" in r[15]: plan_type = "上肢力量"
            elif "腿膝" in r[15]: plan_type = "腿膝力量"
            break
    rec_meals = RECOMMENDED_MEALS.get(plan_type, RECOMMENDED_MEALS["default"])

    # 1. 读取用户对话报备记录
    user_reported = {}
    if os.path.exists("daily_user_meals.json"):
        try:
            with open("daily_user_meals.json", "r", encoding="utf-8") as f:
                user_reported = json.load(f).get(ymd, {})
        except Exception:
            user_reported = {}

    # 2. 读取 Keep 记录
    keep_recorded = {}

    # 3. 四层仲裁核心逻辑
    final_meals = {}
    source_tags = []
    meal_tags = ["早餐", "午餐", "晚餐", "加餐"]

    for tag in meal_tags:
        if tag in user_reported and user_reported[tag]:
            # 规则1 & 规则2：只要我报了，无论Keep有没有，以我为准
            final_meals[tag] = user_reported[tag]
            source_tags.append(f"{tag}:用户报备")
        elif tag in keep_recorded and keep_recorded[tag]:
            # 规则3：我没报，Keep报了，以Keep为准
            final_meals[tag] = keep_recorded[tag]
            source_tags.append(f"{tag}:Keep记录")
        else:
            # 规则4：双方都没报，以当日推荐食谱保底补齐
            final_meals[tag] = rec_meals[tag]
            source_tags.append(f"{tag}:推荐食谱兜底")

    totals = {"kcal": 0.0, "carb": 0.0, "protein": 0.0, "fat": 0.0, "fiber": 0.0, "water": 0.0, "sodium": 0.0, "potassium": 0.0, "magnesium": 0.0, "sugar": 0.0}
    for m in final_meals.values():
        for k in totals:
            totals[k] += float(m.get(k, 0))

    final_row = [
        ymd,
        round(totals["kcal"], 1),
        round(totals["carb"], 1),
        round(totals["protein"], 1),
        round(totals["fat"], 1),
        round(totals["fiber"], 1),
        round(totals["water"], 1),
        round(totals["sodium"], 1),
        round(totals["potassium"], 1),
        round(totals["magnesium"], 1),
        round(totals["sugar"], 1),
        4,
        "；".join(source_tags)
    ]

    diet_all = ws_diet.get_all_values()
    found_idx = next((idx for idx, r in enumerate(diet_all[1:], start=2) if r and r[0] == ymd), None)

    if found_idx:
        ws_diet.update(range_name=f"A{found_idx}:M{found_idx}", values=[final_row], value_input_option="USER_ENTERED")
        print(f"✅ 《历史饮食记录》已更新: {ymd} | 来源: {'；'.join(source_tags)}")
    else:
        ws_diet.append_row(final_row, value_input_option="USER_ENTERED")
        print(f"✅ 《历史饮食记录》已追加: {ymd} | 来源: {'；'.join(source_tags)}")

if __name__ == "__main__":
    reconcile_daily_diet()
