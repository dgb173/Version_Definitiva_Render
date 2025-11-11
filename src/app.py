# app.py - Servidor web principal (Flask)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from flask import Flask, render_template, abort, request, redirect, url_for
import datetime
import re
import math
import threading
import json
import time
import logging

# ¡Importante! Importa tu nuevo módulo de scraping
from modules.estudio_scraper import (
    analizar_partido_completo, 
    format_ah_as_decimal_string_of,
    parse_ah_to_number_of,
    check_handicap_cover,
    generar_analisis_completo_mercado
)
from flask import jsonify # Asegúrate de que jsonify está importado

app = Flask(__name__)

_EMPTY_DATA_TEMPLATE = {"upcoming_matches": [], "finished_matches": []}
_DATA_FILE_CANDIDATES = [
    Path(__file__).resolve().parent / 'data.json',
    Path(__file__).resolve().parent.parent / 'data.json',
]
for _candidate in _DATA_FILE_CANDIDATES:
    if _candidate.exists():
        DATA_FILE = _candidate
        break
else:
    DATA_FILE = _DATA_FILE_CANDIDATES[0]

_data_file_lock = threading.Lock()


def load_data_from_file():
    """Carga los datos desde el archivo JSON, similar a la app ligera."""
    with _data_file_lock:
        if not DATA_FILE.exists():
            return {key: [] for key in _EMPTY_DATA_TEMPLATE}
        try:
            with DATA_FILE.open('r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Error al leer {DATA_FILE}: {exc}")
            return {key: [] for key in _EMPTY_DATA_TEMPLATE}
        if not isinstance(data, dict):
            return {key: [] for key in _EMPTY_DATA_TEMPLATE}

        normalized = {}
        for key in _EMPTY_DATA_TEMPLATE:
            value = data.get(key, [])
            if isinstance(value, list):
                normalized[key] = [item for item in value if isinstance(item, dict)]
            else:
                normalized[key] = []
        return normalized


def _parse_time_obj(value):
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return None
    return None


def _ensure_time_string(entry, parsed_time):
    if entry.get('time') or not parsed_time:
        return
    entry['time'] = parsed_time.strftime('%d/%m %H:%M')


def _build_handicap_filter_predicate(handicap_filter):
    if not handicap_filter:
        return None
    try:
        target_bucket = normalize_handicap_to_half_bucket_str(handicap_filter)
        if target_bucket is None:
            return None
        target_float = float(target_bucket)
    except Exception:
        return None

    use_range = abs(target_float) >= 2.0 and target_float != 0.0

    def predicate(raw_value):
        hv = normalize_handicap_to_half_bucket_str(raw_value or '')
        if hv is None:
            return False
        if not use_range:
            return hv == target_bucket
        hv_float = float(hv)
        if target_float > 0:
            return hv_float > 0 and hv_float >= target_float
        return hv_float < 0 and hv_float <= target_float

    return predicate


def _normalize_goal_line_option_str(value):
    try:
        parsed = _parse_handicap_to_float(value)
    except Exception:
        parsed = None
    if parsed is None:
        return None
    text = f"{parsed:.2f}"
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def _build_goal_line_filter_predicate(goal_line_filter):
    if not goal_line_filter:
        return None
    try:
        target_value = _parse_handicap_to_float(goal_line_filter)
    except Exception:
        target_value = None
    if target_value is None:
        return None
    use_range = target_value >= 4.0

    def predicate(raw_value):
        try:
            current_value = _parse_handicap_to_float(raw_value or '')
        except Exception:
            current_value = None
        if current_value is None:
            return False
        if not use_range:
            return abs(current_value - target_value) < 1e-6
        return current_value >= target_value

    return predicate


def _build_handicap_options_from_lists(match_lists):
    values = set()
    for dataset in match_lists:
        for entry in dataset or []:
            if not isinstance(entry, dict):
                continue
            normalized = normalize_handicap_to_half_bucket_str(entry.get('handicap'))
            if normalized is not None:
                values.add(normalized)
    try:
        return sorted(values, key=lambda x: float(x))
    except ValueError:
        return sorted(values)


def _build_goal_line_options_from_lists(match_lists):
    values = set()
    for dataset in match_lists:
        for entry in dataset or []:
            if not isinstance(entry, dict):
                continue
            raw_value = entry.get('goal_line') or entry.get('goal_line_alt') or entry.get('goal_line_decimal')
            normalized = _normalize_goal_line_option_str(raw_value)
            if normalized is not None:
                values.add(normalized)
    try:
        return sorted(values, key=lambda x: float(x))
    except ValueError:
        return sorted(values)


def _filter_and_slice_matches(section, limit=None, offset=0, handicap_filter=None, goal_line_filter=None, sort_desc=False):
    data = load_data_from_file()
    matches = data.get(section, [])
    prepared = []
    for original in matches:
        entry = dict(original)
        parsed_time = _parse_time_obj(entry.get('time_obj'))
        entry['_sort_time'] = parsed_time or datetime.datetime.min
        _ensure_time_string(entry, parsed_time)
        prepared.append(entry)

    handicap_predicate = _build_handicap_filter_predicate(handicap_filter)
    if handicap_predicate:
        filtered = []
        for entry in prepared:
            if handicap_predicate(entry.get('handicap', '')):
                filtered.append(entry)
        prepared = filtered

    goal_predicate = _build_goal_line_filter_predicate(goal_line_filter)
    if goal_predicate:
        filtered = []
        for entry in prepared:
            if goal_predicate(entry.get('goal_line', '')):
                filtered.append(entry)
        prepared = filtered

    prepared.sort(key=lambda item: (item['_sort_time'], item.get('id', '')), reverse=sort_desc)

    offset = max(int(offset or 0), 0)
    if offset:
        if offset >= len(prepared):
            prepared = []
        else:
            prepared = prepared[offset:]

    if limit is not None:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = None
        if limit_val is not None and limit_val >= 0:
            prepared = prepared[:limit_val]

    for entry in prepared:
        entry.pop('_sort_time', None)
    return prepared


def _find_match_basic_data(match_id: str):
    if not match_id:
        return None, None
    data = load_data_from_file()
    for section in ('upcoming_matches', 'finished_matches'):
        for entry in data.get(section, []):
            if str(entry.get('id')) == str(match_id):
                return entry, section
    return None, None


def _get_preview_cache_dir():
    static_root_value = app.static_folder
    if not static_root_value:
        static_root_value = Path(__file__).resolve().parent / 'static'
    static_root = Path(static_root_value).resolve()
    return static_root / 'cached_previews'


def load_preview_from_cache(match_id: str):
    cache_dir = _get_preview_cache_dir()
    cache_path = cache_dir / f'{match_id}.json'
    if cache_path.exists():
        try:
            with cache_path.open('r', encoding='utf-8') as fh:
                cached_data = json.load(fh)
                if isinstance(cached_data, dict):
                    return cached_data
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Error al leer cache de analisis {cache_path}: {exc}")
    return None


def save_preview_to_cache(match_id: str, payload: dict):
    cache_dir = _get_preview_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f'{match_id}.json'
        with cache_path.open('w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        print(f"Error al escribir cache de analisis para {match_id}: {exc}")


def _parse_number_clean(s: str):
    if s is None:
        return None
    txt = str(s).strip()
    txt = txt.replace('−', '-')  # unicode minus
    txt = txt.replace(',', '.')
    txt = txt.replace('+', '')
    txt = txt.replace(' ', '')
    m = re.search(r"^[+-]?\d+(?:\.\d+)?$", txt)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None

def _parse_number(s: str):
    if s is None:
        return None
    # Normaliza separadores y signos
    txt = str(s).strip()
    txt = txt.replace('−', '-')  # minus unicode
    txt = txt.replace(',', '.')
    txt = txt.replace(' ', '')
    # Coincide con un número decimal con signo
    m = re.search(r"^[+-]?\d+(?:\.\d+)?$", txt)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None

def _parse_handicap_to_float(text: str):
    if text is None:
        return None
    t = str(text).strip()
    if '/' in t:
        parts = [p for p in re.split(r"/", t) if p]
        nums = []
        for p in parts:
            v = _parse_number_clean(p)
            if v is None:
                return None
            nums.append(v)
        if not nums:
            return None
        return sum(nums) / len(nums)
    # Si viene como cadena normal (ej. "+0.25" o "-0,75")
    return _parse_number_clean(t.replace('+', ''))

def _bucket_to_half(value: float) -> float:
    if value is None:
        return None
    if value == 0:
        return 0.0
    sign = -1.0 if value < 0 else 1.0
    av = abs(value)
    base = math.floor(av + 1e-9)
    frac = av - base
    # Mapea 0.25/0.75/0.5 a .5, 0.0 queda .0
    def close(a, b):
        return abs(a - b) < 1e-6
    if close(frac, 0.0):
        bucket = float(base)
    elif close(frac, 0.5) or close(frac, 0.25) or close(frac, 0.75):
        bucket = base + 0.5
    else:
        # fallback: redondeo al múltiplo de 0.5 más cercano
        bucket = round(av * 2) / 2.0
        # si cae justo en entero, desplazar a .5 para respetar la preferencia de .25/.75 → .5
        f = bucket - math.floor(bucket)
        if close(f, 0.0) and (abs(av - (math.floor(bucket) + 0.25)) < 0.26 or abs(av - (math.floor(bucket) + 0.75)) < 0.26):
            bucket = math.floor(bucket) + 0.5
    return sign * bucket

def normalize_handicap_to_half_bucket_str(text: str):
    v = _parse_handicap_to_float(text)
    if v is None:
        return None
    b = _bucket_to_half(v)
    if b is None:
        return None
    # Formato con un decimal
    return f"{b:.1f}"

def get_main_page_matches(limit=None, offset=0, handicap_filter=None, goal_line_filter=None):
    return _filter_and_slice_matches(
        'upcoming_matches',
        limit=limit,
        offset=offset,
        handicap_filter=handicap_filter,
        goal_line_filter=goal_line_filter,
        sort_desc=False,
    )


def get_main_page_finished_matches(limit=None, offset=0, handicap_filter=None, goal_line_filter=None):
    return _filter_and_slice_matches(
        'finished_matches',
        limit=limit,
        offset=offset,
        handicap_filter=handicap_filter,
        goal_line_filter=goal_line_filter,
        sort_desc=True,
    )


def _fetch_sidebar_lists(handicap_filter=None, goal_line_filter=None):
    return (
        get_main_page_matches(handicap_filter=handicap_filter, goal_line_filter=goal_line_filter),
        get_main_page_finished_matches(handicap_filter=handicap_filter, goal_line_filter=goal_line_filter),
    )


def _render_matches_dashboard(page_mode='upcoming', page_title='Partidos'):
    handicap_filter = request.args.get('handicap')
    goal_line_filter = request.args.get('ou')
    error_msg = None
    try:
        upcoming_matches, finished_matches = _fetch_sidebar_lists(handicap_filter, goal_line_filter)
    except Exception as exc:
        print(f"ERROR al cargar datos para el dashboard: {exc}")
        upcoming_matches, finished_matches = [], []
        error_msg = f"No se pudieron cargar los partidos: {exc}"

    handicap_options = _build_handicap_options_from_lists([upcoming_matches, finished_matches])
    goal_line_options = _build_goal_line_options_from_lists([upcoming_matches, finished_matches])
    active_matches = finished_matches if page_mode == 'finished' else upcoming_matches

    return render_template(
        'index.html',
        matches=active_matches,
        upcoming_matches=upcoming_matches,
        finished_matches=finished_matches,
        handicap_filter=handicap_filter,
        goal_line_filter=goal_line_filter,
        handicap_options=handicap_options,
        goal_line_options=goal_line_options,
        page_mode=page_mode,
        page_title=page_title,
        error=error_msg,
    )

@app.route('/')
def index():
    print("Recibida petici�n para Pr�ximos Partidos...")
    return _render_matches_dashboard('upcoming', 'Pr�ximos Partidos')


@app.route('/resultados')
def resultados():
    print("Recibida petici�n para Partidos Finalizados...")
    return _render_matches_dashboard('finished', 'Resultados Finalizados')


@app.route('/proximos')
def proximos():
    print("Recibida petici�n para /proximos")
    return _render_matches_dashboard('upcoming', 'Pr�ximos Partidos')

@app.route('/api/matches')
def api_matches():
    try:
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 5))
        limit = min(limit, 50)
        matches = get_main_page_matches(limit=limit, offset=offset, handicap_filter=request.args.get('handicap'), goal_line_filter=request.args.get('ou'))
        return jsonify({'matches': matches})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/finished_matches')
def api_finished_matches():
    try:
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 5))
        limit = min(limit, 50)
        matches = get_main_page_finished_matches(limit=limit, offset=offset, handicap_filter=request.args.get('handicap'), goal_line_filter=request.args.get('ou'))
        return jsonify({'matches': matches})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/preview_basico/<string:match_id>')
def api_preview_basico(match_id):
    try:
        entry, section = _find_match_basic_data(match_id)
        if not entry:
            return jsonify({'error': 'Partido no encontrado'}), 404
        payload = {
            'id': entry.get('id'),
            'section': section,
            'home_team': entry.get('home_team'),
            'away_team': entry.get('away_team'),
            'time': entry.get('time'),
            'time_obj': entry.get('time_obj'),
            'score': entry.get('score'),
            'handicap': entry.get('handicap'),
            'goal_line': entry.get('goal_line'),
            'goal_line_alt': entry.get('goalLine'),
            'goal_line_decimal': entry.get('goal_line_decimal'),
            'competition': entry.get('competition'),
        }
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'error': f'No se pudo cargar la vista previa: {exc}'}), 500


def _select_default_match_id(preloaded_upcoming, preloaded_finished):
    if preloaded_upcoming:
        return preloaded_upcoming[0].get('id')
    if preloaded_finished:
        return preloaded_finished[0].get('id')
    return None


# --- NUEVA RUTA PARA MOSTRAR EL ESTUDIO DETALLADO ---
@app.route('/estudio', defaults={'match_id': None})
@app.route('/estudio/<string:match_id>')
def mostrar_estudio(match_id):
    """
    Vista principal del estudio con barra lateral integrada.
    """
    print(f"Recibida petición para el estudio del partido ID: {match_id}")

    dataset = load_data_from_file()
    upcoming_matches = (dataset.get('upcoming_matches') or [])[:20]
    finished_matches = (dataset.get('finished_matches') or [])[:20]

    requested_match_id = match_id or request.args.get('match_id')
    target_match_id = requested_match_id or _select_default_match_id(upcoming_matches, finished_matches)

    if not target_match_id:
        abort(404, description='No hay partidos disponibles para analizar.')

    datos_partido = analizar_partido_completo(target_match_id)

    if not datos_partido or "error" in datos_partido:
        error_message = (datos_partido or {}).get('error', 'Error desconocido')
        print(f"Error al obtener datos para {target_match_id}: {error_message}")
        abort(500, description=error_message)

    datos_partido['match_id'] = target_match_id
    print(f"Datos obtenidos para {datos_partido['home_name']} vs {datos_partido['away_name']}. Renderizando plantilla...")
    return render_template(
        'estudio.html',
        data=datos_partido,
        format_ah=format_ah_as_decimal_string_of,
        upcoming_matches=upcoming_matches,
        finished_matches=finished_matches,
        selected_match_id=target_match_id
    )


@app.route('/api/estudio_panel/<string:match_id>')
def api_estudio_panel(match_id):
    """
    Devuelve el panel de análisis renderizado para actualizar la vista sin recargar la página.
    """
    start_time = time.time()
    try:
        datos_partido = analizar_partido_completo(match_id)
        if not datos_partido or "error" in datos_partido:
            error_message = (datos_partido or {}).get('error', 'No se pudo analizar el partido.')
            return jsonify({'error': error_message}), 500

        datos_partido['match_id'] = match_id
        html = render_template(
            'partials/analysis_panel.html',
            data=datos_partido,
            format_ah=format_ah_as_decimal_string_of
        )
        elapsed = round(time.time() - start_time, 2)
        payload = {
            'html': html,
            'match': {
                'id': match_id,
                'home': datos_partido.get('home_name'),
                'away': datos_partido.get('away_name'),
                'score': datos_partido.get('score'),
                'time': datos_partido.get('time')
            },
            'meta': {'elapsed': elapsed}
        }
        return jsonify(payload)
    except Exception as exc:
        logging.exception("Error generando el panel dinámico para %s", match_id)
        return jsonify({'error': f'No se pudo renderizar el análisis: {exc}'}), 500

# --- NUEVA RUTA PARA ANALIZAR PARTIDOS FINALIZADOS ---
@app.route('/analizar_partido', methods=['GET', 'POST'])
def analizar_partido():
    """
    Ruta para analizar partidos finalizados por ID.
    """
    if request.method == 'POST':
        match_id = request.form.get('match_id')
        if match_id:
            print(f"Recibida petición para analizar partido finalizado ID: {match_id}")
            cleaned_match_id = "".join(filter(str.isdigit, match_id))
            if not cleaned_match_id:
                return render_template('analizar_partido.html', error="Por favor, introduce un ID de partido válido.")

            return redirect(url_for('mostrar_estudio', match_id=cleaned_match_id))
        else:
            return render_template('analizar_partido.html', error="Por favor, introduce un ID de partido válido.")
    
    # Si es GET, mostrar el formulario
    return render_template('analizar_partido.html')

# --- NUEVA RUTA API PARA LA VISTA PREVIA RÁPIDA ---
@app.route('/api/preview/<string:match_id>')
def api_preview(match_id):
    """
    Endpoint para la vista previa ("el ojito"). Llama al scraper COMPLETO.
    Devuelve los datos en formato JSON.
    """
    try:
        preview_data = analizar_partido_completo(match_id)
        if "error" in preview_data:
            return jsonify(preview_data), 500
        return jsonify(preview_data)
    except Exception as e:
        print(f"Error en la ruta /api/preview/{match_id}: {e}")
        return jsonify({'error': 'Ocurrió un error interno en el servidor.'}), 500


@app.route('/api/analisis/<string:match_id>')
def api_analisis(match_id):
    """
    Servicio de analisis profundo bajo demanda.
    Devuelve tanto el payload complejo como el HTML simplificado.
    """
    try:
        cached_payload = load_preview_from_cache(match_id)
        if isinstance(cached_payload, dict) and cached_payload.get('home_team'):
            print(f"Devolviendo analisis cacheado para {match_id}")
            return jsonify(cached_payload)

        start_time = time.time()
        logging.warning(f"CACHE MISS para {match_id}. Iniciando análisis profundo...")

        datos = analizar_partido_completo(match_id)
        if not datos or (isinstance(datos, dict) and datos.get('error')):
            return jsonify({'error': (datos or {}).get('error', 'No se pudieron obtener datos.')}), 500

        # --- Lógica para el payload complejo (la original) ---
        def df_to_rows(df):
            rows = []
            try:
                if df is not None and hasattr(df, 'iterrows'):
                    for idx, row in df.iterrows():
                        label = str(idx)
                        label = label.replace('Shots on Goal', 'Tiros a Puerta')                                     .replace('Shots', 'Tiros')                                     .replace('Dangerous Attacks', 'Ataques Peligrosos')                                     .replace('Attacks', 'Ataques')
                        try:
                            home_val = row['Casa']
                        except Exception:
                            home_val = ''
                        try:
                            away_val = row['Fuera']
                        except Exception:
                            away_val = ''
                        rows.append({'label': label, 'home': home_val or '', 'away': away_val or ''})
            except Exception:
                pass
            return rows

        payload = {
            'match_id': match_id,
            'home_team': datos.get('home_name', ''),
            'away_team': datos.get('away_name', ''),
            'final_score': datos.get('score'),
            'match_date': datos.get('match_date'),
            'match_time': datos.get('match_time'),
            'match_datetime': datos.get('match_datetime'),
            'recent_indirect_full': {
                'last_home': None,
                'last_away': None,
                'h2h_col3': None
            },
            'comparativas_indirectas': {
                'left': None,
                'right': None
            }
        }
        
        # --- START COVERAGE CALCULATION ---
        main_odds = datos.get("main_match_odds_data")
        home_name = datos.get("home_name")
        away_name = datos.get("away_name")
        ah_actual_num = parse_ah_to_number_of(main_odds.get('ah_linea_raw', ''))
        
        favorito_actual_name = "Ninguno (línea en 0)"
        if ah_actual_num is not None:
            if ah_actual_num > 0: favorito_actual_name = home_name
            elif ah_actual_num < 0: favorito_actual_name = away_name

        def get_cover_status_vs_current(details):
            if not details or ah_actual_num is None:
                return 'NEUTRO'
            try:
                score_str = details.get('score', '').replace(' ', '').replace(':', '-')
                if not score_str or '?' in score_str:
                    return 'NEUTRO'

                h_home = details.get('home_team')
                h_away = details.get('away_team')
                
                status, _ = check_handicap_cover(score_str, ah_actual_num, favorito_actual_name, h_home, h_away, home_name)
                return status
            except Exception:
                return 'NEUTRO'
                
        # --- Análisis mejorado de H2H Rivales ---
        def analyze_h2h_rivals(home_result, away_result):
            if not home_result or not away_result:
                return None
                
            try:
                # Obtener resultados de los partidos
                home_goals = list(map(int, home_result.get('score', '0-0').split('-')))
                away_goals = list(map(int, away_result.get('score', '0-0').split('-')))
                
                # Calcular diferencia de goles
                home_goal_diff = home_goals[0] - home_goals[1]
                away_goal_diff = away_goals[0] - away_goals[1]
                
                # Comparar resultados
                if home_goal_diff > away_goal_diff:
                    return "Contra rivales comunes, el Equipo Local ha obtenido mejores resultados"
                elif away_goal_diff > home_goal_diff:
                    return "Contra rivales comunes, el Equipo Visitante ha obtenido mejores resultados"
                else:
                    return "Los rivales han tenido resultados similares"
            except Exception:
                return None
                    
            # --- Análisis de Comparativas Indirectas ---
        def analyze_indirect_comparison(result, team_name):
            if not result:
                return None
                
            try:
                # Determinar si el equipo cubrió el handicap
                status = get_cover_status_vs_current(result)
                
                if status == 'CUBIERTO':
                    return f"Contra este rival, {team_name} habría cubierto el handicap"
                elif status == 'NO CUBIERTO':
                    return f"Contra este rival, {team_name} no habría cubierto el handicap"
                else:
                    return f"Contra este rival, el resultado para {team_name} sería indeterminado"
            except Exception:
                return None
        # --- END COVERAGE CALCULATION ---

        last_home = (datos.get('last_home_match') or {})
        last_home_details = last_home.get('details') or {}
        if last_home_details:
            payload['recent_indirect_full']['last_home'] = {
                'home': last_home_details.get('home_team'),
                'away': last_home_details.get('away_team'),
                'score': (last_home_details.get('score') or '').replace(':', ' : '),
                'ah': format_ah_as_decimal_string_of(last_home_details.get('handicap_line_raw') or '-'),
                'ou': last_home_details.get('ouLine') or '-',
                'stats_rows': df_to_rows(last_home.get('stats')),
                'date': last_home_details.get('date'),
                'cover_status': get_cover_status_vs_current(last_home_details)
            }

        last_away = (datos.get('last_away_match') or {})
        last_away_details = last_away.get('details') or {}
        if last_away_details:
            payload['recent_indirect_full']['last_away'] = {
                'home': last_away_details.get('home_team'),
                'away': last_away_details.get('away_team'),
                'score': (last_away_details.get('score') or '').replace(':', ' : '),
                'ah': format_ah_as_decimal_string_of(last_away_details.get('handicap_line_raw') or '-'),
                'ou': last_away_details.get('ouLine') or '-',
                'stats_rows': df_to_rows(last_away.get('stats')),
                'date': last_away_details.get('date'),
                'cover_status': get_cover_status_vs_current(last_away_details)
            }

        h2h_col3 = (datos.get('h2h_col3') or {})
        h2h_col3_details = h2h_col3.get('details') or {}
        if h2h_col3_details and h2h_col3_details.get('status') == 'found':
            h2h_col3_details_adapted = {
                'score': f"{h2h_col3_details.get('goles_home')}:{h2h_col3_details.get('goles_away')}",
                'home_team': h2h_col3_details.get('h2h_home_team_name'),
                'away_team': h2h_col3_details.get('h2h_away_team_name')
            }
            payload['recent_indirect_full']['h2h_col3'] = {
                'home': h2h_col3_details.get('h2h_home_team_name'),
                'away': h2h_col3_details.get('h2h_away_team_name'),
                'score': f"{h2h_col3_details.get('goles_home')} : {h2h_col3_details.get('goles_away')}",
                'ah': format_ah_as_decimal_string_of(h2h_col3_details.get('handicap_line_raw') or '-'),
                'ou': h2h_col3_details.get('ou_result') or '-',
                'stats_rows': df_to_rows(h2h_col3.get('stats')),
                'date': h2h_col3_details.get('date'),
                'cover_status': get_cover_status_vs_current(h2h_col3_details_adapted),
                'analysis': analyze_h2h_rivals(last_home_details, last_away_details)
            }

        h2h_general = (datos.get('h2h_general') or {})
        h2h_general_details = h2h_general.get('details') or {}
        if h2h_general_details:
            score_text = h2h_general_details.get('res6') or ''
            cover_input = {
                'score': score_text,
                'home_team': h2h_general_details.get('h2h_gen_home'),
                'away_team': h2h_general_details.get('h2h_gen_away')
            }
            payload['recent_indirect_full']['h2h_general'] = {
                'home': h2h_general_details.get('h2h_gen_home'),
                'away': h2h_general_details.get('h2h_gen_away'),
                'score': score_text.replace(':', ' : '),
                'ah': h2h_general_details.get('ah6') or '-',
                'ou': h2h_general_details.get('ou_result6') or '-',
                'stats_rows': df_to_rows(h2h_general.get('stats')),
                'date': h2h_general_details.get('date'),
                'cover_status': get_cover_status_vs_current(cover_input) if score_text else 'NEUTRO'
            }

        comp_left = (datos.get('comp_L_vs_UV_A') or {})
        comp_left_details = comp_left.get('details') or {}
        if comp_left_details:
            payload['comparativas_indirectas']['left'] = {
                'title_home_name': datos.get('home_name'),
                'title_away_name': datos.get('away_name'),
                'home_team': comp_left_details.get('home_team'),
                'away_team': comp_left_details.get('away_team'),
                'score': (comp_left_details.get('score') or '').replace(':', ' : '),
                'ah': format_ah_as_decimal_string_of(comp_left_details.get('ah_line') or '-'),
                'ou': comp_left_details.get('ou_line') or '-',
                'localia': comp_left_details.get('localia') or '',
                'stats_rows': df_to_rows(comp_left.get('stats')),
                'cover_status': get_cover_status_vs_current(comp_left_details),
                'analysis': analyze_indirect_comparison(comp_left_details, datos.get('home_name'))
            }

        comp_right = (datos.get('comp_V_vs_UL_H') or {})
        comp_right_details = comp_right.get('details') or {}
        if comp_right_details:
            payload['comparativas_indirectas']['right'] = {
                'title_home_name': datos.get('home_name'),
                'title_away_name': datos.get('away_name'),
                'home_team': comp_right_details.get('home_team'),
                'away_team': comp_right_details.get('away_team'),
                'score': (comp_right_details.get('score') or '').replace(':', ' : '),
                'ah': format_ah_as_decimal_string_of(comp_right_details.get('ah_line') or '-'),
                'ou': comp_right_details.get('ou_line') or '-',
                'localia': comp_right_details.get('localia') or '',
                'stats_rows': df_to_rows(comp_right.get('stats')),
                'cover_status': get_cover_status_vs_current(comp_right_details),
                'analysis': analyze_indirect_comparison(comp_right_details, datos.get('away_name'))
            }

        # --- Lógica para el HTML simplificado ---
        h2h_data = datos.get("h2h_data")
        simplified_html = ""
        if all([main_odds, h2h_data, home_name, away_name]):
            simplified_html = generar_analisis_completo_mercado(main_odds, h2h_data, home_name, away_name)
        
        payload['simplified_html'] = simplified_html

        save_preview_to_cache(match_id, payload)

        end_time = time.time()
        elapsed = end_time - start_time
        logging.warning(f"[PERFORMANCE] El análisis completo para el partido {match_id} tardó {elapsed:.2f} segundos.")

        return jsonify(payload)

    except Exception as e:
        print(f"Error en la ruta /api/analisis/{match_id}: {e}")
        return jsonify({'error': 'Ocurrió un error interno en el servidor.'}), 500
@app.route('/start_analysis_background', methods=['POST'])
def start_analysis_background():
    match_id = request.json.get('match_id')
    if not match_id:
        return jsonify({'status': 'error', 'message': 'No se proporcionó match_id'}), 400

    def analysis_worker(app, match_id):
        with app.app_context():
            print(f"Iniciando análisis en segundo plano para el ID: {match_id}")
            try:
                analizar_partido_completo(match_id)
                print(f"Análisis en segundo plano finalizado para el ID: {match_id}")
            except Exception as e:
                print(f"Error en el hilo de análisis para el ID {match_id}: {e}")

    thread = threading.Thread(target=analysis_worker, args=(app, match_id))
    thread.start()

    return jsonify({'status': 'success', 'message': f'Análisis iniciado para el partido {match_id}'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) # debug=True es útil para desarrollar


