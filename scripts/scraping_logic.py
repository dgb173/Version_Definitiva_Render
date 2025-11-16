# scripts/scraping_logic.py
import asyncio
import json
import re
import cloudscraper
from datetime import datetime, timedelta

# --- CONFIGURACIÓN ---
JS_URL = "https://live20.nowgoal25.com/gf/data/bf_en-idn.js"
REQUEST_TIMEOUT_SECONDS = 15
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    "Referer": "https://live20.nowgoal25.com/",
}

# --- LÓGICA DE SCRAPING ---

def _get_session():
    """Crea y devuelve una sesión de cloudscraper."""
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

def _fetch_js_data_sync():
    """Descarga el contenido del archivo JS de datos."""
    session = _get_session()
    try:
        response = session.get(JS_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error al descargar los datos del JS: {e}")
        return None

def _sanitize_js_content(js_content):
    """Limpia el contenido del JS para convertirlo en un JSON válido."""
    # Extraer el bloque de asignaciones del array A
    match = re.search(r"(A\[\d+\].*?B\[\d+\])", js_content, re.DOTALL)
    if not match:
        print("No se pudo encontrar el bloque de datos 'A' en el contenido JS.")
        return None

    # El contenido que nos interesa termina antes de la primera asignación de B
    array_content = match.group(1).split("B[")[0]
    
    # Extraer cada asignación individual de A
    array_items = re.findall(r"A\[\d+\]=\[(.*?)\];", array_content)
    if not array_items:
        print("No se encontraron items en el array 'A'.")
        return None
        
    # Construir un string JSON a partir de los items
    json_string = "[" + ",".join([f"[{item}]" for item in array_items]) + "]"

    # Realizar reemplazos para que sea un JSON válido
    json_string = json_string.replace("'", '"')
    # Manejar casos como <font color=...> que no usan comillas
    json_string = re.sub(r'<font color=([^>]+)>', r'<font color=\\"\1\\">', json_string)
    json_string = re.sub(r',,', ',null,', json_string)
    json_string = re.sub(r',,', ',null,', json_string)
    json_string = re.sub(r'\[,', '[null,', json_string)
    json_string = re.sub(r',\]', ',null]', json_string)

    return json_string

def _parse_sanitized_json(json_string):
    """Parsea el string JSON saneado."""
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        print(f"Error al decodificar el JSON: {e}")
        # Opcional: encontrar el lugar del error para depurar
        # print(f"Error cerca de: {json_string[e.pos-20:e.pos+20]}")
        return None

def _process_match_data(all_matches):
    """Procesa la lista de partidos para dividirlos y darles el formato correcto."""
    upcoming_matches = []
    finished_matches = []

    for match_data in all_matches:
        try:
            state = match_data[8]
            
            # Mapeo de datos basado en el análisis del archivo JS
            match_dict = {
                "id": match_data[0],
                "home_team": match_data[4],
                "away_team": match_data[5],
                "handicap": match_data[21],
                "goal_line": match_data[25],
                "state": state,
            }

            # Partidos finalizados (state == -1)
            if state == -1:
                match_dict["score"] = f"{match_data[9]}-{match_data[10]}"
                time_str = match_data[6]
                try:
                    time_obj = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    match_dict["time_obj"] = time_obj.isoformat()
                    match_dict["time"] = (time_obj + timedelta(hours=1)).strftime('%d/%m %H:%M')
                except (ValueError, TypeError):
                    match_dict["time_obj"] = None
                    match_dict["time"] = "N/A"
                finished_matches.append(match_dict)

            # Partidos próximos (state < 8 y no finalizado)
            elif state is not None and state < 8:
                time_str = match_data[6]
                try:
                    time_obj = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    match_dict["time_obj"] = time_obj.isoformat()
                    match_dict["time"] = (time_obj + timedelta(hours=1)).strftime('%H:%M')
                except (ValueError, TypeError):
                    match_dict["time_obj"] = None
                    match_dict["time"] = "N/A"
                upcoming_matches.append(match_dict)

        except (IndexError, TypeError) as e:
            # print(f"Error procesando un partido, saltando: {e} - Datos: {match_data}")
            continue
            
    # Ordenar las listas
    upcoming_matches.sort(key=lambda x: x.get('time_obj') or '')
    finished_matches.sort(key=lambda x: x.get('time_obj') or '', reverse=True)

    return upcoming_matches, finished_matches

async def fetch_and_process_data():
    """Función principal asíncrona que orquesta todo el proceso."""
    print("Descargando y procesando datos desde el archivo JS...")
    
    # Ejecutar la descarga en un hilo separado para no bloquear el loop de asyncio
    js_content = await asyncio.to_thread(_fetch_js_data_sync)
    if not js_content:
        return [], []

    print("Saneando contenido JS...")
    sanitized_string = _sanitize_js_content(js_content)
    if not sanitized_string:
        return [], []

    print("Parseando datos JSON...")
    all_matches_data = _parse_sanitized_json(sanitized_string)
    if not all_matches_data:
        return [], []

    print("Procesando y clasificando partidos...")
    upcoming, finished = _process_match_data(all_matches_data)
    
    return upcoming, finished

# Este bloque es para permitir pruebas directas del script
if __name__ == '__main__':
    async def test_run():
        upcoming, finished = await fetch_and_process_data()
        print(f"\n--- Muestra de Partidos Próximos ({len(upcoming)}) ---")
        for match in upcoming[:5]:
            print(f"ID: {match['id']}, {match['home_team']} vs {match['away_team']}, Handicap: {match['handicap']}")
        
        print(f"\n--- Muestra de Partidos Finalizados ({len(finished)}) ---")
        for match in finished[:5]:
            print(f"ID: {match['id']}, {match['home_team']} vs {match['away_team']}, Score: {match['score']}, Handicap: {match['handicap']}")

    asyncio.run(test_run())