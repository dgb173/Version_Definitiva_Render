# modules/other_feature_NUEVO.py (o como lo llames)
import streamlit as st
import time
import requests
import re
import math
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Importaciones de Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com" # Verifica que este sea el dominio correcto
SELENIUM_TIMEOUT_SECONDS_OF = 20
SELENIUM_POLL_FREQUENCY_OF = 0.2

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (ADAPTADAS) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s: # Formatos como "0.5/1", "-0/0.5"
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str)
            except ValueError: return None
            try: val2 = float(p2_str)
            except ValueError: return None
            # Lógica para manejar signos correctamente en formatos como "-0/0.5" o "0/-0.5"
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0: # ej: -0.5/1
                 val2 = -abs(val2) # Implícito -0.5 / -1, pero raro; más común es -0.5/-1
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0: # ej: -0/0.5 (debe ser 0 y -0.5)
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else: # Formatos como "0.5", "-1"
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    # Devuelve el string formateado (ej: "-0.5", "1", "0") o '-' si no es parseable/válido.
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None: # No se pudo parsear a número
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'

    if numeric_value == 0.0:
        return "0"
    
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1
    
    if mod_val == 0.0: abs_rounded = abs_num
    elif mod_val == 0.25: abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5: abs_rounded = abs_num
    elif mod_val == 0.75: abs_rounded = math.floor(abs_num) + 0.75
    else: 
        if mod_val < 0.25: abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75: abs_rounded = math.floor(abs_num) + 0.5
        else: abs_rounded = math.ceil(abs_num)

    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0: output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9 : output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9: output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or \
         abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9: output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else: output_str = f"{final_value_signed:.2f}" 

    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        if len(cells) < 12: return None
        league_id_hist_attr = row_element.get('name')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        home_tag = cells[home_idx].find('a'); home = home_tag.text.strip() if home_tag else cells[home_idx].text.strip()
        away_tag = cells[away_idx].find('a'); away = away_tag.text.strip() if away_tag else cells[away_idx].text.strip()
        score_cell_content = cells[score_idx].text.strip()
        score_span = cells[score_idx].find('span', class_=lambda x: x and score_class_selector in x)
        score_raw_text = score_span.text.strip() if score_span else score_cell_content
        score_m = re.match(r'(\d+-\d+)', score_raw_text); score_raw = score_m.group(1) if score_m else '?-?'
        score_fmt = score_raw.replace('-', '*') if score_raw != '?-?' else '?*?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text) 
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception: return None

@st.cache_resource
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter_req = HTTPAdapter(max_retries=retries_req)
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36"})
    return session

@st.cache_data(ttl=3600)
def fetch_soup_requests_of(path, max_tries=3, delay=1):
    session = get_requests_session_of(); url = f"{BASE_URL_OF}{path}"
    for attempt in range(1, max_tries + 1):
        try:
            resp = session.get(url, timeout=10); resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            if attempt == max_tries: return None
            time.sleep(delay * attempt)
    return None

@st.cache_data(ttl=3600) 
def get_rival_a_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v1") 
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if row.get("vs") == "1": 
            key_match_id_for_h2h_url = row.get("index") 
            if not key_match_id_for_h2h_url: continue
            onclicks = row.find_all("a", onclick=True) 
            if len(onclicks) > 1 and onclicks[1].get("onclick"): 
                rival_tag = onclicks[1]; rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()
                if rival_a_id_match and rival_a_name: return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int):
    soup_h2h_page = fetch_soup_requests_of(f"/match/h2h-{main_match_id}") 
    if not soup_h2h_page: return None, None, None
    table = soup_h2h_page.find("table", id="table_v2") 
    if not table: return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if row.get("vs") == "1": 
            match_id_of_rival_b_game = row.get("index") 
            if not match_id_of_rival_b_game: continue
            onclicks = row.find_all("a", onclick=True) 
            if len(onclicks) > 0 and onclicks[0].get("onclick"): 
                rival_tag = onclicks[0]; rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip() 
                if rival_b_id_match and rival_b_name: return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None

@st.cache_resource 
def get_selenium_driver_of():
    options = ChromeOptions(); options.add_argument("--headless"); options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage"); options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36")
    options.add_argument('--blink-settings=imagesEnabled=false'); options.add_argument("--window-size=1920,1080")
    try: return webdriver.Chrome(options=options)
    except WebDriverException as e: st.error(f"Error inicializando Selenium driver (OF): {e}"); return None

def get_h2h_details_for_original_logic_of(driver_instance, key_match_id_for_h2h_url, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not driver_instance: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)"}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id: return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})"}
    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        driver_instance.get(url_to_visit)
        WebDriverWait(driver_instance, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))
        time.sleep(0.7); soup_selenium = BeautifulSoup(driver_instance.page_source, "html.parser")
    except TimeoutException: return {"status": "error", "resultado": f"N/A (Timeout esperando table_v2 en {url_to_visit})"}
    except Exception as e: return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})"}
    if not soup_selenium: return {"status": "error", "resultado": f"N/A (Fallo soup Selenium H2H Original OF en {url_to_visit})"}
    table_to_search_h2h = soup_selenium.find("table", id="table_v2") 
    if not table_to_search_h2h: return {"status": "error", "resultado": f"N/A (Tabla v2 para H2H no encontrada en {url_to_visit})"}
    for row in table_to_search_h2h.find_all("tr", id=re.compile(r"tr2_\d+")): 
        links = row.find_all("a", onclick=True); 
        if len(links) < 2: continue
        h2h_row_home_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", "")); h2h_row_away_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
        h2h_row_home_id = h2h_row_home_id_m.group(1); h2h_row_away_id = h2h_row_away_id_m.group(1)
        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.find("span", class_="fscore_2") 
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1)
            tds = row.find_all("td"); handicap_raw = "N/A"; HANDICAP_TD_IDX = 11 
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]; d_o = cell.get("data-o") 
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"
            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(), "handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h, "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()}
    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en historial (table_v2) de la página de ref. ({key_match_id_for_h2h_url})."}

def get_team_league_info_from_script_of(soup):
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo ="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content); g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content); h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content); l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

def click_element_robust_of(driver, by, value, timeout=7):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.3)
        try: WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        except (ElementClickInterceptedException, TimeoutException): driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: return False

def extract_last_match_in_league_of(driver, table_css_id_str, main_team_name_in_table, league_id_filter_value, home_or_away_filter_css_selector, is_home_game_filter):
    pass

def get_main_match_odds_selenium_of(driver):
    return odds_info

def extract_standings_data_from_h2h_page_of(h2h_soup, target_team_name_exact):
    return data

def extract_final_score_of(soup):
    return '?*?', "?-?"

def extract_h2h_data_of(soup, main_home_team_name, main_away_team_name, current_league_id):
    return ah1, res1, res1_raw, ah6, res6, res6_raw

def extract_comparative_match_of(soup_for_team_history, table_id_of_team_to_search, team_name_to_find_match_for, opponent_name_to_search, current_league_id, is_home_table):
    return "-"

def extraer_handicaps_h2h(html_content):
    """
    Extrae los datos de handicap H2H de la tabla v3 en el HTML proporcionado.

    Busca la primera fila con vs="1" para "Local en Casa" y la primera con vs="0" para "General".
    Extrae las probabilidades de Asian Handicap (H, AH, A) y el resultado del AH.
    "AH Actual Partido" es un valor fijo de "-1.5".
    """
    data = {
        "AH H2H (Local en Casa)": "N/A",
        "Res H2H (Local en Casa)": "N/A",
        "AH Actual Partido": "-1.5",  # Valor fijo según la descripción del issue
        "AH H2H (General)": "N/A",
        "Res H2H (General)": "N/A"
    }

    if not html_content:
        return data

    soup = BeautifulSoup(html_content, "html.parser")
    table_v3 = soup.find("table", id="table_v3")

    if not table_v3:
        return data

    found_local_en_casa = False
    found_general = False

    rows = table_v3.find_all("tr", id=lambda x: x and x.startswith("tr3_"))

    for row in rows:
        if found_local_en_casa and found_general:
            break

        vs_attr = row.get("vs")

        tds = row.find_all("td")
        if len(tds) < 14: # Need at least 14 cells for indices 10, 11, 12, 13
            continue

        # Common extraction logic for AH values
        def get_value(cell_index, cell_list):
            raw_val = cell_list[cell_index].get("data-o")
            if raw_val is None or raw_val.strip() == "" or raw_val.strip() == "-":
                text_val = cell_list[cell_index].text.strip()
                return text_val if text_val and text_val != "-" else "N/A"
            return raw_val.strip()

        ah_h = get_value(10, tds)
        ah_line = get_value(11, tds)
        ah_a = get_value(12, tds)

        res_ah_span = tds[13].find("span")
        res_ah = res_ah_span.text.strip() if res_ah_span and res_ah_span.text.strip() and res_ah_span.text.strip() != "-" else "N/A"

        if vs_attr == "1" and not found_local_en_casa:
            data["AH H2H (Local en Casa)"] = f"{ah_h} / {ah_line} / {ah_a}"
            data["Res H2H (Local en Casa)"] = res_ah
            found_local_en_casa = True
        elif vs_attr == "0" and not found_general:
            data["AH H2H (General)"] = f"{ah_h} / {ah_line} / {ah_a}"
            data["Res H2H (General)"] = res_ah
            found_general = True

    return data

if __name__ == "__main__":
    # This assumes the script is run from the 'funciones' directory.
    # Adjust path if running from repository root or elsewhere for testing.
    html_example_path = "../otras_carpetas/BODYDELAWEB.txt"

    # For local testing, you might need to ensure BeautifulSoup is available here
    # if not already imported globally in the file.
    # from bs4 import BeautifulSoup # Already imported at module level

    print(f"Attempting to load HTML from: {html_example_path}")
    try:
        with open(html_example_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print("HTML content loaded successfully.")

        # Ensure the function `extraer_handicaps_h2h` is defined before this block
        # or imported if it's in another file.
        print("Calling extraer_handicaps_h2h...")
        extracted_data = extraer_handicaps_h2h(content)

        # Import json for pretty printing the dictionary
        import json
        print("\nExtracted Data:")
        print(json.dumps(extracted_data, indent=4, ensure_ascii=False))
        print("\nScript execution finished.")

    except FileNotFoundError:
        print(f"Error: File not found at {html_example_path}. Please ensure the path is correct.")
        print("If running from repository root, path might be 'otras_carpetas/BODYDELAWEB.txt'")
    except NameError as ne:
        print(f"NameError: {ne}. Ensure 'extraer_handicaps_h2h' is defined or imported.")
    except Exception as e:
        print(f"An error occurred during the test execution: {e}")
