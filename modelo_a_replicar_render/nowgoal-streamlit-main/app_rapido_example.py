import streamlit as st
import pandas as pd
import time
import asyncio # Necesario para llamar a extraer_datos_partido_rapido

from modules.extractor_rapido import (
    extraer_datos_partido_rapido,
    get_requests_session_of,
    get_selenium_driver_of_cached, # Usar la versión cacheada del driver
    close_selenium_driver_of,
    format_ah_as_decimal_string_of, # Para formatear algunas líneas de AH en la UI
    PLACEHOLDER_NODATA
)

# --- Configuración de la Página Streamlit ---
st.set_page_config(layout="wide", page_title="Extractor Rápido - Demo", initial_sidebar_state="expanded")

# --- Estilos CSS (simplificados de datos.py) ---
st.markdown("""
<style>
    .main-title { font-size: 2em; font-weight: bold; color: #1E90FF; text-align: center; margin-bottom: 5px; }
    .sub-title { font-size: 1.4em; text-align: center; margin-bottom: 15px; }
    .section-header { font-size: 1.6em; font-weight: bold; color: #4682B4; margin-top: 20px; margin-bottom: 10px; border-bottom: 1px solid #4682B4; padding-bottom: 3px;}
    .card-title { font-size: 1.1em; font-weight: bold; color: #333; margin-bottom: 8px; }
    .home-color { color: #007bff; font-weight: bold; }
    .away-color { color: #fd7e14; font-weight: bold; }
    .score-value { font-size: 1.1em; font-weight: bold; color: #28a745; margin: 0 3px; }
    .ah-value { font-weight: bold; color: #6f42c1; }
    .data-highlight { font-weight: bold; color: #dc3545; }
    .standings-table p { margin-bottom: 0.2rem; font-size: 0.9em;}
    .standings-table strong { min-width: 40px; display: inline-block; }
    h6 {margin-top:8px; margin-bottom:3px; font-style:italic; color: #005A9C; font-size: 0.95em;}
</style>
""", unsafe_allow_html=True)

# --- Funciones de Ayuda para la UI ---
def display_progression_stats_df(df_stats, title="Estadísticas de Progresión"):
    if df_stats is not None and not df_stats.empty:
        st.markdown(f"<h6>{title}</h6>", unsafe_allow_html=True)
        # Renombrar columnas para claridad si es necesario (ej. Casa -> Home, Fuera -> Away)
        # df_display = df_stats.rename(columns={"Casa": "H", "Fuera": "A"})
        st.dataframe(df_stats)
    else:
        st.caption(f"{title}: No disponibles.")

# --- Sidebar para Input ---
st.sidebar.title("Configuración (Extractor Rápido)")
match_id_input = st.sidebar.text_input("ID Partido Principal:", value="2696131", key="rapido_match_id_input")
use_selenium_checkbox = st.sidebar.checkbox("Usar Selenium (para cuotas, filtros, etc.)", value=True, key="rapido_use_selenium")
analizar_button = st.sidebar.button("Analizar Partido", type="primary", use_container_width=True, key="rapido_analizar_button")

# --- Contenedor Principal para Resultados ---
results_container = st.container()

if analizar_button:
    results_container.empty()
    main_match_id = None
    if match_id_input:
        try:
            main_match_id = int("".join(filter(str.isdigit, match_id_input)))
        except ValueError:
            results_container.error("ID de partido no válido.")
            st.stop()
    if not main_match_id:
        results_container.warning("Por favor, ingresa un ID de partido.")
        st.stop()

    req_session = get_requests_session_of()
    driver = None
    if use_selenium_checkbox:
        with st.spinner("Inicializando WebDriver de Selenium..."):
            driver = get_selenium_driver_of_cached()
            if not driver:
                st.sidebar.error("No se pudo inicializar Selenium. Algunas funciones estarán limitadas.")

    start_time_extraction = time.time()
    with st.spinner(f"Extrayendo datos para el partido ID: {main_match_id}..."):
        # Llamar a la función de extracción asíncrona
        datos_partido = asyncio.run(extraer_datos_partido_rapido(main_match_id, req_session, driver))
    end_time_extraction = time.time()

    if driver and use_selenium_checkbox: # Cerrar solo si se usó y se pidió usar
        # No cerrar el driver global aquí si se quiere reusar en ejecuciones subsiguientes en la misma sesión de Streamlit.
        # close_selenium_driver_of() # Esto lo cerraría permanentemente para la sesión de Streamlit.
        # Para una app real, el manejo del ciclo de vida del driver es importante.
        # Podría cerrarse al final de la sesión de Streamlit o mantenerse vivo.
        # Por ahora, para esta demo, no lo cerramos para permitir re-análisis rápidos.
        pass


    st.sidebar.success(f"Extracción completada en {end_time_extraction - start_time_extraction:.2f}s")
    st.sidebar.caption(f"Tiempo interno de extractor_rapido: {datos_partido.get('execution_time_seconds', 0):.2f}s")

    if datos_partido.get("error"):
        results_container.error(datos_partido["error"])
        st.stop()

    # --- Mostrar Datos Extraídos ---
    main_info = datos_partido.get("main_match_info", {})
    home_name = main_info.get("home_team_name", "Local")
    away_name = main_info.get("away_team_name", "Visitante")

    results_container.markdown(f"<p class='main-title'>Análisis Rápido del Partido</p>", unsafe_allow_html=True)
    results_container.markdown(f"<p class='sub-title'><span class='home-color'>{home_name}</span> vs <span class='away-color'>{away_name}</span></p>", unsafe_allow_html=True)
    results_container.caption(f"ID Partido: {main_match_id} | Liga: {main_info.get('league_name', 'N/A')}")
    results_container.divider()

    # Sección de Marcador y Cuotas
    with results_container.expander("Marcador Final y Cuotas", expanded=True):
        col_score, col_ah, col_goals = st.columns(3)
        col_score.metric("Marcador Final", main_info.get("final_score", PLACEHOLDER_NODATA))

        odds = datos_partido.get("odds", {})
        ah_line_raw = odds.get('ah_linea_raw', '?')
        ah_line_fmt = format_ah_as_decimal_string_of(ah_line_raw)
        col_ah.metric("AH Inicial", ah_line_fmt if ah_line_fmt != '?' else PLACEHOLDER_NODATA,
                      f"{odds.get('ah_home_cuota','-')}/{odds.get('ah_away_cuota','-')}")

        goals_line_raw = odds.get('goals_linea_raw', '?')
        goals_line_fmt = format_ah_as_decimal_string_of(goals_line_raw)
        col_goals.metric("Goles O/U Inicial", goals_line_fmt if goals_line_fmt != '?' else PLACEHOLDER_NODATA,
                         f"O:{odds.get('goals_over_cuota','-')} U:{odds.get('goals_under_cuota','-')}")

        if main_info.get("final_score"):
             display_progression_stats_df(main_info.get("progression_stats"), f"Progresión: {home_name} vs {away_name}")


    # Sección de Clasificación
    results_container.markdown("<h2 class='section-header'>Clasificación en Liga</h2>", unsafe_allow_html=True)
    standings_data = datos_partido.get("standings", {})
    col_stand_h, col_stand_a = results_container.columns(2)
    with col_stand_h:
        home_stand = standings_data.get("home_team", {})
        st.markdown(f"<h3 class='card-title home-color'>{home_stand.get('name', home_name)} (Rk: {home_stand.get('ranking', 'N/A')})</h3>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(f"""<div class='standings-table'>
                <p><strong>Total:</strong> PJ {home_stand.get('total_pj', '-')} | {home_stand.get('total_v', '-')}V-{home_stand.get('total_e', '-')}E-{home_stand.get('total_d', '-')}D | GF {home_stand.get('total_gf', '-')}-GC {home_stand.get('total_gc', '-')}</p>
                <p><strong>{home_stand.get('specific_type', 'Específico')}:</strong> PJ {home_stand.get('specific_pj', '-')} | {home_stand.get('specific_v', '-')}V-{home_stand.get('specific_e', '-')}E-{home_stand.get('specific_d', '-')}D | GF {home_stand.get('specific_gf', '-')}-GC {home_stand.get('specific_gc', '-')}</p>
            </div>""", unsafe_allow_html=True)
    with col_stand_a:
        away_stand = standings_data.get("away_team", {})
        st.markdown(f"<h3 class='card-title away-color'>{away_stand.get('name', away_name)} (Rk: {away_stand.get('ranking', 'N/A')})</h3>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(f"""<div class='standings-table'>
                <p><strong>Total:</strong> PJ {away_stand.get('total_pj', '-')} | {away_stand.get('total_v', '-')}V-{away_stand.get('total_e', '-')}E-{away_stand.get('total_d', '-')}D | GF {away_stand.get('total_gf', '-')}-GC {away_stand.get('total_gc', '-')}</p>
                <p><strong>{away_stand.get('specific_type', 'Específico')}:</strong> PJ {away_stand.get('specific_pj', '-')} | {away_stand.get('specific_v', '-')}V-{away_stand.get('specific_e', '-')}E-{away_stand.get('specific_d', '-')}D | GF {away_stand.get('specific_gf', '-')}-GC {away_stand.get('specific_gc', '-')}</p>
            </div>""", unsafe_allow_html=True)
    results_container.divider()

    # Sección de Últimos Partidos y H2H Indirecto Col3
    results_container.markdown("<h2 class='section-header'>Rendimiento Reciente y H2H Rivales (Col3)</h2>", unsafe_allow_html=True)
    col_last_h, col_last_a, col_h2h_c3 = results_container.columns(3)

    last_matches_data = datos_partido.get("last_matches", {})
    with col_last_h, st.container(border=True):
        lh_match = last_matches_data.get("home_team_last_home")
        st.markdown(f"<h4 class='card-title'>Último <span class='home-color'>{home_name}</span> (Casa)</h4>", unsafe_allow_html=True)
        if lh_match:
            st.markdown(f"🆚 <span class='away-color'>{lh_match.get('away_team')}</span>: <span class='score-value'>{lh_match.get('score','N/A').replace('-',':')}</span>", unsafe_allow_html=True)
            st.markdown(f"AH: <span class='ah-value'>{format_ah_as_decimal_string_of(lh_match.get('handicap_line_raw','-'))}</span> | 📅 {lh_match.get('date', 'N/A')}", unsafe_allow_html=True)
            display_progression_stats_df(lh_match.get("progression_stats"), f"Progresión: {lh_match.get('home_team')} vs {lh_match.get('away_team')}")
        else:
            st.info(f"No disponible para {home_name} (Casa).")

    with col_last_a, st.container(border=True):
        la_match = last_matches_data.get("away_team_last_away")
        st.markdown(f"<h4 class='card-title'>Último <span class='away-color'>{away_name}</span> (Fuera)</h4>", unsafe_allow_html=True)
        if la_match:
            st.markdown(f"🆚 <span class='home-color'>{la_match.get('home_team')}</span>: <span class='score-value'>{la_match.get('score','N/A').replace('-',':')}</span>", unsafe_allow_html=True)
            st.markdown(f"AH: <span class='ah-value'>{format_ah_as_decimal_string_of(la_match.get('handicap_line_raw','-'))}</span> | 📅 {la_match.get('date', 'N/A')}", unsafe_allow_html=True)
            display_progression_stats_df(la_match.get("progression_stats"), f"Progresión: {la_match.get('home_team')} vs {la_match.get('away_team')}")
        else:
            st.info(f"No disponible para {away_name} (Fuera).")

    with col_h2h_c3, st.container(border=True):
        h2h_c3 = datos_partido.get("h2h_indirect_col3", {})
        rival_info_c3 = datos_partido.get("rival_info_for_col3", {})
        r_a_name = rival_info_c3.get("rival_a",{}).get("name", "Rival A")
        r_b_name = rival_info_c3.get("rival_b",{}).get("name", "Rival B")
        st.markdown(f"<h4 class='card-title'>H2H Rivales (<span class='home-color'>{r_a_name}</span> vs <span class='away-color'>{r_b_name}</span>)</h4>", unsafe_allow_html=True)
        if h2h_c3.get("status") == "found":
            h2h_c3_home = h2h_c3.get('h2h_home_team_name', 'Local H2H')
            h2h_c3_away = h2h_c3.get('h2h_away_team_name', 'Visitante H2H')
            st.markdown(f"<span class='home-color'>{h2h_c3_home}</span> <span class='score-value'>{h2h_c3.get('goles_home', '?')}:{h2h_c3.get('goles_away', '?')}</span> <span class='away-color'>{h2h_c3_away}</span>", unsafe_allow_html=True)
            st.markdown(f"AH: <span class='ah-value'>{format_ah_as_decimal_string_of(h2h_c3.get('handicap','-'))}</span>", unsafe_allow_html=True)
            display_progression_stats_df(h2h_c3.get("progression_stats"), f"Progresión H2H Col3")
        else:
            st.info(h2h_c3.get('resultado', f"No disponible o error."))
    results_container.divider()

    # H2H Directos
    with results_container.expander("H2H Directos", expanded=False):
        h2h_direct_data = datos_partido.get("h2h_direct", {})
        h2h_home = h2h_direct_data.get("home_at_home", {})
        h2h_gen = h2h_direct_data.get("general_last", {})

        st.markdown(f"**<span class='home-color'>{home_name}</span> en Casa vs <span class='away-color'>{away_name}</span>:** "
                    f"Resultado <span class='score-value'>{h2h_home.get('score', 'N/A')}</span>, "
                    f"AH <span class='ah-value'>{h2h_home.get('ah_line', 'N/A')}</span> "
                    f"(ID: {h2h_home.get('match_id', 'N/A')})", unsafe_allow_html=True)
        display_progression_stats_df(h2h_home.get("progression_stats"), f"Progresión H2H (Local en Casa)")

        st.markdown(f"**Último General (<span class='home-color'>{h2h_gen.get('home_team_name', 'N/A')}</span> vs <span class='away-color'>{h2h_gen.get('away_team_name', 'N/A')}</span>):** "
                    f"Resultado <span class='score-value'>{h2h_gen.get('score', 'N/A')}</span>, "
                    f"AH <span class='ah-value'>{h2h_gen.get('ah_line', 'N/A')}</span> "
                    f"(ID: {h2h_gen.get('match_id', 'N/A')})", unsafe_allow_html=True)
        display_progression_stats_df(h2h_gen.get("progression_stats"), f"Progresión H2H (General)")

    # Comparativas Indirectas
    with results_container.expander("Comparativas Indirectas", expanded=False):
        comp_matches = datos_partido.get("comparative_matches", {})
        comp_L_UVA = comp_matches.get("home_vs_last_opponent_of_away", {})
        comp_V_ULH = comp_matches.get("away_vs_last_opponent_of_home", {})

        if comp_L_UVA:
            st.markdown(f"**<span class='home-color'>{home_name}</span> vs Últ. Rival de <span class='away-color'>{away_name}</span> ({comp_L_UVA.get('home_team','L')} vs {comp_L_UVA.get('away_team','V')}):** "
                        f"Res <span class='score-value'>{comp_L_UVA.get('score', 'N/A')}</span>, "
                        f"AH <span class='ah-value'>{format_ah_as_decimal_string_of(comp_L_UVA.get('ah_line', '-'))}</span>, "
                        f"Localía de {home_name}: <span class='data-highlight'>{comp_L_UVA.get('localia', '-')}</span> "
                        f"(ID: {comp_L_UVA.get('match_id')})", unsafe_allow_html=True)
            display_progression_stats_df(comp_L_UVA.get("progression_stats"), f"Progresión Comp. L vs UV_A")
        else:
            st.caption(f"Comparativa '{home_name} vs Últ. Rival de {away_name}' no disponible.")

        if comp_V_ULH:
            st.markdown(f"**<span class='away-color'>{away_name}</span> vs Últ. Rival de <span class='home-color'>{home_name}</span> ({comp_V_ULH.get('home_team','L')} vs {comp_V_ULH.get('away_team','V')}):** "
                        f"Res <span class='score-value'>{comp_V_ULH.get('score', 'N/A')}</span>, "
                        f"AH <span class='ah-value'>{format_ah_as_decimal_string_of(comp_V_ULH.get('ah_line', '-'))}</span>, "
                        f"Localía de {away_name}: <span class='data-highlight'>{comp_V_ULH.get('localia', '-')}</span> "
                        f"(ID: {comp_V_ULH.get('match_id')})", unsafe_allow_html=True)
            display_progression_stats_df(comp_V_ULH.get("progression_stats"), f"Progresión Comp. V vs UL_H")
        else:
            st.caption(f"Comparativa '{away_name} vs Últ. Rival de {home_name}' no disponible.")

    # Raw data expander
    with results_container.expander("Raw Data Extraída (JSON)", expanded=False):
        # Convertir DataFrames a diccionarios para serialización JSON en st.json
        # Esto es solo un ejemplo, la serialización de DataFrames puede ser más compleja
        # o se pueden mostrar de otra manera.

        # Clona datos_partido para no modificar el original
        import copy
        data_for_json = copy.deepcopy(datos_partido)

        # Itera y convierte DataFrames a dict (o a string como placeholder)
        for top_key, top_value in data_for_json.items():
            if isinstance(top_value, dict):
                for sub_key, sub_value in top_value.items():
                    if isinstance(sub_value, dict) and isinstance(sub_value.get("progression_stats"), pd.DataFrame):
                        sub_value["progression_stats"] = sub_value["progression_stats"].to_dict() if not sub_value["progression_stats"].empty else "DataFrame Vacío"
                    elif isinstance(sub_value, pd.DataFrame): # Caso de stats del partido principal
                         top_value[sub_key] = sub_value.to_dict() if not sub_value.empty else "DataFrame Vacío"


        st.json(data_for_json)

else:
    results_container.info("Ingresa un ID de partido y haz clic en 'Analizar Partido'.")

# Consideración sobre el ciclo de vida del driver de Selenium:
# Si se quiere que el driver persista entre ejecuciones del botón "Analizar Partido"
# dentro de la misma sesión de Streamlit, NO se debe llamar a close_selenium_driver_of()
# hasta que la sesión de Streamlit termine o el usuario lo indique.
# get_selenium_driver_of_cached() ya maneja la creación única.
# Para una app desplegada, se podría añadir un botón "Cerrar Selenium" o manejarlo
# con la gestión de sesión de Streamlit si es necesario liberar recursos.
# En este ejemplo, se mantiene vivo mientras la app Streamlit esté activa.
# Si `close_selenium_driver_of()` se llamara después de cada extracción,
# la siguiente extracción con Selenium volvería a inicializarlo (costoso).
# Si no se cierra nunca, podría dejar procesos huérfanos al cerrar la app Streamlit.
# Una mejor práctica sería manejarlo con st.session_state para cerrarlo al final.

if 'selenium_driver_initialized_rapido' not in st.session_state:
    st.session_state.selenium_driver_initialized_rapido = False

if use_selenium_checkbox and analizar_button and get_selenium_driver_of_cached():
    st.session_state.selenium_driver_initialized_rapido = True

# Intento de cerrar el driver al salir de la app (puede no funcionar en todos los entornos de Streamlit)
# Esto es más un hack, Streamlit no tiene un "on_stop" hook oficial robusto.
# La mejor manera es un botón explícito o confiar en que el sistema operativo limpie procesos.
def cleanup_driver():
    if st.session_state.get('selenium_driver_initialized_rapido', False):
        print("Cerrando driver de Selenium desde cleanup_driver (app_rapido_example)...")
        close_selenium_driver_of()
        st.session_state.selenium_driver_initialized_rapido = False

# Este registro de atexit es problemático con Streamlit, ya que Streamlit maneja su propio ciclo de vida.
# import atexit
# atexit.register(cleanup_driver)
# Mejor no usar atexit con Streamlit.
# Dejar el cierre manual o confiar en que el driver cacheado se cierre cuando el proceso Python termine.
# O un botón de "Limpiar Recursos" en la UI.
