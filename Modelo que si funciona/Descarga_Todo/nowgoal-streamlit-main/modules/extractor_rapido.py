# modules/extractor_rapido.py
import asyncio
import streamlit as st # Mantener por ahora para las funciones de cache, se evaluará si se pueden reemplazar.
import time
import requests
import re
import math
import pandas as pd
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Importaciones de Selenium (solo si son estrictamente necesarias tras optimización)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, NoSuchElementException

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
SELENIUM_TIMEOUT_SECONDS_OF = 15 # Reducido para optimización
SELENIUM_POLL_FREQUENCY_OF = 0.2
PLACEHOLDER_NODATA = "*(No disponible)*"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (Replicadas de datos.py) ---
def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str): return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']: return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:
            parts = s.split('/')
            if len(parts) != 2: return None
            p1_str, p2_str = parts[0], parts[1]
            try: val1 = float(p1_str)
            except ValueError: return None
            try: val2 = float(p2_str)
            except ValueError: return None
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except ValueError:
        return None

def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-','?'] else '-'

    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:
        return ah_line_str.strip() if ah_line_str.strip() in ['-','?'] else '-'

    if numeric_value == 0.0: return "0"

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

    if for_sheets: # Esta parte podría eliminarse si no se usa para Google Sheets directamente
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    # Replicada de datos.py, ajustada para devolver match_id consistentemente
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
        score_fmt = score_raw.replace('-', ':') if score_raw != '?-?' else '?:?'
        ah_line_raw_text = cells[ah_idx].text.strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw_text)
        match_id = row_element.get('index') # Este es el ID del partido histórico
        if not home or not away: return None
        return {'home': home, 'away': away, 'score': score_fmt, 'score_raw': score_raw,
                'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw_text,
                'match_id': match_id, # Usar 'match_id' consistentemente
                'vs': row_element.get('vs'),
                'league_id_hist': league_id_hist_attr}
    except Exception:
        # Considerar logging del error si es necesario
        return None

# --- SESIÓN Y FETCHING (Replicado y optimizado) ---
@st.cache_resource # Mantener cache_resource para la sesión
def get_requests_session_of():
    session = requests.Session()
    retries_req = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]) # backoff_factor reducido
    adapter_req = HTTPAdapter(max_retries=retries_req, pool_connections=50, pool_maxsize=50) # Aumentar pool
    session.mount("https://", adapter_req); session.mount("http://", adapter_req)
    session.headers.update({"User-Agent": USER_AGENT})
    return session

@st.cache_data(ttl=1800) # Reducir TTL si los datos cambian más frecuentemente, o ajustar según necesidad
async def fetch_soup_async(path, session):
    url = f"{BASE_URL_OF}{path}"
    try:
        # Usar un cliente HTTP asíncrono como httpx si se quieren paralelizar estas llamadas
        # Por ahora, se mantiene síncrono dentro de una función async para futura integración
        # Para un verdadero beneficio async, la llamada session.get() debería ser async.
        # Esto requeriría cambiar get_requests_session_of para devolver un cliente async.
        # Por simplicidad inicial, se deja síncrono pero la función es async.
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, session.get, url, {"timeout": 8}) # Timeout reducido
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml") # Usar lxml para parseo más rápido
    except requests.RequestException as e:
        # Considerar logging
        # print(f"Error fetching {url}: {e}")
        return None

# --- FUNCIONES DE EXTRACCIÓN DE DATOS (Reimplementadas y optimizadas) ---

@st.cache_data(ttl=3600)
def get_team_league_info_from_script_of(soup: BeautifulSoup):
    # Replicada de datos.py
    home_id, away_id, league_id, home_name, away_name, league_name = (None,)*3 + ("N/A",)*3
    if not soup: return home_id, away_id, league_id, home_name, away_name, league_name
    script_tag = soup.find("script", string=re.compile(r"var\s*_matchInfo\s*="))
    if script_tag and script_tag.string:
        script_content = script_tag.string
        h_id_m = re.search(r"hId:\s*parseInt\('(\d+)'\)", script_content);
        g_id_m = re.search(r"gId:\s*parseInt\('(\d+)'\)", script_content)
        sclass_id_m = re.search(r"sclassId:\s*parseInt\('(\d+)'\)", script_content);
        h_name_m = re.search(r"hName:\s*'([^']*)'", script_content)
        g_name_m = re.search(r"gName:\s*'([^']*)'", script_content);
        l_name_m = re.search(r"lName:\s*'([^']*)'", script_content)
        if h_id_m: home_id = h_id_m.group(1)
        if g_id_m: away_id = g_id_m.group(1)
        if sclass_id_m: league_id = sclass_id_m.group(1)
        if h_name_m: home_name = h_name_m.group(1).replace("\\'", "'")
        if g_name_m: away_name = g_name_m.group(1).replace("\\'", "'")
        if l_name_m: league_name = l_name_m.group(1).replace("\\'", "'")
    return home_id, away_id, league_id, home_name, away_name, league_name

@st.cache_data(ttl=3600)
def extract_standings_data_from_h2h_page_of(h2h_soup: BeautifulSoup, target_team_name_exact: str):
    # Replicada de datos.py, asegurar selectores eficientes
    data = {
        "name": target_team_name_exact, "ranking": "N/A",
        "total_pj": "N/A", "total_v": "N/A", "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A",
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A", "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A",
        "specific_type": "N/A"
    }
    if not h2h_soup or not target_team_name_exact: return data

    standings_section = h2h_soup.select_one("div#porletP4") # Selector CSS directo
    if not standings_section: return data

    team_table_soup = None
    is_home_table_type = False

    home_div = standings_section.select_one("div.home-div")
    if home_div:
        header_tr = home_div.select_one("tr.team-home a")
        if header_tr and target_team_name_exact.lower() in header_tr.get_text(strip=True).lower():
            team_table_soup = home_div.select_one("table.team-table-home")
            is_home_table_type = True
            data["specific_type"] = "Est. como Local (en Liga)"

    if not team_table_soup:
        guest_div = standings_section.select_one("div.guest-div")
        if guest_div:
            header_tr = guest_div.select_one("tr.team-guest a")
            if header_tr and target_team_name_exact.lower() in header_tr.get_text(strip=True).lower():
                team_table_soup = guest_div.select_one("table.team-table-guest")
                is_home_table_type = False
                data["specific_type"] = "Est. como Visitante (en Liga)"

    if not team_table_soup: return data

    header_link = team_table_soup.select_one("tr[class*=team-] a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        name_match = re.search(r"]\s*(.*)", full_text)
        rank_match = re.search(r"\[(?:[^\]]+-)?(\d+)\]", full_text)
        if name_match: data["name"] = name_match.group(1).strip()
        if rank_match: data["ranking"] = rank_match.group(1)

    in_ft_section = False
    for row in team_table_soup.select("tr[align=center]"): # Selector más específico
        th_header = row.select_one("th")
        if th_header:
            th_text = th_header.get_text(strip=True)
            if "FT" in th_text:
                in_ft_section = True
                continue
            elif "HT" in th_text:
                in_ft_section = False
                break

        if in_ft_section:
            cells = row.select("td") # td hijos directos
            if not cells or len(cells) < 7: continue

            row_type_text_container = cells[0].select_one("span") if cells[0].select_one("span") else cells[0]
            row_type_text = row_type_text_container.get_text(strip=True)

            stats_values = [cell.get_text(strip=True) or "N/A" for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats_values[:6]

            if row_type_text == "Total":
                data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            elif (row_type_text == "Home" and is_home_table_type) or \
                 (row_type_text == "Away" and not is_home_table_type):
                data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data

@st.cache_data(ttl=3600)
def get_rival_a_for_original_h2h_of(main_match_id: int, session_requests): # Pasar session
    # path = f"/match/h2h-{main_match_id}" # No es async todavía
    # soup_h2h_page = await fetch_soup_async(path, session_requests) # Necesitaría ser llamada con await
    # Por ahora, usamos la versión síncrona de fetch_soup_requests_of
    soup_h2h_page = fetch_soup_requests_sync(f"/match/h2h-{main_match_id}", session_requests)

    if not soup_h2h_page: return None, None, None, None
    table = soup_h2h_page.select_one("table#table_v1")
    if not table: return None, None, None, None
    for row in table.select("tr[id^=tr1_]"): # Selector CSS
        if row.get("vs") == "1":
            key_match_id_for_h2h_url = row.get("index")
            if not key_match_id_for_h2h_url: continue
            # onclicks = row.find_all("a", onclick=True) # Mantenido por complejidad del selector
            onclicks = row.select("a[onclick]")
            if len(onclicks) > 1 and onclicks[1].get("onclick"):
                rival_tag = onclicks[1]; rival_a_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_a_name = rival_tag.text.strip()
                if rival_a_id_match and rival_a_name:
                    # Devolver también el soup de esta página para evitar refech
                    # rival_page_path = f"/match/h2h-{key_match_id_for_h2h_url}"
                    # rival_soup = await fetch_soup_async(rival_page_path, session_requests)
                    # rival_soup = fetch_soup_requests_sync(rival_page_path, session_requests)
                    # Devolvemos solo los IDs, la página del rival se cargará en get_h2h_details si es necesario
                    return key_match_id_for_h2h_url, rival_a_id_match.group(1), rival_a_name
    return None, None, None

@st.cache_data(ttl=3600)
def get_rival_b_for_original_h2h_of(main_match_id: int, session_requests):
    # soup_h2h_page = await fetch_soup_async(f"/match/h2h-{main_match_id}", session_requests)
    soup_h2h_page = fetch_soup_requests_sync(f"/match/h2h-{main_match_id}", session_requests)
    if not soup_h2h_page: return None, None, None, None
    table = soup_h2h_page.select_one("table#table_v2")
    if not table: return None, None, None, None
    for row in table.select("tr[id^=tr2_]"):
        if row.get("vs") == "1":
            match_id_of_rival_b_game = row.get("index")
            if not match_id_of_rival_b_game: continue
            # onclicks = row.find_all("a", onclick=True)
            onclicks = row.select("a[onclick]")
            if len(onclicks) > 0 and onclicks[0].get("onclick"): # El rival B es el primer link (local)
                rival_tag = onclicks[0]; rival_b_id_match = re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))
                rival_b_name = rival_tag.text.strip()
                if rival_b_id_match and rival_b_name:
                    # rival_page_path = f"/match/h2h-{match_id_of_rival_b_game}"
                    # rival_soup = await fetch_soup_async(rival_page_path, session_requests)
                    # rival_soup = fetch_soup_requests_sync(rival_page_path, session_requests)
                    return match_id_of_rival_b_game, rival_b_id_match.group(1), rival_b_name
    return None, None, None


@st.cache_data(ttl=7200)
def get_match_progression_stats_data(match_id: str, session_requests) -> pd.DataFrame | None:
    # Replicada de datos.py, usando la sesión pasada
    base_url_live = f"{BASE_URL_OF}/match/live-" # Asegurar que BASE_URL_OF es el correcto
    full_url = f"{base_url_live}{match_id}"
    headers = { # Headers simplificados, User-Agent ya está en la sesión
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Encoding": "gzip, deflate, br", "Accept-Language": "en-US,en;q=0.9", "DNT": "1",
        "Connection": "keep-alive", "Upgrade-Insecure-Requests": "1",
    }
    stat_titles_of_interest = {
        "Shots": {"Home": "-", "Away": "-"}, "Shots on Goal": {"Home": "-", "Away": "-"},
        "Attacks": {"Home": "-", "Away": "-"}, "Dangerous Attacks": {"Home": "-", "Away": "-"},
    }
    try:
        # response = await asyncio.get_event_loop().run_in_executor(None, session_requests.get, full_url, {"headers": headers, "timeout":10})
        response = session_requests.get(full_url, headers=headers, timeout=10)
        response.raise_for_status()
        html_content = response.text
        soup = BeautifulSoup(html_content, 'lxml') # lxml
        team_tech_div = soup.select_one('div#teamTechDiv_detail') # Selector CSS
        if team_tech_div:
            stat_list = team_tech_div.select_one('ul.stat') # Selector CSS
            if stat_list:
                for li in stat_list.select('li'): # Selector CSS
                    title_span = li.select_one('span.stat-title')
                    if title_span:
                        stat_title = title_span.get_text(strip=True)
                        if stat_title in stat_titles_of_interest:
                            values = li.select('span.stat-c') # Selector CSS
                            if len(values) == 2:
                                stat_titles_of_interest[stat_title]["Home"] = values[0].get_text(strip=True)
                                stat_titles_of_interest[stat_title]["Away"] = values[1].get_text(strip=True)
    except Exception: # Considerar logging
        return None
    table_rows = [{"Estadistica_EN": name, "Casa": vals['Home'], "Fuera": vals['Away']} for name, vals in stat_titles_of_interest.items()]
    df = pd.DataFrame(table_rows)
    return df.set_index("Estadistica_EN") if not df.empty else df


@st.cache_data(ttl=3600)
def extract_final_score_of(soup: BeautifulSoup):
    # Replicada de datos.py
    if not soup: return '?:?', "?-?"
    try:
        score_divs = soup.select('#mScore .end .score') # Selector CSS
        if len(score_divs) == 2:
            hs = score_divs[0].text.strip(); aws = score_divs[1].text.strip()
            if hs.isdigit() and aws.isdigit(): return f"{hs}:{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?:?', "?-?"

@st.cache_data(ttl=3600)
def extract_h2h_data_of(soup: BeautifulSoup, main_home_team_name: str, main_away_team_name: str, current_league_id: str | None):
    # Replicada de datos.py
    ah1, res1, res1_raw, match1_id = '-', '?:?', '?-?', None
    ah6, res6, res6_raw, match6_id = '-', '?:?', '?-?', None
    h2h_gen_home_name, h2h_gen_away_name = "Local (H2H Gen)", "Visitante (H2H Gen)"

    if not soup: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    h2h_table = soup.select_one("table#table_v3") # Selector CSS
    if not h2h_table: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    filtered_h2h_list = []
    # main_home_team_name y main_away_team_name pueden ser None o "N/A"
    valid_main_team_names = main_home_team_name and main_home_team_name != "N/A" and \
                            main_away_team_name and main_away_team_name != "N/A"

    for row_h2h in h2h_table.select("tr[id^=tr3_]"): # Selector CSS
        details = get_match_details_from_row_of(row_h2h, score_class_selector='fscore_3', source_table_type='h2h')
        if not details: continue
        # Filtrar por liga si current_league_id está presente
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue
        filtered_h2h_list.append(details)

    if not filtered_h2h_list: return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

    # H2H General (primer partido de la lista filtrada)
    h2h_general_match = filtered_h2h_list[0]
    ah6 = h2h_general_match.get('ahLine', '-')
    res6 = h2h_general_match.get('score', '?:?'); res6_raw = h2h_general_match.get('score_raw', '?-?')
    match6_id = h2h_general_match.get('match_id') # Usar 'match_id'
    h2h_gen_home_name = h2h_general_match.get('home', "Local (H2H Gen)")
    h2h_gen_away_name = h2h_general_match.get('away', "Visitante (H2H Gen)")

    # H2H Específico (Local en Casa)
    if valid_main_team_names:
        h2h_local_specific_match = None
        for d_h2h in filtered_h2h_list:
            if d_h2h.get('home','').lower() == main_home_team_name.lower() and \
               d_h2h.get('away','').lower() == main_away_team_name.lower():
                h2h_local_specific_match = d_h2h; break

        if h2h_local_specific_match:
            ah1 = h2h_local_specific_match.get('ahLine', '-')
            res1 = h2h_local_specific_match.get('score', '?:?'); res1_raw = h2h_local_specific_match.get('score_raw', '?-?')
            match1_id = h2h_local_specific_match.get('match_id') # Usar 'match_id'

    return ah1, res1, res1_raw, match1_id, ah6, res6, res6_raw, match6_id, h2h_gen_home_name, h2h_gen_away_name

@st.cache_data(ttl=3600)
def extract_comparative_match_of(soup_for_team_history: BeautifulSoup, table_id_of_team_to_search: str,
                                 team_name_to_find_match_for: str, opponent_name_to_search: str,
                                 current_league_id: str | None, is_home_table: bool):
    # Replicada de datos.py
    if not soup_for_team_history or not opponent_name_to_search or opponent_name_to_search == "N/A" or \
       not team_name_to_find_match_for or team_name_to_find_match_for == "N/A":
        return None

    table = soup_for_team_history.select_one(f"table#{table_id_of_team_to_search}") # Selector CSS
    if not table: return None

    score_class_selector = 'fscore_1' if is_home_table else 'fscore_2'
    table_row_prefix = table_id_of_team_to_search[-1] # e.g., '1' from 'table_v1'

    for row in table.select(f"tr[id^=tr{table_row_prefix}_]"): # Selector CSS
        details = get_match_details_from_row_of(row, score_class_selector=score_class_selector, source_table_type='hist')
        if not details: continue
        if current_league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(current_league_id):
            continue

        home_hist = details.get('home','').lower(); away_hist = details.get('away','').lower()
        team_main_lower = team_name_to_find_match_for.lower(); opponent_lower = opponent_name_to_search.lower()

        if (team_main_lower == home_hist and opponent_lower == away_hist) or \
           (team_main_lower == away_hist and opponent_lower == home_hist):
            return {
                "score": details.get('score', '?:?'),
                "ah_line": details.get('ahLine', '-'),
                "localia": 'H' if team_main_lower == home_hist else 'A',
                "home_team": details.get('home'),
                "away_team": details.get('away'),
                "match_id": details.get('match_id') # Usar 'match_id'
            }
    return None


# --- FUNCIONES DEPENDIENTES DE SELENIUM (Intentar minimizar su uso) ---
_selenium_driver_instance = None

@st.cache_resource
def get_selenium_driver_of_cached(): # Renombrada para evitar conflicto con la de datos.py si se importa allí
    global _selenium_driver_instance
    if _selenium_driver_instance is None:
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"user-agent={USER_AGENT}")
        options.add_argument('--blink-settings=imagesEnabled=false') # Deshabilitar imágenes
        options.add_argument("--window-size=1280,720") # Tamaño más pequeño
        # Más opciones para reducir consumo
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3") # Solo errores fatales
        options.add_argument("--silent")


        # prefs = {"profile.managed_default_content_settings.images": 2} # No cargar imágenes
        # options.add_experimental_option("prefs", prefs)

        try:
            # Especificar servicio para controlar logs
            from selenium.webdriver.chrome.service import Service as ChromeService
            service = ChromeService(log_output=None) # Descartar logs de chromedriver
            # _selenium_driver_instance = webdriver.Chrome(options=options, service=service)
            # Temporalmente sin service para ver si es la causa del error en sandbox
            _selenium_driver_instance = webdriver.Chrome(options=options)


        except WebDriverException as e:
            # print(f"Error inicializando Selenium driver (extractor_rapido): {e}")
            # Considerar st.error o similar si esto fuera parte de una app Streamlit directa
            return None
    return _selenium_driver_instance

def close_selenium_driver_of():
    global _selenium_driver_instance
    if _selenium_driver_instance is not None:
        try:
            _selenium_driver_instance.quit()
        except Exception: # Considerar logging
            pass
        _selenium_driver_instance = None

def click_element_robust_of(driver, by, value, timeout=5): # Timeout reducido
    # Replicada de datos.py
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((by, value)))
        # No es necesario esperar visibilidad si solo se va a clickear con JS
        # WebDriverWait(driver, timeout, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.visibility_of(element))
        # ScrollIntoView puede ser lento, intentar click directo primero
        # driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element); time.sleep(0.1) # Sleep reducido
        try:
            # Priorizar click JS que suele ser más robusto a intercepciones
            driver.execute_script("arguments[0].click();", element)
        except Exception: # Fallback al click normal
            WebDriverWait(driver, 2, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.element_to_be_clickable((by, value))).click()
        return True
    except Exception: # Considerar logging
        return False

@st.cache_data(ttl=3600)
def get_main_match_odds_selenium_of(driver, match_h2h_url_path: str):
    # Modificada para aceptar el path y hacer el get aquí si es necesario
    # Esto asume que el driver ya está en la página correcta o la carga aquí.
    # Para optimizar, es mejor que el driver ya esté en la página.
    odds_info = {"ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A", "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"}
    if not driver: return odds_info

    current_url = driver.current_url
    expected_page_segment = match_h2h_url_path.split('/')[-1] # e.g., h2h-match_id

    # Solo navegar si no estamos ya en la página correcta (o una muy similar)
    if expected_page_segment not in current_url:
        try:
            driver.get(f"{BASE_URL_OF}{match_h2h_url_path}")
            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))
        except Exception:
            # print(f"Error navegando o esperando liveCompareDiv en {match_h2h_url_path}")
            return odds_info # No se pudo cargar la página o encontrar el div

    try:
        # No es necesario esperar liveCompareDiv si ya se esperó antes o si la página ya está cargada.
        # live_compare_div = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF, poll_frequency=SELENIUM_POLL_FREQUENCY_OF).until(EC.presence_of_element_located((By.ID, "liveCompareDiv")))

        # Usar selectores CSS que son generalmente más rápidos
        bet365_row = driver.find_element(By.CSS_SELECTOR, "tr#tr_o_1_8[name='earlyOdds'], tr#tr_o_1_31[name='earlyOdds']") # Coma para OR en CSS
        # No es necesario scrollear si el elemento es encontrado
        # driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", bet365_row); time.sleep(0.1)

        tds = bet365_row.find_elements(By.TAG_NAME, "td")
        if len(tds) >= 11:
            odds_info["ah_home_cuota"] = tds[2].get_attribute("data-o") or tds[2].text.strip() or "N/A"
            odds_info["ah_linea_raw"] = tds[3].get_attribute("data-o") or tds[3].text.strip() or "N/A"
            odds_info["ah_away_cuota"] = tds[4].get_attribute("data-o") or tds[4].text.strip() or "N/A"
            odds_info["goals_over_cuota"] = tds[8].get_attribute("data-o") or tds[8].text.strip() or "N/A"
            odds_info["goals_linea_raw"] = tds[9].get_attribute("data-o") or tds[9].text.strip() or "N/A"
            odds_info["goals_under_cuota"] = tds[10].get_attribute("data-o") or tds[10].text.strip() or "N/A"
    except NoSuchElementException:
        # print("No se encontró la fila de Bet365 para las cuotas.")
        pass # Es común que no esté, no necesariamente un error grave.
    except Exception: # Considerar logging
        # print(f"Excepción en get_main_match_odds_selenium_of: {e}")
        pass
    return odds_info

@st.cache_data(ttl=3600)
def extract_last_match_in_league_of(driver, table_css_id_str: str, main_team_name_in_table: str,
                                    league_id_filter_value: str | None, home_or_away_filter_css_selector: str,
                                    is_home_game_filter: bool, match_h2h_url_path: str):
    # Modificada para optimizar y asegurar que el driver está en la página correcta.
    if not driver or not main_team_name_in_table or main_team_name_in_table == "N/A": return None

    current_url = driver.current_url
    expected_page_segment = match_h2h_url_path.split('/')[-1]
    if expected_page_segment not in current_url:
        try:
            driver.get(f"{BASE_URL_OF}{match_h2h_url_path}")
            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, table_css_id_str)))
        except Exception:
            # print(f"Error navegando o esperando tabla {table_css_id_str} en {match_h2h_url_path}")
            return None

    try:
        # Los clics son la parte lenta y dependiente de JS
        if league_id_filter_value:
            league_checkbox_selector = f"input#checkboxleague{table_css_id_str[-1]}[value='{league_id_filter_value}']"
            click_element_robust_of(driver, By.CSS_SELECTOR, league_checkbox_selector); time.sleep(0.3) # Sleep reducido

        click_element_robust_of(driver, By.CSS_SELECTOR, home_or_away_filter_css_selector); time.sleep(0.5) # Sleep reducido, puede necesitar ajuste

        page_source_updated = driver.page_source # Obtener HTML después de acciones JS
        soup_updated = BeautifulSoup(page_source_updated, "lxml")
        table = soup_updated.select_one(f"table#{table_css_id_str}")
        if not table: return None

        count_visible_rows = 0
        table_row_prefix = table_css_id_str[-1]

        for row in table.select(f"tr[id^=tr{table_row_prefix}_]"): # Iterar sobre soup, no driver
            if row.get("style") and "display:none" in row.get("style","").lower(): continue
            count_visible_rows +=1
            if count_visible_rows > 7: break # Limitar búsqueda para velocidad

            # El filtro de liga ya se aplicó por JS, pero podemos re-verificar en el soup si es necesario (aunque añade tiempo)
            # if league_id_filter_value and row.get("name") != str(league_id_filter_value): continue

            # get_match_details_from_row_of usa find_all, que es más lento. Reimplementar aquí con selectores directos.
            tds = row.select("td")
            if len(tds) < 14: continue

            home_team_row_el = tds[2].select_one("a"); away_team_row_el = tds[4].select_one("a")
            if not home_team_row_el or not away_team_row_el: continue

            home_team_row_name = home_team_row_el.text.strip(); away_team_row_name = away_team_row_el.text.strip()
            team_is_home_in_row = main_team_name_in_table.lower() == home_team_row_name.lower()
            team_is_away_in_row = main_team_name_in_table.lower() == away_team_row_name.lower()

            if (is_home_game_filter and team_is_home_in_row) or \
               (not is_home_game_filter and team_is_away_in_row):
                date_span = tds[1].select_one("span[name=timeData]"); date = date_span.text.strip() if date_span else "N/A"
                score_span = tds[3].select_one("span[class*=fscore_]"); score = score_span.text.strip() if score_span else "N/A"
                handicap_cell = tds[11]; handicap_raw = handicap_cell.get("data-o", handicap_cell.text.strip())
                if not handicap_raw or handicap_raw.strip() == "-": handicap_raw = "N/A"
                else: handicap_raw = handicap_raw.strip()

                match_id_last_game = row.get('index')
                return {"date": date, "home_team": home_team_row_name,
                        "away_team": away_team_row_name,"score": score,
                        "handicap_line_raw": handicap_raw,
                        "match_id": match_id_last_game}
        return None
    except Exception: # Considerar logging
        # print(f"Excepción en extract_last_match_in_league_of: {e}")
        return None

@st.cache_data(ttl=3600)
def get_h2h_details_for_original_logic_of(driver, key_match_id_for_h2h_url: str, rival_a_id: str, rival_b_id: str,
                                          rival_a_name="Rival A", rival_b_name="Rival B"):
    # Esta función inherentemente necesita cargar una nueva página con Selenium si se usa el driver.
    # O, si se pasa soup, parsear ese soup.
    # Para optimización, si key_match_id_for_h2h_url es el mismo que el partido principal,
    # se podría reusar el soup principal. Pero la lógica original busca en table_v2 de la página del rival.
    if not driver: return {"status": "error", "resultado": "N/A (Driver no disponible H2H OF)", "match_id": None}
    if not key_match_id_for_h2h_url or not rival_a_id or not rival_b_id:
        return {"status": "error", "resultado": f"N/A (IDs incompletos para H2H {rival_a_name} vs {rival_b_name})", "match_id": None}

    url_to_visit = f"{BASE_URL_OF}/match/h2h-{key_match_id_for_h2h_url}"
    try:
        # Solo navegar si no estamos ya en la página del H2H del rival A (key_match_id_for_h2h_url)
        current_url = driver.current_url
        expected_page_segment = f"h2h-{key_match_id_for_h2h_url}"
        if expected_page_segment not in current_url:
            driver.get(url_to_visit)
            WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v2")))

        # Dar un pequeño tiempo para JS si es necesario, aunque la espera anterior debería bastar
        time.sleep(0.3) # Reducido
        soup_selenium = BeautifulSoup(driver.page_source, "lxml")
    except TimeoutException:
        return {"status": "error", "resultado": f"N/A (Timeout esperando table_v2 en {url_to_visit})", "match_id": None}
    except Exception as e:
        return {"status": "error", "resultado": f"N/A (Error Selenium en {url_to_visit}: {type(e).__name__})", "match_id": None}

    if not soup_selenium:
        return {"status": "error", "resultado": f"N/A (Fallo soup Selenium H2H en {url_to_visit})", "match_id": None}

    table_to_search_h2h = soup_selenium.select_one("table#table_v2")
    if not table_to_search_h2h:
        return {"status": "error", "resultado": f"N/A (Tabla v2 para H2H no encontrada en {url_to_visit})", "match_id": None}

    for row in table_to_search_h2h.select("tr[id^=tr2_]"):
        links = row.select("a[onclick]")
        if len(links) < 2: continue
        h2h_row_home_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", ""));
        h2h_row_away_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))
        if not h2h_row_home_id_m or not h2h_row_away_id_m: continue
        h2h_row_home_id = h2h_row_home_id_m.group(1); h2h_row_away_id = h2h_row_away_id_m.group(1)

        if {h2h_row_home_id, h2h_row_away_id} == {str(rival_a_id), str(rival_b_id)}:
            score_span = row.select_one("span.fscore_2") # fscore_2 para table_v2
            if not score_span or not score_span.text or "-" not in score_span.text: continue
            score_val = score_span.text.strip().split("(")[0].strip(); g_h, g_a = score_val.split("-", 1)

            tds = row.select("td"); handicap_raw = "N/A"; HANDICAP_TD_IDX = 11
            if len(tds) > HANDICAP_TD_IDX:
                cell = tds[HANDICAP_TD_IDX]; d_o = cell.get("data-o")
                handicap_raw = d_o.strip() if d_o and d_o.strip() not in ["", "-"] else (cell.text.strip() if cell.text.strip() not in ["", "-"] else "N/A")

            match_id_h2h_rivals = row.get('index')
            rol_a_in_this_h2h = "H" if h2h_row_home_id == str(rival_a_id) else "A"

            return {"status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                    "handicap": handicap_raw, "rol_rival_a": rol_a_in_this_h2h,
                    "h2h_home_team_name": links[0].text.strip(),
                    "h2h_away_team_name": links[1].text.strip(),
                    "match_id": match_id_h2h_rivals}

    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name} en {key_match_id_for_h2h_url}.", "match_id": None}


# --- FUNCIÓN PRINCIPAL DE EXTRACCIÓN ---
async def extraer_datos_partido_rapido(partido_id: int, session_requests, driver_selenium):
    # El driver_selenium se pasa como argumento, se gestiona externamente.
    start_total_time = time.time()
    data = {"partido_id": str(partido_id)}

    # 1. Obtener soup de la página H2H principal
    main_h2h_path = f"/match/h2h-{partido_id}"
    # soup_main_h2h_page = await fetch_soup_async(main_h2h_path, session_requests)
    soup_main_h2h_page = fetch_soup_requests_sync(main_h2h_path, session_requests) # Version sync temporal
    if not soup_main_h2h_page:
        data["error"] = "No se pudo obtener la página H2H principal."
        return data

    # 2. Información básica del partido
    home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(soup_main_h2h_page)
    data["main_match_info"] = {
        "home_team_id": home_id, "home_team_name": home_name,
        "away_team_id": away_id, "away_team_name": away_name,
        "league_id": league_id, "league_name": league_name,
    }

    # 3. Clasificaciones de equipos principales
    # Estas pueden ser llamadas en paralelo si fetch_soup_async es verdaderamente async
    # standings_home_task = extract_standings_data_from_h2h_page_of(soup_main_h2h_page, home_name)
    # standings_away_task = extract_standings_data_from_h2h_page_of(soup_main_h2h_page, away_name)
    # data["standings"] = {
    #     "home_team": await standings_home_task, # si la función fuera async
    #     "away_team": await standings_away_task, # si la función fuera async
    # }
    data["standings"] = {
         "home_team": extract_standings_data_from_h2h_page_of(soup_main_h2h_page, home_name),
         "away_team": extract_standings_data_from_h2h_page_of(soup_main_h2h_page, away_name)
    }
    # Actualizar nombres de equipos principales con los de standings si son más completos
    if data["standings"]["home_team"].get("name", "N/A") != "N/A":
        home_name = data["standings"]["home_team"]["name"]
        data["main_match_info"]["home_team_name"] = home_name
    if data["standings"]["away_team"].get("name", "N/A") != "N/A":
        away_name = data["standings"]["away_team"]["name"]
        data["main_match_info"]["away_team_name"] = away_name


    # 4. Marcador final (si existe) y Estadísticas de Progresión del partido principal
    final_score_fmt, final_score_raw = extract_final_score_of(soup_main_h2h_page)
    data["main_match_info"]["final_score"] = final_score_fmt if final_score_fmt != "?:?" else None
    data["main_match_info"]["final_score_raw"] = final_score_raw if final_score_raw != "?-?" else None
    if data["main_match_info"]["final_score"]: # Si hay marcador, obtener stats
        # data["main_match_info"]["progression_stats"] = await get_match_progression_stats_data(str(partido_id), session_requests)
        data["main_match_info"]["progression_stats"] = get_match_progression_stats_data(str(partido_id), session_requests)


    # 5. H2H Directos
    ah1, res1, _, m1_id, ah6, res6, _, m6_id, h2h_gen_h_name, h2h_gen_a_name = extract_h2h_data_of(soup_main_h2h_page, home_name, away_name, league_id)
    data["h2h_direct"] = {
        "home_at_home": {"ah_line": ah1, "score": res1, "match_id": m1_id, "progression_stats": None},
        "general_last": {"ah_line": ah6, "score": res6, "match_id": m6_id, "home_team_name": h2h_gen_h_name, "away_team_name": h2h_gen_a_name, "progression_stats": None}
    }
    # if m1_id: data["h2h_direct"]["home_at_home"]["progression_stats"] = await get_match_progression_stats_data(m1_id, session_requests)
    # if m6_id: data["h2h_direct"]["general_last"]["progression_stats"] = await get_match_progression_stats_data(m6_id, session_requests)
    if m1_id: data["h2h_direct"]["home_at_home"]["progression_stats"] = get_match_progression_stats_data(m1_id, session_requests)
    if m6_id: data["h2h_direct"]["general_last"]["progression_stats"] = get_match_progression_stats_data(m6_id, session_requests)


    # --- Operaciones que podrían usar Selenium ---
    # El driver se pasa, así que la gestión de su ciclo de vida es externa.
    # Idealmente, todas las operaciones de Selenium en la misma página se hacen secuencialmente
    # para evitar recargas.
    data["odds"] = {}
    data["last_matches"] = {"home_team_last_home": None, "away_team_last_away": None}
    data["h2h_indirect_col3"] = {}
    data["comparative_matches"] = {"home_vs_last_opponent_of_away": None, "away_vs_last_opponent_of_home": None}
    data["rival_info_for_col3"] = {}

    if driver_selenium:
        # Navegar a la página principal H2H una vez (si no está ya allí)
        try:
            current_url = driver_selenium.current_url
            expected_page_segment = main_h2h_path.split('/')[-1]
            if expected_page_segment not in current_url:
                driver_selenium.get(f"{BASE_URL_OF}{main_h2h_path}")
                WebDriverWait(driver_selenium, SELENIUM_TIMEOUT_SECONDS_OF).until(EC.presence_of_element_located((By.ID, "table_v1"))) # Esperar un elemento clave
        except Exception as e_nav:
            # print(f"Error navegando a la página principal H2H con Selenium: {e_nav}")
            # Continuar sin datos de Selenium si falla la navegación inicial
            pass # El driver podría estar ya en un estado problemático.
        else: # Solo proceder si la navegación fue exitosa o ya estaba en la página
            # 6. Cuotas (Selenium)
            data["odds"] = get_main_match_odds_selenium_of(driver_selenium, main_h2h_path) # path para re-verificar

            # 7. Últimos partidos (Selenium)
            if home_id and league_id and home_name != "N/A":
                lh_match = extract_last_match_in_league_of(driver_selenium, "table_v1", home_name, league_id, "input#cb_sos1[value='1']", True, main_h2h_path)
                if lh_match:
                    # lh_match["progression_stats"] = await get_match_progression_stats_data(lh_match["match_id"], session_requests)
                    lh_match["progression_stats"] = get_match_progression_stats_data(lh_match["match_id"], session_requests)
                data["last_matches"]["home_team_last_home"] = lh_match

            if away_id and league_id and away_name != "N/A":
                la_match = extract_last_match_in_league_of(driver_selenium, "table_v2", away_name, league_id, "input#cb_sos2[value='2']", False, main_h2h_path)
                if la_match:
                    # la_match["progression_stats"] = await get_match_progression_stats_data(la_match["match_id"], session_requests)
                    la_match["progression_stats"] = get_match_progression_stats_data(la_match["match_id"], session_requests)

                data["last_matches"]["away_team_last_away"] = la_match

            # 8. Rivales para H2H Col3 y el H2H mismo (Selenium para la página del rival)
            # Esto requiere navegar a otra página con Selenium, lo cual es costoso.
            # Primero, obtener IDs de rivales (ya hecho con requests si es posible, o re-hacer)
            # rival_a_key_match, rival_a_id, rival_a_name, _ = await get_rival_a_for_original_h2h_of(partido_id, session_requests)
            # rival_b_key_match, rival_b_id, rival_b_name, _ = await get_rival_b_for_original_h2h_of(partido_id, session_requests)
            rival_a_key_match, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(partido_id, session_requests)
            rival_b_key_match, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(partido_id, session_requests)


            data["rival_info_for_col3"] = {
                "rival_a": {"id": rival_a_id, "name": rival_a_name, "ref_match_id_h2h_page": rival_a_key_match},
                "rival_b": {"id": rival_b_id, "name": rival_b_name, "ref_match_id_h2h_page": rival_b_key_match} # Usar key_match de A para la página
            }

            if rival_a_key_match and rival_a_id and rival_b_id: # rival_b_key_match no se usa para la URL, sino el de A
                h2h_col3_details = get_h2h_details_for_original_logic_of(driver_selenium, rival_a_key_match, rival_a_id, rival_b_id, rival_a_name, rival_b_name)
                if h2h_col3_details.get("status") == "found" and h2h_col3_details.get("match_id"):
                    # h2h_col3_details["progression_stats"] = await get_match_progression_stats_data(h2h_col3_details["match_id"], session_requests)
                    h2h_col3_details["progression_stats"] = get_match_progression_stats_data(h2h_col3_details["match_id"], session_requests)
                data["h2h_indirect_col3"] = h2h_col3_details


    # 9. Comparativas indirectas (usando soup_main_h2h_page)
    last_away_match_info = data["last_matches"]["away_team_last_away"]
    opponent_for_home_comp = last_away_match_info.get("home_team") if last_away_match_info else None
    if opponent_for_home_comp and home_name != "N/A":
        comp1 = extract_comparative_match_of(soup_main_h2h_page, "table_v1", home_name, opponent_for_home_comp, league_id, True)
        if comp1 and comp1.get("match_id"):
            # comp1["progression_stats"] = await get_match_progression_stats_data(comp1["match_id"], session_requests)
            comp1["progression_stats"] = get_match_progression_stats_data(comp1["match_id"], session_requests)
        data["comparative_matches"]["home_vs_last_opponent_of_away"] = comp1

    last_home_match_info = data["last_matches"]["home_team_last_home"]
    opponent_for_away_comp = last_home_match_info.get("away_team") if last_home_match_info else None
    if opponent_for_away_comp and away_name != "N/A":
        comp2 = extract_comparative_match_of(soup_main_h2h_page, "table_v2", away_name, opponent_for_away_comp, league_id, False)
        if comp2 and comp2.get("match_id"):
            # comp2["progression_stats"] = await get_match_progression_stats_data(comp2["match_id"], session_requests)
            comp2["progression_stats"] = get_match_progression_stats_data(comp2["match_id"], session_requests)
        data["comparative_matches"]["away_vs_last_opponent_of_home"] = comp2

    data["execution_time_seconds"] = time.time() - start_total_time
    return data

# Helper síncrono para fetch_soup_requests_of, hasta que todo sea async
@st.cache_data(ttl=1800)
def fetch_soup_requests_sync(path, session_requests):
    url = f"{BASE_URL_OF}{path}"
    try:
        resp = session_requests.get(url, timeout=8)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException: # Considerar logging
        return None


# --- Ejemplo de uso (para pruebas) ---
async def main_test(partido_id_test):
    req_session = get_requests_session_of()
    # Intentar obtener driver, puede ser None si falla la inicialización
    # driver = get_selenium_driver_of_cached()
    driver = None # Forzar prueba sin selenium inicialmente

    print(f"Iniciando extracción para partido ID: {partido_id_test} (Sin Selenium)")
    datos_partido = await extraer_datos_partido_rapido(partido_id_test, req_session, driver)

    # Imprimir un resumen de los datos
    print(f"\n--- Resumen Datos Extraídos para {partido_id_test} ---")
    print(f"Tiempo total: {datos_partido.get('execution_time_seconds'):.2f}s")
    if datos_partido.get('error'):
        print(f"Error: {datos_partido.get('error')}")
        return

    print(f"Info Partido: {datos_partido.get('main_match_info', {}).get('home_team_name')} vs {datos_partido.get('main_match_info', {}).get('away_team_name')}")
    print(f"Marcador Final: {datos_partido.get('main_match_info', {}).get('final_score', 'N/A')}")
    print(f"Cuotas AH: {datos_partido.get('odds', {}).get('ah_linea_raw', 'N/A')}")
    print(f"Standings Local (Ranking): {datos_partido.get('standings', {}).get('home_team', {}).get('ranking', 'N/A')}")
    print(f"Último Local (Casa): {datos_partido.get('last_matches', {}).get('home_team_last_home', {}).get('score', 'N/A')}")

    # Intentar con Selenium si el driver se inicializó
    # if driver:
    #     print(f"\nIniciando extracción para partido ID: {partido_id_test} (CON Selenium)")
    #     # Limpiar caches de datos que dependen de Selenium para forzar re-extracción con driver
    #     # Esto es complejo de hacer selectivamente con st.cache_data.
    #     # Para una prueba real, sería mejor reiniciar el script o comentar los @st.cache_data de funciones con Selenium.
    #     # O usar una sesión de requests diferente o un ID de partido diferente para evitar colisiones de cache.
    #     # Por ahora, asumimos que la cache no interfiere o que las funciones de selenium se llaman con diferentes parámetros.
    #     datos_partido_selenium = await extraer_datos_partido_rapido(partido_id_test, req_session, driver)
    #     print(f"Tiempo total (con Selenium): {datos_partido_selenium.get('execution_time_seconds'):.2f}s")
    #     print(f"Cuotas AH (con Selenium): {datos_partido_selenium.get('odds', {}).get('ah_linea_raw', 'N/A')}")
    #     print(f"Último Local (Casa) (con Selenium): {datos_partido_selenium.get('last_matches', {}).get('home_team_last_home', {}).get('score', 'N/A')}")
    #     print(f"H2H Col3 (con Selenium): {datos_partido_selenium.get('h2h_indirect_col3', {}).get('status', 'N/A')}")


    if driver: # Asegurarse de cerrar el driver si se usó
        close_selenium_driver_of()

if __name__ == '__main__':
    # Ejemplo de ID de partido para probar
    test_match_id = 2696131 # Usar un ID de un partido reciente o en curso

    # Para ejecutar una función async en un contexto síncrono como if __name__ == '__main__':
    # asyncio.run(main_test(test_match_id))
    # Por ahora, las funciones principales no son realmente async, así que se puede llamar directamente
    # o adaptar main_test para que no sea async.

    # Adaptación temporal de main_test para no ser async:
    req_session = get_requests_session_of()
    driver = None # Probar sin Selenium primero
    # driver = get_selenium_driver_of_cached() # Descomentar para probar con Selenium

    print(f"Iniciando extracción para partido ID: {test_match_id} (Driver: {'Sí' if driver else 'No'})")

    # Como extraer_datos_partido_rapido es async, necesitamos un event loop
    # Pero las funciones internas cacheadas no son async todavía.
    # Vamos a reestructurar para que la llamada principal no sea async por ahora,
    # y las funciones internas que podrían ser async se llamarán de forma síncrona.

    # Para simplificar la prueba inicial, se modificará `extraer_datos_partido_rapido` para que no sea `async`
    # y las llamadas a `get_match_progression_stats_data` etc. se harán directamente.
    # Esto se revierte si se implementa verdadera paralelización con asyncio/httpx.

    # Simulación de llamada (requiere que extraer_datos_partido_rapido NO sea async)
    # datos_partido = extraer_datos_partido_rapido_sync(test_match_id, req_session, driver)
    # print_summary(datos_partido)

    # Dado que la estructura actual de `extraer_datos_partido_rapido` está definida como `async`,
    # la forma correcta de llamarla es con `asyncio.run`.
    # Las funciones internas que usan `@st.cache_data` no deben ser `async` ellas mismas
    # a menos que Streamlit soporte cachear corutinas directamente (lo cual no es estándar).
    # La estrategia es: `extraer_datos_partido_rapido` es `async` y orquesta.
    # Las funciones de CPU-bound o I/O-bound que son cacheadas son síncronas,
    # y se pueden ejecutar en un executor si es necesario dentro de la corutina orquestadora.

    # Para esta fase, vamos a asumir que las funciones cacheadas que hacen I/O
    # (como fetch_soup_requests_sync) se comportan bien si se llaman desde una corutina
    # que se ejecuta con asyncio.run().

    async def run_extraction():
        nonlocal driver # Para poder modificar el driver de fuera si es necesario
        s = get_requests_session_of()

        # Prueba sin Selenium
        # d_no_selenium = await extraer_datos_partido_rapido(test_match_id, s, None)
        # print_summary(d_no_selenium, "SIN Selenium")

        # Prueba CON Selenium
        # Asegurarse que el driver se obtiene aquí si se va a probar con él
        driver_sel = get_selenium_driver_of_cached()
        if driver_sel:
            print("\nDriver de Selenium obtenido, procediendo con prueba completa.")
            d_with_selenium = await extraer_datos_partido_rapido(test_match_id, s, driver_sel)
            print_summary(d_with_selenium, "CON Selenium")
        else:
            print("\nNo se pudo obtener driver de Selenium. Ejecutando prueba SIN Selenium.")
            d_no_selenium = await extraer_datos_partido_rapido(test_match_id, s, None)
            print_summary(d_no_selenium, "SIN Selenium")


        if driver_sel: # Cerrar el driver global si se usó
            close_selenium_driver_of()
            print("Driver de Selenium cerrado.")

    def print_summary(datos, context=""):
        print(f"\n--- Resumen Datos Extraídos ({context}) para {datos.get('partido_id')} ---")
        print(f"Tiempo total: {datos.get('execution_time_seconds'):.2f}s")
        if datos.get('error'):
            print(f"Error: {datos.get('error')}")
            return

        main_info = datos.get('main_match_info', {})
        print(f"Info Partido: {main_info.get('home_team_name')} vs {main_info.get('away_team_name')}")
        print(f"Marcador Final: {main_info.get('final_score', 'N/A')}")

        odds = datos.get('odds', {})
        print(f"Cuotas AH: {odds.get('ah_linea_raw', 'N/A')} ({odds.get('ah_home_cuota', '/')}/{odds.get('ah_away_cuota', '/')})")

        standings_home = datos.get('standings', {}).get('home_team', {})
        print(f"Standings Local (Ranking): {standings_home.get('ranking', 'N/A')}, PJ: {standings_home.get('total_pj', 'N/A')}")

        last_home_match = datos.get('last_matches', {}).get('home_team_last_home', {})
        print(f"Último Local (Casa): Score {last_home_match.get('score', 'N/A')}, AH {last_home_match.get('handicap_line_raw', 'N/A')}")

        h2h_col3 = datos.get('h2h_indirect_col3', {})
        if h2h_col3.get("status") == "found":
            print(f"H2H Col3: {h2h_col3.get('h2h_home_team_name')} {h2h_col3.get('goles_home')}-{h2h_col3.get('goles_away')} {h2h_col3.get('h2h_away_team_name')}, AH: {h2h_col3.get('handicap')}")
        else:
            print(f"H2H Col3: {h2h_col3.get('status', 'Error/No procesado')} - {h2h_col3.get('resultado', '')}")

    asyncio.run(run_extraction())
    # Nota: Streamlit y asyncio pueden tener interacciones complejas.
    # Si esto se ejecuta DENTRO de un script Streamlit, st.cache_* y el loop de asyncio
    # deben manejarse con cuidado. Para un módulo de extracción puro, es más simple.
    # Las funciones cacheadas no deberían ser async ellas mismas.
    # Si una función async necesita cachear, cachear la parte síncrona o el resultado.
    # O usar cachés compatibles con asyncio como aiocache.
    # Por ahora, @st.cache_data en funciones síncronas llamadas desde una corrutina es la aproximación.
