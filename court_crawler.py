# -*- coding: utf-8 -*-
"""
司法院法拍屋資訊爬蟲模組
官方網址: https://aomp109.judicial.gov.tw/judbp/wkw/WHD1A02.htm
"""

import os
import urllib.request
import urllib.parse
import http.cookiejar
import re
import json
import time
from typing import List, Dict, Any, Optional


class CourtAuctionCrawler:
    BASE_URL = "https://aomp109.judicial.gov.tw/judbp"
    V2_URL = f"{BASE_URL}/wkw/WHD1A02/V2.htm"
    QUERY_URL = f"{BASE_URL}/wkw/WHD1A02/QUERY.htm"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.V2_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _get_tokens(self) -> tuple[str, str]:
        """從 V2.htm 取得 Session Cookie 與 CSRF / Token"""
        req = urllib.request.Request(self.V2_URL, headers=self.headers)
        with self.opener.open(req, timeout=self.timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        csrf_m = re.search(r'name=["\']_csrf["\'] value=["\']([^"\']+)["\']', html)
        token_m = re.search(r'name=["\']token["\'] value=["\']([^"\']+)["\']', html)

        csrf = csrf_m.group(1) if csrf_m else ""
        token = token_m.group(1) if token_m else ""
        return csrf, token

    def fetch_auctions(
        self,
        court: str = "",
        county: str = "",
        proptype: str = "C52",  # C52: 房屋, C51: 土地, C51C52: 房地全部
        saletype: str = "",    # 拍賣程序: 1=第一拍, 2=第二拍, 3=第三拍, 4=第四拍, ''=不限
        max_pages: int = 5,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        抓取司法院法拍公告清單
        """
        target_name = court or county or "全國"
        print(f"[法院爬蟲] 正在連接司法院拍賣公告系統 (目標: {target_name})...")
        try:
            csrf, token = self._get_tokens()
        except Exception as e:
            print(f"[法院爬蟲] 取得 Session 失敗: {e}")
            return []

        all_items: List[Dict[str, Any]] = []

        for page in range(1, max_pages + 1):
            print(f"[法院爬蟲] 正在查詢第 {page}/{max_pages} 頁法拍資料 (每頁 {page_size} 筆)...")
            payload = {
                "gov": "",
                "crtnm": "",
                "court": court,
                "county": county,
                "town": "",
                "proptype": proptype,
                "saletype": saletype,
                "keyword": "",
                "saledate1": "",
                "saledate2": "",
                "minprice1": "",
                "minprice2": "",
                "saleno": "",
                "crmyy": "",
                "crmid": "",
                "crmno": "",
                "dpt": "",
                "comm_yn": "",
                "stopitem": "",
                "sec": "",
                "rrange": "",
                "area1": "",
                "area2": "",
                "debtor": "",
                "checkyn": "",
                "emptyyn": "",
                "ttitle": "",
                "sorted_column": "A.SALEDATE,A.CRMYY,A.CRMID,A.CRMNO,A.SALENO,A.ROWID",
                "sorted_type": "ASC",
                "_ORDER_BY": "",
                "pageNum": str(page),
                "pageSize": str(page_size),
                "token": token,
                "_csrf": csrf,
            }

            data_encoded = urllib.parse.urlencode(payload).encode("utf-8")
            post_headers = dict(self.headers)
            post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

            req_post = urllib.request.Request(self.QUERY_URL, data=data_encoded, headers=post_headers)

            try:
                with self.opener.open(req_post, timeout=self.timeout) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            except Exception as e:
                print(f"[法院爬蟲] 第 {page} 頁請求失敗: {e}")
                break

            records = resp_data.get("data", [])
            if not records:
                print(f"[法院爬蟲] 無更多資料或已達最後一頁。")
                break

            for rec in records:
                parsed = self._parse_record(rec)
                if parsed:
                    all_items.append(parsed)

            total_pages = resp_data.get("pageInfo", {}).get("totalPage", page)
            if page >= total_pages:
                break

            time.sleep(1.0)  # 禮貌防禦，避免過度請求

        print(f"[法院爬蟲] 成功擷取 {len(all_items)} 筆法拍物件！")
        return all_items

    def fetch_tainan_kaohsiung_auctions(
        self,
        max_pages_per_court: int = 2,
        page_size: int = 20,
        proptype: str = "C52"
    ) -> List[Dict[str, Any]]:
        """
        專屬抓取直轄市「臺南市」與「高雄市」之法拍屋資料
        涵蓋: 臺灣臺南地方法院(TND)、臺灣高雄地方法院(KSD)、臺灣橋頭地方法院(CTD)
        """
        courts = [
            ("TND", "臺灣臺南地方法院"),
            ("KSD", "臺灣高雄地方法院"),
            ("CTD", "臺灣橋頭地方法院(高雄北區)")
        ]
        all_results = []
        for court_code, court_name in courts:
            print(f"\n[直轄市專案] 正在抓取【{court_name}】最新法拍公告...")
            items = self.fetch_auctions(
                court=court_code,
                proptype=proptype,
                max_pages=max_pages_per_court,
                page_size=page_size
            )
            for it in items:
                # 嚴格篩選僅保留臺南市與高雄市
                clean_c = it["county"].replace("台", "臺")
                if clean_c in ["臺南市", "高雄市"]:
                    it["county"] = clean_c
                    all_results.append(it)

        # 依案號與住址去重
        unique_results = []
        seen = set()
        for r in all_results:
            key = (r["county"], r["address"], r["case_no"])
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        print(f"\n[直轄市專案] 臺南市與高雄市法拍資料抓取完成，共 {len(unique_results)} 筆！")
        return unique_results

    def _parse_record(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """清理與規範化單筆法拍資料"""
        county = (raw.get("hsimun") or "").strip()
        town = (raw.get("ctmd") or "").strip()
        address = (raw.get("budadd") or "").strip()
        sec = (raw.get("sec") or "").strip()

        # 如果住址為空但有土地坐落
        if not address:
            address = f"{county}{town}{sec}" + (raw.get("landno") or "")

        # 規範化縣市名稱 (例如 台北市 -> 臺北市)
        clean_county = county.replace("台", "臺")

        # 拍賣底價
        summinprc = raw.get("summinprc") or 0
        try:
            price_val = float(summinprc)
        except (ValueError, TypeError):
            price_val = 0.0

        # 格式化價格 (新台幣元)
        price_str = raw.get("summinprcstr") or f"{int(price_val):,}"

        # 拍次
        saleno = str(raw.get("saleno") or "")
        sale_round_str = f"第{saleno}拍" if saleno else "拍次未標明"

        # 拍賣日期 (民國年月日)
        saledate = str(raw.get("saledate1") or raw.get("saledate") or "")
        if len(saledate) == 7:  # e.g. 1131022 -> 113/10/22
            date_formatted = f"{saledate[:3]}/{saledate[3:5]}/{saledate[5:]}"
        else:
            date_formatted = saledate

        # 案號
        crmyy = raw.get("crmyy") or ""
        crmid = raw.get("crmid") or ""
        crmno = raw.get("crmno") or ""
        case_no = f"{crmyy}年度{crmid}字第{crmno}號" if crmyy else (raw.get("crm") or "")

        # 點交情形
        checkyn = (raw.get("checkynstr") or "").strip()
        if not checkyn:
            checkyn = "點交" if raw.get("checkyn") == "Y" else "不點交"

        filenm = (raw.get("filenm") or "").strip()
        doc_url = f"{self.BASE_URL}/wkw/WHD1A02/DO_VIEWPDF.htm?filenm={urllib.parse.quote(filenm)}" if filenm else ""

        return {
            "county": clean_county or county,
            "town": town,
            "section": sec,
            "address": address,
            "price": price_val,
            "price_str": price_str,
            "sale_round": sale_round_str,
            "sale_date": date_formatted,
            "court_name": raw.get("crtnm") or "",
            "case_no": case_no,
            "check_status": checkyn,
            "building_area": raw.get("btotal") or 0,
            "raw_id": raw.get("rowid") or "",
            "doc_filenm": filenm,
            "doc_url": doc_url,
            "google_map_url": self.make_google_map_url(address, clean_county or county, town),
        }

    @staticmethod
    def make_google_map_url(address: str, county: str = "", town: str = "") -> str:
        """
        清洗法拍地址，去除樓層、室、地下室、附號與備註等，使 Google 地圖能精準掉落大紅圖釘 (Pin Marker)
        """
        if not address:
            target = f"{county}{town}"
        else:
            target = address.replace("巿", "市").strip()
            # 清除前綴 (例如: 未辦保存登記建物門牌:、未保存登記建物門牌: 等)
            target = re.sub(r'^(?:未[辦辦]?保存登記建物)?(?:門牌)?[:：]?', '', target).strip()
            # 移除括號備註 (例如 (未保存登記部分)、(未辦保存登記建物))
            target = re.sub(r'[\(（].*?[\)）]', '', target).strip()
            # 補齊縣市
            if county:
                clean_c = county.replace("台", "臺")
                if not target.startswith("臺南") and not target.startswith("台南") and not target.startswith("高雄"):
                    target = clean_c + target

            # 處理附號: 2號附10 -> 2號
            target = re.sub(r'([0-9一二三四五六七八九十]+(?:之[0-9]+)?號)附[0-9]+.*$', r'\1', target)
            # 去除並列多門牌: 577號12樓之1、579號12樓之1 -> 577號
            target = re.sub(r'([0-9]+號).*?[、,].*$', r'\1', target)
            target = re.sub(r'([0-9]+(?:、[0-9]+)+號).*$', lambda m: m.group(1).split('、')[0] + '號', target)
            # 鎖定主門牌號碼，去除後方之樓層、地下室、頂樓、頂層、室、未保存登記等後綴
            target = re.sub(r'([0-9一二三四五六七八九十]+(?:之[0-9]+)?號)(?:[0-9一二三四五六七八九十]+樓|地下\w*層|頂層|頂樓|\d+F|\d+室|之\d+|未[辦辦]?保存登記.*).*$', r'\1', target)
            # 去除殘留頓號、逗號或贅詞
            target = re.sub(r'([0-9]+號).*$', r'\1', target)

        encoded = urllib.parse.quote(target)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"

    def download_notice_pdf(self, filenm: str, save_path: str, csrf: str = "", token: str = "") -> bool:
        """
        透過 Session 與 VIEW.htm 驗證下載司法院公告 PDF 至本機
        """
        if not filenm:
            return False

        if not csrf or not token:
            csrf, token = self._get_tokens()

        try:
            # 1. 呼叫 VIEW.htm 取得存取權限
            view_url = f"{self.BASE_URL}/wkw/WHD1A02/VIEW.htm"
            post_headers = dict(self.headers)
            post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            view_payload = urllib.parse.urlencode({"filenm": filenm, "token": token, "_csrf": csrf}).encode("utf-8")
            req_v = urllib.request.Request(view_url, data=view_payload, headers=post_headers)

            with self.opener.open(req_v, timeout=self.timeout) as r_v:
                res_v = json.loads(r_v.read().decode("utf-8", errors="ignore"))

            if res_v.get("status") != "SUCCESS":
                return False

            # 2. 下載 PDF 內容
            pdf_url = f"{self.BASE_URL}/wkw/WHD1A02/DO_VIEWPDF.htm?filenm={urllib.parse.quote(filenm)}"
            req_pdf = urllib.request.Request(pdf_url, headers=self.headers)
            with self.opener.open(req_pdf, timeout=self.timeout) as r_pdf:
                content = r_pdf.read()

            if len(content) > 500 and content.startswith(b"%PDF"):
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                with open(save_path, "wb") as f_out:
                    f_out.write(content)
                return True
        except Exception as e:
            print(f"[法院爬蟲] 下載公告 PDF 失敗 ({filenm}): {e}")

        return False


if __name__ == "__main__":
    crawler = CourtAuctionCrawler()
    results = crawler.fetch_auctions(max_pages=1, page_size=5)
    for r in results:
        print(f"[{r['county']}] {r['address']} | 底價: {r['price_str']} 元 ({r['sale_round']})")
