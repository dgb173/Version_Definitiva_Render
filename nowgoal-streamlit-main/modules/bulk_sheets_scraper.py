import math
import os
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple

import gspread
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Helper functions for AH parsing ---

def parse_ah_to_number(ah_line_str: str):
    if not isinstance(ah_line_str, str):
        return None
    s = ah_line_str.strip().replace(" ", "")
    if not s or s in ["-", "?"]:
        return None
    original_minus = ah_line_str.strip().startswith("-")
    try:
        if "/" in s:
            parts = s.split("/")
            if len(parts) != 2:
                return None
            p1_str, p2_str = parts[0], parts[1]
            try:
                val1 = float(p1_str)
            except ValueError:
                return None
            try:
                val2 = float(p2_str)
            except ValueError:
                return None
            if val1 < 0 and not p2_str.startswith("-") and val2 > 0:
                val2 = -abs(val2)
            elif original_minus and val1 == 0.0 and (p1_str == "0" or p1_str == "-0") and not p2_str.startswith("-") and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string(ah_line_str: str):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ["-", "?"]:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else "-"
    numeric_value = parse_ah_to_number(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if isinstance(ah_line_str, str) else "-"
    if numeric_value == 0.0:
        return "0"
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    parte_entera = math.floor(abs_num)
    parte_decimal_original = round(abs_num - parte_entera, 4)
    nueva_parte_decimal = parte_decimal_original
    epsilon = 1e-9
    if abs(parte_decimal_original - 0.25) < epsilon:
        nueva_parte_decimal = 0.5
    elif abs(parte_decimal_original - 0.75) < epsilon:
        nueva_parte_decimal = 0.5
    resultado_num_redondeado = parte_entera + nueva_parte_decimal
    final_value_signed = sign * resultado_num_redondeado
    if final_value_signed == 0.0:
        return "0"
    if abs(final_value_signed - round(final_value_signed, 0)) < epsilon:
        return str(int(round(final_value_signed, 0)))
    return f"{final_value_signed:.1f}"

# --- Selenium helpers ---

def get_chrome_options() -> Options:
    chrome_opts = Options()
    chrome_opts.add_argument("--headless")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/108.0.0.0 Safari/537.36")
    chrome_opts.add_argument("--window-size=1280x720")
    prefs = {"profile.managed_default_content_settings.images": 2,
             "profile.default_content_setting_values.notifications": 2}
    chrome_opts.add_experimental_option("prefs", prefs)
    return chrome_opts

# --- Match extraction ---

SELENIUM_TIMEOUT = 120
WORKER_START_DELAY = 0.5


def extract_match_worker(driver_instance: webdriver.Chrome, mid: int) -> Tuple[int, str, List[str], float | None]:
    url = f"https://live16.nowgoal25.com/match/h2h-{mid}"
    time.sleep(WORKER_START_DELAY)
    try:
        driver_instance.get(url)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#table_v3")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.crumbs")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "body[errorpage]")),
            )
        )
        html = driver_instance.page_source
        if "match not found" in html.lower() or "errorpage" in html.lower():
            return mid, "not_found", [], None
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return mid, "load_error", [], None

    league_name = "League N/A"
    league_tag = soup.select_one("div.crumbs a[href*='/leagueinfo/']")
    if league_tag:
        league_name = league_tag.text.strip()

    final_score = "?*?"
    score_divs = soup.select("#mScore .end .score")
    if len(score_divs) == 2:
        hs, aws = score_divs[0].text.strip(), score_divs[1].text.strip()
        if hs.isdigit() and aws.isdigit():
            final_score = f"{hs}*{aws}"

    ah_row = soup.select_one('#liveCompareDiv #tr_o_1_8[name="earlyOdds"]')
    if not ah_row:
        ah_row = soup.select_one('#tr_o_1_8[name="earlyOdds"]')
    ah_act = "?"
    if ah_row:
        cells = ah_row.find_all('td')
        if len(cells) > 3:
            ah_act = format_ah_as_decimal_string(cells[3].text.strip())

    result_row = ["-", ah_act, "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", final_score, "?", league_name, str(mid)]
    ah_num = parse_ah_to_number(ah_act)
    return mid, "ok", result_row, ah_num


def worker_task(mid_param: int):
    driver = None
    try:
        opts = get_chrome_options()
        driver = webdriver.Chrome(options=opts)
        mid, status, row, ah_num = extract_match_worker(driver, mid_param)
        return mid, status, row, ah_num
    except Exception as e:
        return mid_param, "load_error", [], None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

# --- Google Sheets upload ---

BATCH_SIZE = 100
API_PAUSE = 0.5
RETRY_DELAY_GSPREAD = 15


def upload_data_to_sheet(worksheet_name: str, data_rows: List[List[str]], columns_list: List[str], sheet_handle, batch_size: int = BATCH_SIZE) -> bool:
    print(f"\n--- Iniciando subida para '{worksheet_name}' ({len(data_rows)} filas) ---")
    if not data_rows:
        print(f"  ✅ No hay datos nuevos para subir a '{worksheet_name}'.")
        return True
    try:
        df = data_rows
        ws = None
        try:
            ws = sheet_handle.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet_handle.add_worksheet(title=worksheet_name, rows=max(len(df) + 100, 200), cols=len(columns_list) + 5)
            ws.update('A1', [columns_list], value_input_option='USER_ENTERED')
        if not ws:
            return False
        start_row = len(ws.get_all_values()) + 1
        num_batches = math.ceil(len(df) / batch_size)
        for i in range(num_batches):
            batch = df[i * batch_size : (i + 1) * batch_size]
            range_start = start_row + i * batch_size
            end_col_letter = gspread.utils.rowcol_to_a1(1, len(columns_list)).replace('1','')
            full_range = f"A{range_start}:{end_col_letter}{range_start + len(batch) - 1}"
            ws.update(full_range, batch, value_input_option='USER_ENTERED')
            time.sleep(API_PAUSE)
        return True
    except Exception as e:
        print(f"Error subiendo a {worksheet_name}: {e}")
        return False

# --- Main processing function ---

def process_ranges(credentials_path: str, sheet_name: str, sheet_neg: str, sheet_pos: str, ranges: List[Dict[str, int]], max_workers: int = 3):
    gc = gspread.service_account(filename=credentials_path)
    sh = gc.open(sheet_name)
    columns = [
        "AH_H2H_V","AH_Act","Res_H2H_V","AH_L_H","Res_L_H",
        "AH_V_A","Res_V_A","AH_H2H_G","Res_H2H_G",
        "L_vs_UV_A","V_vs_UL_H","Stats_L","Stats_V",
        "Fin","G_i", "League", "match_id"
    ]
    for r_idx, r in enumerate(ranges):
        start_id = r.get('start_id')
        end_id = r.get('end_id')
        label = r.get('label', f'Rango {r_idx+1}')
        ids = list(range(start_id, end_id - 1, -1)) if start_id >= end_id else list(range(start_id, end_id + 1))
        rows_neg_zero: List[List[str]] = []
        rows_pos: List[List[str]] = []
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for mid in ids:
                future = executor.submit(worker_task, mid)
                futures[future] = mid
            for f in as_completed(futures):
                mid, status, row, ah_num = f.result()
                if status == 'ok':
                    if ah_num is None or ah_num <= 0:
                        rows_neg_zero.append(row)
                    else:
                        rows_pos.append(row)
        upload_data_to_sheet(sheet_neg, rows_neg_zero, columns, sh)
        upload_data_to_sheet(sheet_pos, rows_pos, columns, sh)

