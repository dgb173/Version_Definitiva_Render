# src/modules/estudio_scraper.py

import time
import copy
import requests
import re
import math
import threading
from contextlib import contextmanager
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

# --- CONFIGURACIÓN GLOBAL ---
BASE_URL_OF = "https://live18.nowgoal25.com"
PLACEHOLDER_NODATA = "*(No disponible)*"
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": BASE_URL_OF,
}
SOUP_CACHE_TTL_SECONDS = 45
STATS_CACHE_TTL_SECONDS = 300
ANALYSIS_CACHE_TTL_SECONDS = 120

_requests_session = None
_requests_session_lock = threading.Lock()
_soup_cache = {}
_soup_cache_lock = threading.Lock()
_stats_cache = {}
_stats_cache_lock = threading.Lock()
_analysis_cache = {}
_analysis_cache_lock = threading.Lock()
_STATS_NOT_FOUND = object()

def _read_cache(cache_dict, key, ttl_seconds, lock):
    with lock:
        entry = cache_dict.get(key)
        if not entry:
            return None
        ts, value = entry
        if (time.time() - ts) > ttl_seconds:
            cache_dict.pop(key, None)
            return None
        return value

def _write_cache(cache_dict, key, value, lock):
    with lock:
        cache_dict[key] = (time.time(), value)


def _get_cached_analysis(match_id: str):
    cached = _read_cache(_analysis_cache, match_id, ANALYSIS_CACHE_TTL_SECONDS, _analysis_cache_lock)
    if cached is None:
        return None
    return copy.deepcopy(cached)


def _set_cached_analysis(match_id: str, payload: dict):
    _write_cache(_analysis_cache, match_id, copy.deepcopy(payload), _analysis_cache_lock)

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO ---
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
            val1 = float(p1_str)
            val2 = float(p2_str)
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:
                 val2 = -abs(val2)
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:
            return float(s)
    except (ValueError, IndexError):
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
    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-','?'] else output_str
    return output_str

def _df_to_rows(df):
    rows = []
    if df is None or df.empty:
        return rows
    for idx, row in df.iterrows():
        label = str(idx).replace('Shots on Goal', 'Tiros a Puerta').replace('Shots', 'Tiros').replace('Dangerous Attacks', 'Ataques Peligrosos').replace('Attacks', 'Ataques')
        rows.append({
            'label': label,
            'home': row.get('Casa', ''),
            'away': row.get('Fuera', '')
        })
    return rows

# --- SISTEMA DE ANÁLISIS DE MERCADO ---
def check_handicap_cover(resultado_raw: str, ah_line_num: float, favorite_team_name: str, home_team_in_h2h: str, away_team_in_h2h: str, main_home_team_name: str):
    try:
        goles_h, goles_a = map(int, resultado_raw.split('-'))
        if ah_line_num == 0.0:
            if main_home_team_name.lower() == home_team_in_h2h.lower():
                if goles_h > goles_a: return ("CUBIERTO", True)
                elif goles_a > goles_h: return ("NO CUBIERTO", False)
                else: return ("PUSH", None)
            else:
                if goles_a > goles_h: return ("CUBIERTO", True)
                elif goles_h > goles_a: return ("NO CUBIERTO", False)
                else: return ("PUSH", None)
        
        if favorite_team_name.lower() == home_team_in_h2h.lower():
            favorite_margin = goles_h - goles_a
        elif favorite_team_name.lower() == away_team_in_h2h.lower():
            favorite_margin = goles_a - goles_h
        else:
            return ("indeterminado", None)
        
        if favorite_margin - abs(ah_line_num) > 0.05:
            return ("CUBIERTO", True)
        elif favorite_margin - abs(ah_line_num) < -0.05:
            return ("NO CUBIERTO", False)
        else:
            return ("PUSH", None)
    except (ValueError, TypeError, AttributeError):
        return ("indeterminado", None)

def check_goal_line_cover(resultado_raw: str, goal_line_num: float):
    try:
        goles_h, goles_a = map(int, resultado_raw.split('-'))
        total_goles = goles_h + goles_a
        if total_goles > goal_line_num:
            return ("SUPERADA (Over)", True)
        elif total_goles < goal_line_num:
            return (f"NO SUPERADA (UNDER)", False)
        else:
            return ("PUSH (Igual)", None)
    except (ValueError, TypeError):
        return ("indeterminado", None)

def _analizar_precedente_handicap(precedente_data, ah_actual_num, favorito_actual_name, main_home_team_name):
    res_raw = precedente_data.get('res_raw')
    ah_raw = precedente_data.get('ah_raw')
    home_team_precedente = precedente_data.get('home')
    away_team_precedente = precedente_data.get('away')

    if not all([res_raw, res_raw != '?-?', ah_raw, ah_raw != '-']):
        return "<li><span class='ah-value'>Hándicap:</span> No hay datos suficientes en este precedente.</li>"

    ah_historico_num = parse_ah_to_number_of(ah_raw)
    comparativa_texto = ""

    if ah_historico_num is not None and ah_actual_num is not None:
        formatted_ah_historico = format_ah_as_decimal_string_of(ah_raw)
        formatted_ah_actual = format_ah_as_decimal_string_of(str(ah_actual_num))
        line_movement_str = f"{formatted_ah_historico} → {formatted_ah_actual}"
        
        favorito_historico_name = None
        if ah_historico_num > 0:
            favorito_historico_name = home_team_precedente
        elif ah_historico_num < 0:
            favorito_historico_name = away_team_precedente
        
        if favorito_actual_name.lower() == (favorito_historico_name or "").lower():
            if abs(ah_actual_num) > abs(ah_historico_num):
                comparativa_texto = f"El mercado considera a este equipo <strong>más favorito</strong> que en el precedente (movimiento: <strong style='color: green; font-size:1.2em;'>{line_movement_str}</strong>). "
            elif abs(ah_actual_num) < abs(ah_historico_num):
                comparativa_texto = f"El mercado considera a este equipo <strong>menos favorito</strong> que en el precedente (movimiento: <strong style='color: orange; font-size:1.2em;'>{line_movement_str}</strong>). "
            else:
                comparativa_texto = f"El mercado mantiene una línea de <strong>magnitud idéntica</strong> a la del precedente (<strong>{formatted_ah_historico}</strong>). "
        else:
            if favorito_historico_name and favorito_actual_name != "Ninguno (línea en 0)":
                comparativa_texto = f"Ha habido un <strong>cambio total de favoritismo</strong>. En el precedente el favorito era '{favorito_historico_name}' (movimiento: <strong style='color: red; font-size:1.2em;'>{line_movement_str}</strong>). "
            elif not favorito_historico_name:
                comparativa_texto = f"El mercado establece un favorito claro, considerándolo <strong>mucho más favorito</strong> que en el precedente (movimiento: <strong style='color: green; font-size:1.2em;'>{line_movement_str}</strong>). "
            else:
                comparativa_texto = f"El mercado <strong>ha eliminado al favorito</strong> ('{favorito_historico_name}') que existía en el precedente (movimiento: <strong style='color: orange; font-size:1.2em;'>{line_movement_str}</strong>). "
    else:
        comparativa_texto = f"No se pudo realizar una comparación detallada (línea histórica: <strong>{format_ah_as_decimal_string_of(ah_raw)}</strong>). "

    resultado_cover, cubierto = check_handicap_cover(res_raw, ah_actual_num, favorito_actual_name, home_team_precedente, away_team_precedente, main_home_team_name)
    
    if cubierto is True:
        cover_html = f"<span style='color: green; font-weight: bold;'>CUBIERTO ✅</span>"
    elif cubierto is False:
        cover_html = f"<span style='color: red; font-weight: bold;'>NO CUBIERTO ❌</span>"
    else:
        cover_html = f"<span style='color: #6c757d; font-weight: bold;'>{resultado_cover.upper()} 🤔</span>"

    return f"<li><span class='ah-value'>Hándicap:</span> {comparativa_texto}Con el resultado ({res_raw.replace('-' , ':')}), la línea actual se habría considerado {cover_html}.</li>"

def _analizar_precedente_goles(precedente_data, goles_actual_num):
    res_raw = precedente_data.get('res_raw')
    if not res_raw or res_raw == '?-?':
        return "<li><span class='score-value'>Goles:</span> No hay datos suficientes en este precedente.</li>"
    try:
        total_goles = sum(map(int, res_raw.split('-')))
        resultado_cover, _ = check_goal_line_cover(res_raw, goles_actual_num)
        if 'SUPERADA' in resultado_cover:
            cover_html = f"<span style='color: green; font-weight: bold;'>{resultado_cover}</span>"
        elif 'NO SUPERADA' in resultado_cover:
            cover_html = f"<span style='color: red; font-weight: bold;'>{resultado_cover}</span>"
        else:
            cover_html = f"<span style='color: #6c757d; font-weight: bold;'>{resultado_cover}</span>"
        
        return f"<li><span class='score-value'>Goles:</span> El partido tuvo <strong>{total_goles} goles</strong>, por lo que la línea actual habría resultado {cover_html}.</li>"
    except (ValueError, TypeError):
        return "<li><span class='score-value'>Goles:</span> No se pudo procesar el resultado del precedente.</li>"

def generar_analisis_completo_mercado(main_odds, h2h_data, home_name, away_name):
    ah_actual_str = format_ah_as_decimal_string_of(main_odds.get('ah_linea_raw', '-'))
    ah_actual_num = parse_ah_to_number_of(ah_actual_str)
    goles_actual_num = parse_ah_to_number_of(main_odds.get('goals_linea_raw', '-'))

    if ah_actual_num is None or goles_actual_num is None: return ""

    favorito_name, favorito_html = "Ninguno (línea en 0)", "Ninguno (línea en 0)"
    if ah_actual_num < 0:
        favorito_name, favorito_html = away_name, f"<span class='away-color'>{away_name}</span>"
    elif ah_actual_num > 0:
        favorito_name, favorito_html = home_name, f"<span class='home-color'>{home_name}</span>"
    
    titulo_html = f"<p style='margin-bottom: 12px;'><strong>📊 Análisis de Mercado vs. Histórico H2H</strong><br><span style='font-style: italic; font-size: 0.9em;'>Líneas actuales: AH {ah_actual_str} / Goles {goles_actual_num} | Favorito: {favorito_html}</span></p>"

    precedente_estadio = {
        'res_raw': h2h_data.get('res1_raw'), 'ah_raw': h2h_data.get('ah1'),
        'home': home_name, 'away': away_name, 'match_id': h2h_data.get('match1_id')
    }
    sintesis_ah_estadio = _analizar_precedente_handicap(precedente_estadio, ah_actual_num, favorito_name, home_name)
    sintesis_goles_estadio = _analizar_precedente_goles(precedente_estadio, goles_actual_num)
    
    analisis_estadio_html = (
        f"<div style='margin-bottom: 10px;'>"
        f"  <strong style='font-size: 1.05em;'>🏟️ Análisis del Precedente en Este Estadio</strong>"
        f"  <ul style='margin: 5px 0 0 20px; padding-left: 0;'>{sintesis_ah_estadio}{sintesis_goles_estadio}</ul>"
        f"</div>"
    )

    precedente_general_id = h2h_data.get('match6_id')
    
    if precedente_estadio['match_id'] and precedente_general_id and precedente_estadio['match_id'] == precedente_general_id:
        analisis_general_html = (
            "<div style='margin-top: 10px;'>"
            "  <strong>✈️ Análisis del H2H General Más Reciente</strong>"
            "  <p style='margin: 5px 0 0 20px; font-style: italic; font-size: 0.9em;'>"
            "    El precedente es el mismo partido analizado arriba."
            "  </p>"
            "</div>"
        )
    else:
        precedente_general = {
            'res_raw': h2h_data.get('res6_raw'),
            'ah_raw': h2h_data.get('ah6'),
            'home': h2h_data.get('h2h_gen_home'),
            'away': h2h_data.get('h2h_gen_away'),
            'match_id': precedente_general_id
        }
        sintesis_ah_general = _analizar_precedente_handicap(precedente_general, ah_actual_num, favorito_name, home_name)
        sintesis_goles_general = _analizar_precedente_goles(precedente_general, goles_actual_num)
        
        analisis_general_html = (
            f"<div>"
            f"  <strong style='font-size: 1.05em;'>✈️ Análisis del H2H General Más Reciente</strong>"
            f"  <ul style='margin: 5px 0 0 20px; padding-left: 0;'>{sintesis_ah_general}{sintesis_goles_general}</ul>"
            f"</div>"
        )

    return f"""
    <div style="border-left: 4px solid #1E90FF; padding: 12px 15px; margin-top: 15px; background-color: #f0f2f6; border-radius: 5px; font-size: 0.95em;">
        {titulo_html}
        {analisis_estadio_html}
        {analisis_general_html}
    </div>
    """

# --- FUNCIONES DE EXTRACCIÓN DE DATOS ---
def get_match_details_from_row_of(row_element, score_class_selector='score', source_table_type='h2h'):
    try:
        cells = row_element.find_all('td')
        home_idx, score_idx, away_idx, ah_idx = 2, 3, 4, 11
        if len(cells) <= ah_idx: return None
        date_span = cells[1].find('span', attrs={'name': 'timeData'})
        date_txt = date_span.get_text(strip=True) if date_span else ''
        def get_cell_txt(idx):
            a = cells[idx].find('a')
            return a.get_text(strip=True) if a else cells[idx].get_text(strip=True)
        home, away = get_cell_txt(home_idx), get_cell_txt(away_idx)
        if not home or not away: return None
        score_cell = cells[score_idx]
        score_span = score_cell.find('span', class_=lambda c: isinstance(c, str) and score_class_selector in c)
        score_raw_text = (score_span.get_text(strip=True) if score_span else score_cell.get_text(strip=True)) or ''
        m = re.search(r'(\d+)\s*-\s*(\d+)', score_raw_text)
        score_raw, score_fmt = (f"{m.group(1)}-{m.group(2)}", f"{m.group(1)}:{m.group(2)}") if m else ('?-?', '?:?')
        ah_cell = cells[ah_idx]
        ah_line_raw = (ah_cell.get('data-o') or ah_cell.text).strip()
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw) if ah_line_raw not in ['', '-'] else '-'
        return {
            'date': date_txt, 'home': home, 'away': away, 'score': score_fmt,
            'score_raw': score_raw, 'ahLine': ah_line_fmt, 'ahLine_raw': ah_line_raw or '-',
            'matchIndex': row_element.get('index'), 'vs': row_element.get('vs'),
            'league_id_hist': row_element.get('name')
        }
    except Exception:
        return None

def get_requests_session_of():
    global _requests_session
    with _requests_session_lock:
        if _requests_session is None:
            session = requests.Session()
            retries = Retry(total=3, backoff_factor=0.4, status_forcelist=[500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retries, pool_connections=32, pool_maxsize=32)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(REQUEST_HEADERS)
            _requests_session = session
        return _requests_session

def get_match_progression_stats_data(match_id: str) -> pd.DataFrame | None:
    if not match_id or not str(match_id).isdigit():
        return None
    match_id = str(match_id)
    cached_value = _read_cache(_stats_cache, match_id, STATS_CACHE_TTL_SECONDS, _stats_cache_lock)
    if cached_value is not None:
        if cached_value is _STATS_NOT_FOUND:
            return None
        return cached_value.copy(deep=True)

    url = f"{BASE_URL_OF}/match/live-{match_id}"
    try:
        session = get_requests_session_of()
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        stat_titles = {"Shots": "-", "Shots on Goal": "-", "Attacks": "-", "Dangerous Attacks": "-"}
        team_tech_div = soup.find('div', id='teamTechDiv_detail')
        if team_tech_div and (stat_list := team_tech_div.find('ul', class_='stat')):
            for li in stat_list.find_all('li'):
                if (title_span := li.find('span', class_='stat-title')) and (stat_title := title_span.get_text(strip=True)) in stat_titles:
                    values = [v.get_text(strip=True) for v in li.find_all('span', class_='stat-c')]
                    if len(values) == 2:
                        stat_titles[stat_title] = {"Home": values[0], "Away": values[1]}
        table_rows = [{"Estadistica_EN": name, "Casa": vals.get('Home', '-'), "Fuera": vals.get('Away', '-')}
                      for name, vals in stat_titles.items() if isinstance(vals, dict)]
        df = pd.DataFrame(table_rows)
        df = df.set_index("Estadistica_EN") if not df.empty else df
        cache_value = df.copy(deep=True) if df is not None else _STATS_NOT_FOUND
        _write_cache(_stats_cache, match_id, cache_value, _stats_cache_lock)
        return df
    except requests.RequestException:
        _write_cache(_stats_cache, match_id, _STATS_NOT_FOUND, _stats_cache_lock)
        return None

def get_rival_a_for_original_h2h_of(soup, league_id=None):
    if not soup or not (table := soup.find("table", id="table_v1")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr1_\d+")):
        if league_id and row.get("name") != str(league_id):
            continue
        if row.get("vs") == "1" and (key_id := row.get("index")):
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 1 and (rival_tag := onclicks[1]) and (rival_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))):
                return key_id, rival_id_match.group(1), rival_tag.text.strip()
    return None, None, None

def get_rival_b_for_original_h2h_of(soup, league_id=None):
    if not soup or not (table := soup.find("table", id="table_v2")): return None, None, None
    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        if league_id and row.get("name") != str(league_id):
            continue
        if row.get("vs") == "1" and (key_id := row.get("index")):
            onclicks = row.find_all("a", onclick=True)
            if len(onclicks) > 0 and (rival_tag := onclicks[0]) and (rival_id_match := re.search(r"team\((\d+)\)", rival_tag.get("onclick", ""))):
                return key_id, rival_id_match.group(1), rival_tag.text.strip()
    return None, None, None

def get_h2h_details_for_original_logic_of(session, key_match_id, rival_a_id, rival_b_id, rival_a_name="Rival A", rival_b_name="Rival B"):
    if not all([session, key_match_id, rival_a_id, rival_b_id]):
        return {"status": "error", "resultado": "N/A (Datos incompletos para H2H)"}

    url = f"{BASE_URL_OF}/match/h2h-{key_match_id}"

    try:
        # Aquí asumimos que la tabla ya contiene los datos necesarios sin interacciones JS complejas.
        # En el futuro, se podría investigar si hay una API que devuelva estos datos.
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        return {"status": "error", "resultado": f"N/A (Error de red en H2H Col3: {e})"}

    if not (table := soup.find("table", id="table_v2")):
        return {"status": "error", "resultado": "N/A (Tabla H2H Col3 no encontrada)"}

    for row in table.find_all("tr", id=re.compile(r"tr2_\d+")):
        links = row.find_all("a", onclick=True)
        if len(links) < 2: continue

        h_id_m = re.search(r"team\((\d+)\)", links[0].get("onclick", ""));
        a_id_m = re.search(r"team\((\d+)\)", links[1].get("onclick", ""))

        if not (h_id_m and a_id_m): continue

        h_id, a_id = h_id_m.group(1), a_id_m.group(1)

        if {h_id, a_id} == {str(rival_a_id), str(rival_b_id)}:
            if not (score_span := row.find("span", class_="fscore_2")) or "-" not in score_span.text: continue

            score = score_span.text.strip().split("(")[0].strip()
            g_h, g_a = score.split("-", 1)
            tds = row.find_all("td")
            handicap_raw = "N/A"

            if len(tds) > 11:
                cell = tds[11]
                handicap_raw = (cell.get("data-o") or cell.text).strip() or "N/A"

            return {
                "status": "found", "goles_home": g_h.strip(), "goles_away": g_a.strip(),
                "handicap": handicap_raw, "match_id": row.get('index'),
                "h2h_home_team_name": links[0].text.strip(), "h2h_away_team_name": links[1].text.strip()
            }

    return {"status": "not_found", "resultado": f"H2H directo no encontrado para {rival_a_name} vs {rival_b_name}."}

def get_team_league_info_from_script_of(soup):
    script_tag = soup.find("script", string=re.compile(r"var _matchInfo = "))
    if not (script_tag and script_tag.string): return (None,) * 3 + ("N/A",) * 3
    content = script_tag.string
    def find_val(pattern):
        match = re.search(pattern, content)
        return match.group(1).replace("\'", "'") if match else None
    home_id = find_val(r"hId:\s*parseInt\('(\d+)'\)")
    away_id = find_val(r"gId:\s*parseInt\('(\d+)'\)")
    league_id = find_val(r"sclassId:\s*parseInt\('(\d+)'\)")
    home_name = find_val(r"hName:\s*'([^']*)'") or "N/A"
    away_name = find_val(r"gName:\s*'([^']*)'") or "N/A"
    league_name = find_val(r"lName:\s*'([^']*)'") or "N/A"
    return home_id, away_id, league_id, home_name, away_name, league_name

def _parse_date_ddmmyyyy(d: str) -> tuple:
    m = re.search(r'(\d{2})-(\d{2})-(\d{4})', d or '')
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (1900, 1, 1)

def extract_last_match_in_league_of(soup, table_id, team_name, league_id, is_home_game):
    if not soup or not (table := soup.find("table", id=table_id)): return None
    candidate_matches = []
    score_selector = 'fscore_1' if is_home_game else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if not (details := get_match_details_from_row_of(row, score_class_selector=score_selector, source_table_type='hist')):
            continue
        if league_id and details.get("league_id_hist") != str(league_id):
            continue
        is_team_home = team_name.lower() in details.get('home', '').lower()
        is_team_away = team_name.lower() in details.get('away', '').lower()
        if (is_home_game and is_team_home) or (not is_home_game and is_team_away):
            candidate_matches.append(details)
    if not candidate_matches: return None
    candidate_matches.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)
    last_match = candidate_matches[0]
    return {
        "date": last_match.get('date', 'N/A'), "home_team": last_match.get('home'),
        "away_team": last_match.get('away'), "score": last_match.get('score_raw', 'N/A').replace('-', ':'),
        "handicap_line_raw": last_match.get('ahLine_raw', 'N/A'), "match_id": last_match.get('matchIndex')
    }

def extract_bet365_initial_odds_of(soup):
    odds_info = {
        "ah_home_cuota": "N/A", "ah_linea_raw": "N/A", "ah_away_cuota": "N/A",
        "goals_over_cuota": "N/A", "goals_linea_raw": "N/A", "goals_under_cuota": "N/A"
    }
    if not soup: return odds_info
    bet365_row = soup.select_one("tr#tr_o_1_8[name='earlyOdds'], tr#tr_o_1_31[name='earlyOdds']")
    if not bet365_row: return odds_info
    tds = bet365_row.find_all("td")
    if len(tds) >= 11:
        odds_info["ah_home_cuota"] = tds[2].get("data-o", tds[2].text).strip()
        odds_info["ah_linea_raw"] = tds[3].get("data-o", tds[3].text).strip()
        odds_info["ah_away_cuota"] = tds[4].get("data-o", tds[4].text).strip()
        odds_info["goals_over_cuota"] = tds[8].get("data-o", tds[8].text).strip()
        odds_info["goals_linea_raw"] = tds[9].get("data-o", tds[9].text).strip()
        odds_info["goals_under_cuota"] = tds[10].get("data-o", tds[10].text).strip()
    return odds_info

def extract_standings_data_from_h2h_page_of(soup, team_name):
    data = {
        "name": team_name, "ranking": "N/A", "total_pj": "N/A", "total_v": "N/A",
        "total_e": "N/A", "total_d": "N/A", "total_gf": "N/A", "total_gc": "N/A",
        "specific_pj": "N/A", "specific_v": "N/A", "specific_e": "N/A",
        "specific_d": "N/A", "specific_gf": "N/A", "specific_gc": "N/A",
        "specific_type": "N/A"
    }
    if not soup or not team_name: return data
    standings_section = soup.find("div", id="porletP4")
    if not standings_section: return data
    team_table_soup = None
    is_home_table = False
    home_div = standings_section.find("div", class_="home-div")
    if home_div and team_name.lower() in home_div.get_text(strip=True).lower():
        team_table_soup = home_div.find("table", class_="team-table-home")
        is_home_table = True
        data["specific_type"] = "Est. como Local (en Liga)"
    else:
        guest_div = standings_section.find("div", class_="guest-div")
        if guest_div and team_name.lower() in guest_div.get_text(strip=True).lower():
            team_table_soup = guest_div.find("table", class_="team-table-guest")
            is_home_table = False
            data["specific_type"] = "Est. como Visitante (en Liga)"
    if not team_table_soup: return data
    header_link = team_table_soup.find("a")
    if header_link:
        full_text = header_link.get_text(separator=" ", strip=True)
        rank_match = re.search(r'\[.*?-(\d+)\]', full_text)
        if rank_match: data["ranking"] = rank_match.group(1)
    all_rows = team_table_soup.find_all("tr", align="center")
    is_ft_section = False
    for row in all_rows:
        header_cell = row.find("th")
        if header_cell:
            header_text = header_cell.get_text(strip=True)
            if "FT" in header_text: is_ft_section = True
            elif "HT" in header_text: is_ft_section = False
            continue
        if is_ft_section and len(cells := row.find_all("td")) >= 7:
            row_type_element = cells[0].find("span") or cells[0]
            row_type = row_type_element.get_text(strip=True)
            stats = [cell.get_text(strip=True) for cell in cells[1:7]]
            pj, v, e, d, gf, gc = stats
            if row_type == "Total":
                data.update({"total_pj": pj, "total_v": v, "total_e": e, "total_d": d, "total_gf": gf, "total_gc": gc})
            specific_row_needed = "Home" if is_home_table else "Away"
            if row_type == specific_row_needed:
                data.update({"specific_pj": pj, "specific_v": v, "specific_e": e, "specific_d": d, "specific_gf": gf, "specific_gc": gc})
    return data

def extract_over_under_stats_from_div_of(soup, team_type: str):
    default_stats = {"over_pct": 0, "under_pct": 0, "push_pct": 0, "total": 0}
    if not soup: return default_stats
    table_id = "table_v1" if team_type == 'home' else "table_v2"
    table = soup.find("table", id=table_id)
    if not table: return default_stats
    y_bar = table.find("ul", class_="y-bar")
    if not y_bar: return default_stats
    ou_group = None
    for group in y_bar.find_all("li", class_="group"):
        if "Over/Under Odds" in group.get_text():
            ou_group = group
            break
    if not ou_group: return default_stats
    try:
        total_text = ou_group.find("div", class_="tit").find("span").get_text(strip=True)
        total_match = re.search(r'\((\d+)\s*games\)', total_text)
        total = int(total_match.group(1)) if total_match else 0
        values = ou_group.find_all("span", class_="value")
        if len(values) == 3:
            over_pct_text = values[0].get_text(strip=True).replace('%', '')
            push_pct_text = values[1].get_text(strip=True).replace('%', '')
            under_pct_text = values[2].get_text(strip=True).replace('%', '')
            return {"over_pct": float(over_pct_text), "under_pct": float(under_pct_text), "push_pct": float(push_pct_text), "total": total}
    except (ValueError, TypeError, AttributeError):
        return default_stats
    return default_stats

def extract_final_score_of(soup):
    try:
        scores = soup.select('#mScore .end .score')
        if len(scores) == 2 and scores[0].text.strip().isdigit() and scores[1].text.strip().isdigit():
            hs, aws = scores[0].text.strip(), scores[1].text.strip()
            return f"{hs}:{aws}", f"{hs}-{aws}"
    except Exception: pass
    return '?:?', '?-?'

def extract_h2h_data_of(soup, home_name, away_name, league_id=None):
    results = {'ah1': '-', 'res1': '?:?', 'res1_raw': '?-?', 'match1_id': None, 'ah6': '-', 'res6': '?:?', 'res6_raw': '?-?', 'match6_id': None, 'h2h_gen_home': "Local (H2H Gen)", 'h2h_gen_away': "Visitante (H2H Gen)"}
    if not soup or not home_name or not away_name or not (h2h_table := soup.find("table", id="table_v3")): return results
    all_matches = []
    for r in h2h_table.find_all("tr", id=re.compile(r"tr3_\d+")):
        if (d := get_match_details_from_row_of(r, score_class_selector='fscore_3', source_table_type='h2h')):
            if not league_id or (d.get('league_id_hist') and d.get('league_id_hist') == str(league_id)):
                all_matches.append(d)
    if not all_matches: return results
    all_matches.sort(key=lambda x: _parse_date_ddmmyyyy(x.get('date', '')), reverse=True)
    most_recent = all_matches[0]
    results.update({'ah6': most_recent.get('ahLine', '-'), 'res6': most_recent.get('score', '?:?'), 'res6_raw': most_recent.get('score_raw', '?-?'), 'match6_id': most_recent.get('matchIndex'), 'h2h_gen_home': most_recent.get('home'), 'h2h_gen_away': most_recent.get('away')})
    for d in all_matches:
        if d['home'].lower() == home_name.lower() and d['away'].lower() == away_name.lower():
            results.update({'ah1': d.get('ahLine', '-'), 'res1': d.get('score', '?:?'), 'res1_raw': d.get('score_raw', '?-?'), 'match1_id': d.get('matchIndex')})
            break
    return results

def extract_comparative_match_of(soup, table_id, main_team, opponent, league_id, is_home_table):
    if not opponent or opponent == "N/A" or not main_team or not (table := soup.find("table", id=table_id)): return None
    score_selector = 'fscore_1' if is_home_table else 'fscore_2'
    for row in table.find_all("tr", id=re.compile(rf"tr{table_id[-1]}_\d+")):
        if not (details := get_match_details_from_row_of(row, score_class_selector=score_selector, source_table_type='hist')): continue
        if league_id and details.get('league_id_hist') and details.get('league_id_hist') != str(league_id): continue
        h, a = details.get('home','').lower(), details.get('away','').lower()
        main, opp = main_team.lower(), opponent.lower()
        if (main == h and opp == a) or (main == a and opp == h):
            return {"score": details.get('score', '?:?'), "ah_line": details.get('ahLine', '-'), "localia": 'H' if main == h else 'A', "home_team": details.get('home'), "away_team": details.get('away'), "match_id": details.get('matchIndex')}
    return None


def _load_main_match_soup(session, main_match_id: str):
    """
    Carga y parsea la página principal de un partido usando requests.
    """
    main_page_url = f"{BASE_URL_OF}/match/h2h-{main_match_id}"

    try:
        response = session.get(main_page_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        # Aquí se asume que la información principal está en el HTML inicial.
        # Las interacciones de JS para cambiar filtros no se pueden replicar fácilmente
        # sin analizar las llamadas de red que hace la página.
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        print(f"Error al cargar la página del partido {main_match_id}: {e}")
        return None

def analizar_partido_completo(match_id: str):
    main_match_id = "".join(filter(str.isdigit, str(match_id)))
    if not main_match_id:
        return {"error": "ID de partido inválido."}

    cached_payload = _get_cached_analysis(main_match_id)
    if cached_payload:
        return cached_payload

    start_time = time.time()
    session = get_requests_session_of()

    try:
        soup_completo = _load_main_match_soup(session, main_match_id)
        if soup_completo is None:
            return {"error": "No se pudo cargar la página del partido."}

        home_id, away_id, league_id, home_name, away_name, league_name = get_team_league_info_from_script_of(soup_completo)
        home_standings = extract_standings_data_from_h2h_page_of(soup_completo, home_name)
        away_standings = extract_standings_data_from_h2h_page_of(soup_completo, away_name)
        home_ou_stats = extract_over_under_stats_from_div_of(soup_completo, 'home')
        away_ou_stats = extract_over_under_stats_from_div_of(soup_completo, 'away')
        key_match_id_rival_a, rival_a_id, rival_a_name = get_rival_a_for_original_h2h_of(soup_completo, league_id)
        _, rival_b_id, rival_b_name = get_rival_b_for_original_h2h_of(soup_completo, league_id)
        last_home_match = extract_last_match_in_league_of(soup_completo, "table_v1", home_name, league_id, True)
        last_away_match = extract_last_match_in_league_of(soup_completo, "table_v2", away_name, league_id, False)
        h2h_data = extract_h2h_data_of(soup_completo, home_name, away_name, None)
        comp_L_vs_UV_A = extract_comparative_match_of(soup_completo, "table_v1", home_name, (last_away_match or {}).get('home_team'), league_id, True)
        comp_V_vs_UL_H = extract_comparative_match_of(soup_completo, "table_v2", away_name, (last_home_match or {}).get('away_team'), league_id, False)
        main_match_odds_data = extract_bet365_initial_odds_of(soup_completo)
        final_score, _ = extract_final_score_of(soup_completo)

        details_h2h_col3 = get_h2h_details_for_original_logic_of(
            session, key_match_id_rival_a, rival_a_id, rival_b_id, rival_a_name, rival_b_name
        )
    except Exception as exc:
        return {"error": f"Error durante el análisis: {exc}"}

    market_analysis_html = generar_analisis_completo_mercado(main_match_odds_data, h2h_data, home_name, away_name)

    def get_stats_rows(match_id_value):
        if not match_id_value:
            return []
        df = get_match_progression_stats_data(str(match_id_value))
        return _df_to_rows(df)

    last_home_match_stats = get_stats_rows((last_home_match or {}).get('match_id'))
    last_away_match_stats = get_stats_rows((last_away_match or {}).get('match_id'))
    h2h_col3_stats = get_stats_rows((details_h2h_col3 or {}).get('match_id'))
    comp_L_vs_UV_A_stats = get_stats_rows((comp_L_vs_UV_A or {}).get('match_id'))
    comp_V_vs_UL_H_stats = get_stats_rows((comp_V_vs_UL_H or {}).get('match_id'))
    h2h_stadium_stats = get_stats_rows(h2h_data.get('match1_id'))
    h2h_general_stats = get_stats_rows(h2h_data.get('match6_id'))

    results = {
        "match_id": main_match_id,
        "home_name": home_name,
        "away_name": away_name,
        "league_name": league_name,
        "final_score": final_score,
        "home_standings": home_standings,
        "away_standings": away_standings,
        "home_ou_stats": home_ou_stats,
        "away_ou_stats": away_ou_stats,
        "main_match_odds": {
            "ah_linea": format_ah_as_decimal_string_of(main_match_odds_data.get('ah_linea_raw', '?')),
            "goals_linea": format_ah_as_decimal_string_of(main_match_odds_data.get('goals_linea_raw', '?'))
        },
        "market_analysis_html": market_analysis_html,
        "last_home_match": {"details": last_home_match, "stats": last_home_match_stats},
        "last_away_match": {"details": last_away_match, "stats": last_away_match_stats},
        "h2h_col3": {"details": details_h2h_col3, "stats": h2h_col3_stats},
        "comp_L_vs_UV_A": {"details": comp_L_vs_UV_A, "stats": comp_L_vs_UV_A_stats},
        "comp_V_vs_UL_H": {"details": comp_V_vs_UL_H, "stats": comp_V_vs_UL_H_stats},
        "h2h_stadium": {"details": h2h_data, "stats": h2h_stadium_stats},
        "h2h_general": {"details": h2h_data, "stats": h2h_general_stats},
        "execution_time_seconds": round(time.time() - start_time, 2),
    }

    _set_cached_analysis(main_match_id, results)
    return copy.deepcopy(results)
