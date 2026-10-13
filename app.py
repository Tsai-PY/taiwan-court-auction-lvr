# -*- coding: utf-8 -*-
"""
司法院法拍屋 × 內政部實價登錄 比對系統 Web 伺服器
採用 Flask 提供現代化網頁介面、RESTful API 與後端自動排程
"""

import os
import sys
import csv
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, send_file, request

# 防止 Windows 終端輸出編碼錯誤
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from daily_court_lvr_runner import DailyCourtLvrRunner

app = Flask(__name__)
runner = DailyCourtLvrRunner()

LATEST_CSV_PATH = os.path.join(runner.output_dir, "法拍與實價登錄比對清單_最新.csv")
STATE_JSON_PATH = os.path.join(runner.output_dir, "latest_state.json")


def load_cached_records():
    """從本地 CSV 快取讀取現有比對資料"""
    if not os.path.exists(LATEST_CSV_PATH):
        # 首次啟動若無資料，直接自動執行一次
        print("[Web 伺服器] 首次載入，自動初始化抓取法拍與實登資料...")
        result = runner.run_daily_pipeline(max_pages=2, page_size=20, open_browser=False)
        return result.get("records", [])

    records = []
    try:
        with open(LATEST_CSV_PATH, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) < 15:
                    continue

                # 價格轉數值以供計算
                try:
                    court_price_val = float(row[2].replace(",", ""))
                except Exception:
                    court_price_val = 0.0

                try:
                    lvr_price_val = float(row[10].replace(",", ""))
                except Exception:
                    lvr_price_val = 0.0

                # 案號與法院拆解
                case_info = row[5]
                parts = case_info.split(" ", 1)
                court_nm = parts[0] if parts else ""
                case_no = parts[1] if len(parts) > 1 else case_info

                address_encoded = row[1]
                map_url = f"https://www.google.com/maps/search/?api=1&query={address_encoded}"

                records.append({
                    "court_county": row[0],
                    "court_address": row[1],
                    "court_price": court_price_val,
                    "court_price_str": row[2],
                    "court_round": row[3],
                    "court_date": row[4],
                    "court_court_name": court_nm,
                    "court_case_no": case_no,
                    "court_check": row[6],
                    "google_map_url": map_url,

                    "lvr_county": row[8],
                    "lvr_address": row[9],
                    "lvr_price": lvr_price_val,
                    "lvr_price_str": row[10],
                    "lvr_unit_price": row[11],
                    "lvr_deal_date": row[12],
                    "lvr_building_type": "房地買賣",
                    "lvr_match_type": row[13],
                    "lvr_diff_analysis": row[14]
                })
    except Exception as e:
        print(f"[Web 伺服器] 讀取快取失敗: {e}")

    return records


@app.route("/")
def index():
    """主網頁介面"""
    return render_template("index.html")


@app.route("/api/records", methods=["GET"])
def api_records():
    """取得比對紀錄列表與狀態"""
    records = load_cached_records()
    last_modified = ""
    if os.path.exists(LATEST_CSV_PATH):
        mtime = os.path.getmtime(LATEST_CSV_PATH)
        last_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    return jsonify({
        "success": True,
        "count": len(records),
        "last_update": last_modified,
        "records": records
    })


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """手動觸發連線抓取最新法拍與比對"""
    try:
        pages = int(request.args.get("pages", 3))
        result = runner.run_daily_pipeline(max_pages=pages, page_size=25, open_browser=False)
        return jsonify({
            "success": True,
            "count": result["count"],
            "message": f"成功更新 {result['count']} 筆最新法拍與實登比對資料！"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"同步失敗: {str(e)}"
        }), 500


@app.route("/api/export", methods=["GET"])
def api_export():
    """分別支援 Excel (.xlsx) 與 CSV (.csv) 格式匯出下載"""
    if not os.path.exists(LATEST_CSV_PATH):
        load_cached_records()

    fmt = request.args.get("format", "csv").lower()
    today_str = datetime.now().strftime("%Y%m%d")

    if fmt in ["excel", "xlsx"]:
        xlsx_path = os.path.join(runner.output_dir, "法拍與實價登錄比對清單_最新.xlsx")
        if os.path.exists(xlsx_path):
            return send_file(
                xlsx_path,
                as_attachment=True,
                download_name=f"臺南高雄法拍屋與實價登錄比對清單_{today_str}.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    return send_file(
        LATEST_CSV_PATH,
        as_attachment=True,
        download_name=f"臺南高雄法拍屋與實價登錄比對清單_{today_str}.csv",
        mimetype="text/csv"
    )


def background_daily_scheduler():
    """背景執行緒：每日定時檢測並在 08:30 自動同步最新資料"""
    last_synced_day = ""
    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        # 每天 08:30 ~ 08:45 間執行每日同步
        if now.hour == 8 and now.minute >= 30 and last_synced_day != today:
            print(f"[排程器] 觸發每日 08:30 定時同步作業 [{today}]...")
            try:
                runner.run_daily_pipeline(max_pages=3, page_size=25, open_browser=False)
                last_synced_day = today
                print(f"[排程器] 每日自動同步作業完成。")
            except Exception as e:
                print(f"[排程器] 自動同步失敗: {e}")

        time.sleep(60)  # 每分鐘檢測一次


if __name__ == "__main__":
    # 啟動每日自動排程背景執行緒
    sched_thread = threading.Thread(target=background_daily_scheduler, daemon=True)
    sched_thread.start()

    print("=" * 65)
    print("🌐 【法拍屋 × 實價登錄】網頁版伺服器已啟動！")
    print("👉 請在瀏覽器打開網址: http://localhost:5000")
    print("=" * 65)

    app.run(host="0.0.0.0", port=5000, debug=False)
