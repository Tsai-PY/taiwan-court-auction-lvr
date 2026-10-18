# -*- coding: utf-8 -*-
"""
內政部實價登錄下載、快取與鄰近交易比對模組
資料來源: 內政部不動產交易實價查詢服務網 (Open Data)
"""

import os
import io
import re
import csv
import ssl
import zipfile
import sqlite3
import urllib.request
from typing import Dict, Any, Optional, List

# 縣市與內政部實價登錄 CSV 代號對應表
COUNTY_CODE_MAP = {
    "臺北市": "a", "台北市": "a",
    "臺中市": "b", "台中市": "b",
    "基隆市": "c",
    "臺南市": "d", "台南市": "d",
    "高雄市": "e",
    "新北市": "f",
    "宜蘭縣": "g",
    "桃園市": "h",
    "嘉義市": "i",
    "新竹縣": "j",
    "苗栗縣": "k",
    "南投縣": "m",
    "彰化縣": "n",
    "新竹市": "o",
    "雲林縣": "p",
    "嘉義縣": "q",
    "屏東縣": "t",
    "花蓮縣": "u",
    "臺東縣": "v", "台東縣": "v",
    "金門縣": "w",
    "澎湖縣": "x",
    "連江縣": "z",
}

CODE_TO_COUNTY = {
    "a": "臺北市", "b": "臺中市", "c": "基隆市", "d": "臺南市",
    "e": "高雄市", "f": "新北市", "g": "宜蘭縣", "h": "桃園市",
    "i": "嘉義市", "j": "新竹縣", "k": "苗栗縣", "m": "南投縣",
    "n": "彰化縣", "o": "新竹市", "p": "雲林縣", "q": "嘉義縣",
    "t": "屏東縣", "u": "花蓮縣", "v": "臺東縣", "w": "金門縣",
    "x": "澎湖縣", "z": "連江縣",
}


class LvrMatcher:
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "lvr_transactions.db")
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 資料表與索引"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    county TEXT,
                    town TEXT,
                    road TEXT,
                    address TEXT,
                    total_price REAL,
                    unit_price_sqm REAL,
                    unit_price_ping REAL,
                    building_area REAL,
                    deal_date TEXT,
                    building_type TEXT,
                    target_type TEXT,
                    note TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_county_town ON transactions(county, town)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_road ON transactions(county, town, road)")
            conn.commit()

    def download_and_import_season(self, season: str = "114S1", force_reload: bool = False):
        """
        下載並解壓縮特定季度的實價登錄資料，匯入 SQLite
        season: 例如 '114S1', '113S4'
        """
        zip_path = os.path.join(self.data_dir, f"lvr_{season}.zip")
        if not os.path.exists(zip_path) or force_reload:
            print(f"[實價登錄] 正在從內政部下載 {season} 季最新實價登錄資料包...")
            url = f"https://plvr.land.moi.gov.tw//DownloadSeason?season={season}&type=zip&fileName=lvr_landcsv.zip"
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            try:
                with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
                    content = resp.read()
                with open(zip_path, "wb") as f:
                    f.write(content)
                print(f"[實價登錄] {season} 實價資料下載成功 ({len(content) // 1024} KB)！")
            except Exception as e:
                print(f"[實價登錄] 下載失敗: {e}，將嘗試讀取現有資料庫快取。")
                return

        # 檢查資料庫是否已匯入過該季資料
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM transactions")
            cnt = c.fetchone()[0]
            if cnt > 1000 and not force_reload:
                print(f"[實價登錄] 本地已有 {cnt:,} 筆實價登錄成交紀錄，直接使用本機索引。")
                return

        print(f"[實價登錄] 正在解析並匯入全國買賣交易資料...")
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                total_inserted = 0
                for fname in z.namelist():
                    # 抓取各縣市的買賣主表: [a-z]_lvr_land_a.csv
                    if re.match(r"^[a-z]_lvr_land_a\.csv$", fname):
                        code = fname[0]
                        county = CODE_TO_COUNTY.get(code, "未知")
                        count = self._import_csv_content(z.read(fname), county)
                        total_inserted += count
                print(f"[實價登錄] 成功建立全國實價登錄索引，共 {total_inserted:,} 筆交易！")
        except Exception as e:
            print(f"[實價登錄] 解析 ZIP 失敗: {e}")

    def _import_csv_content(self, raw_bytes: bytes, county: str) -> int:
        """解析單一縣市 CSV 並寫入 SQLite"""
        text = raw_bytes.decode("utf-8", errors="ignore")
        reader = csv.reader(text.splitlines())
        rows_to_insert = []

        try:
            next(reader)  # 跳過中文表頭
            next(reader)  # 跳過英文表頭
        except StopIteration:
            return 0

        for row in reader:
            if len(row) < 22:
                continue

            town = row[0].strip()
            target_type = row[1].strip()
            address = row[2].strip()
            deal_date = row[7].strip()

            # 總價 (元)
            try:
                total_price = float(row[21].strip() or 0)
            except ValueError:
                total_price = 0.0

            # 單價 (元/平方公尺)
            unit_price_sqm = 0.0
            if len(row) > 22 and row[22].strip():
                try:
                    unit_price_sqm = float(row[22].strip())
                except ValueError:
                    unit_price_sqm = 0.0

            # 每坪單價 (1 平方公尺 = 0.3025 坪 -> 坪價 = sqm * 3.305785 / 10000 萬元)
            unit_price_ping = round((unit_price_sqm * 3.305785) / 10000.0, 2)

            # 建物移轉總面積 (平方公尺 -> 坪)
            building_area_ping = 0.0
            if len(row) > 15 and row[15].strip():
                try:
                    building_area_ping = round(float(row[15].strip()) * 0.3025, 2)
                except ValueError:
                    building_area_ping = 0.0

            building_type = row[11].strip() if len(row) > 11 else ""
            note = row[26].strip() if len(row) > 26 else ""

            # 提取路名
            road = self._extract_road(address)

            rows_to_insert.append((
                county, town, road, address, total_price,
                unit_price_sqm, unit_price_ping, building_area_ping,
                deal_date, building_type, target_type, note
            ))

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO transactions (
                    county, town, road, address, total_price,
                    unit_price_sqm, unit_price_ping, building_area,
                    deal_date, building_type, target_type, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)
            conn.commit()

        return len(rows_to_insert)

    @staticmethod
    def _extract_road(addr: str) -> str:
        """從門牌地址提取主要路/街/大道/段"""
        # 移除非路段前綴
        clean_addr = re.sub(r"^(.*?市|.*?縣)?(.*?區|.*?市|.*?鎮|.*?鄉)?", "", addr)
        m = re.search(r"([^,，\s號]+?(?:大道|[路街巷]|[\d一二三四五六七八九十]+段))", clean_addr)
        if m:
            return m.group(1).strip()
        # 地段名稱 (如德厚段)
        m_sec = re.search(r"([^,，\s號]+?段)", clean_addr)
        if m_sec:
            return m_sec.group(1).strip()
        return ""

    def find_nearby_transactions(self, court_item: Dict[str, Any], limit: int = 3) -> Dict[str, Any]:
        """
        為各筆法拍資料尋找附近的實價登錄成交行情
        """
        county = court_item.get("county", "").replace("台", "臺")
        town = court_item.get("town", "")
        raw_addr = court_item.get("address", "")
        court_price = court_item.get("price", 0.0)

        # 提取路名
        road = self._extract_road(raw_addr)
        sec = court_item.get("section", "")

        matches = []
        match_type = ""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 策略 1: 同縣市 + 同行政區 + 同路名 (最精確附近成交)
            if road:
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE county = ? AND (town = ? OR town = '') AND road LIKE ? AND total_price > 0
                    ORDER BY deal_date DESC LIMIT ?
                """, (county, town, f"%{road}%", limit))
                matches = [dict(r) for r in cursor.fetchall()]
                if matches:
                    match_type = f"同路段鄰近成交 ({road})"

            # 策略 2: 同縣市 + 同行政區 + 同地段 (如土地或無路名門牌)
            if not matches and sec:
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE county = ? AND town = ? AND address LIKE ? AND total_price > 0
                    ORDER BY deal_date DESC LIMIT ?
                """, (county, town, f"%{sec}%", limit))
                matches = [dict(r) for r in cursor.fetchall()]
                if matches:
                    match_type = f"同地段鄰近成交 ({sec})"

            # 策略 3: 同縣市 + 同行政區最新成交行情 (同生活圈行情參考)
            if not matches and town:
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE county = ? AND town = ? AND total_price > 0
                    ORDER BY deal_date DESC LIMIT ?
                """, (county, town, limit))
                matches = [dict(r) for r in cursor.fetchall()]
                if matches:
                    match_type = f"同行政區生活圈參考 ({town})"

            # 策略 4: 全縣市同類型參考
            if not matches:
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE county = ? AND total_price > 0
                    ORDER BY deal_date DESC LIMIT ?
                """, (county, limit))
                matches = [dict(r) for r in cursor.fetchall()]
                if matches:
                    match_type = f"同縣市成交參考"

        if matches:
            best = matches[0]
            lvr_price = best["total_price"]
            lvr_price_str = f"{int(lvr_price):,}"

            # 計算比對價差與折數
            if lvr_price > 0 and court_price > 0:
                discount = round((court_price / lvr_price) * 10, 1)
                diff = court_price - lvr_price
                diff_wan = round(diff / 10000.0, 1)
                if discount < 10:
                    diff_analysis = f"約實登 {discount} 折 (省約 {abs(diff_wan):,} 萬)"
                else:
                    diff_analysis = f"約實登 {discount} 折 (+{diff_wan:,} 萬)"
            else:
                diff_analysis = "價格比對中"

            deal_date_raw = str(best.get("deal_date", ""))
            if len(deal_date_raw) == 7:
                deal_date_str = f"{deal_date_raw[:3]}/{deal_date_raw[3:5]}"
            else:
                deal_date_str = deal_date_raw

            lvr_addr_full = f"{best['town']} {best['address']}".strip()
            return {
                "lvr_county": best["county"],
                "lvr_address": lvr_addr_full,
                "lvr_price": lvr_price,
                "lvr_price_str": lvr_price_str,
                "lvr_unit_price": f"{best['unit_price_ping']} 萬/坪" if best['unit_price_ping'] > 0 else "未記載",
                "lvr_deal_date": deal_date_str,
                "lvr_building_type": best.get("building_type", "房地買賣"),
                "lvr_target_type": best.get("target_type", ""),
                "match_type": match_type,
                "diff_analysis": diff_analysis,
                "lvr_map_url": self.make_lvr_map_url(lvr_addr_full, best["county"]),
                "all_matches": matches
            }
        else:
            return {
                "lvr_county": county,
                "lvr_address": f"{town} 尚無同季實登成交紀錄",
                "lvr_price": 0.0,
                "lvr_price_str": "無資料",
                "lvr_unit_price": "-",
                "lvr_deal_date": "-",
                "lvr_building_type": "-",
                "lvr_target_type": "-",
                "match_type": "未尋獲符合記錄",
                "diff_analysis": "-",
                "lvr_map_url": "",
                "all_matches": []
            }

    @staticmethod
    def clean_lvr_address(address: str, county: str = "") -> str:
        """清洗實價登錄地址，去除樓層、地下室等，保留純門牌或地段號字串"""
        if not address or "尚無" in address:
            return ""

        target = address.strip()
        # 全形數字/英文字元轉半形
        table = str.maketrans(
            "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        )
        target = target.translate(table)

        # 處理 '佳里區 臺南市佳里區延平路...' 或 '鹽水區 南港段479地號'
        m_town = re.match(r"^([^\s]+[區鄉鎮市])\s*(.*)$", target)
        if m_town:
            town_prefix = m_town.group(1)
            rest = m_town.group(2)
            if rest.startswith("臺南") or rest.startswith("台南") or rest.startswith("高雄"):
                target = rest
            else:
                target = f"{town_prefix}{rest}"

        target = target.replace("巿", "市").strip()

        # 補齊縣市名稱
        if county:
            clean_c = county.replace("台", "臺")
            if not target.startswith("臺南") and not target.startswith("台南") and not target.startswith("高雄"):
                target = clean_c + target

        # 移除括號備註
        target = re.sub(r"[\(（].*?[\)）]", "", target).strip()

        # 鎖定主門牌號碼，去除樓層、地下室等
        if "號" in target:
            target = re.sub(r"([0-9一二三四五六七八九十]+(?:之[0-9]+)?號)附[0-9]+.*$", r"\1", target)
            target = re.sub(r"([0-9]+號).*?[、,].*$", r"\1", target)
            target = re.sub(r"([0-9一二三四五六七八九十]+(?:之[0-9]+)?號)(?:[0-9一二三四五六七八九十]+樓|地下\w*層|頂層|頂樓|\d+F|\d+室|之\d+).*$", r"\1", target)
            target = re.sub(r"([0-9]+號).*$", r"\1", target)

        return target

    @classmethod
    def make_lvr_map_url(cls, address: str, county: str = "") -> str:
        """清洗實價登錄地址並產出 Google Maps 精準定位網址"""
        target = cls.clean_lvr_address(address, county)
        if not target:
            return ""
        encoded = urllib.parse.quote(target)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"


if __name__ == "__main__":
    matcher = LvrMatcher()
    matcher.download_and_import_season("114S1")
    # 測試比對
    test_court = {
        "county": "新北市",
        "town": "三重區",
        "section": "德厚段",
        "address": "新北市三重區中正北路27號11樓之2",
        "price": 14600000.0
    }
    res = matcher.find_nearby_transactions(test_court)
    print("比對結果:")
    print("實登縣市:", res["lvr_county"])
    print("實登住址:", res["lvr_address"])
    print("實登價格:", res["lvr_price_str"])
    print("比對分析:", res["diff_analysis"])
