# Fichero: modules/handicap_analyzer.py

import streamlit as st
import time
import re
import pandas as pd
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- Configuración para un funcionamiento más rápido y limpio ---
logging.getLogger('selenium').setLevel(logging.CRITICAL)
logging.getLogger('webdriver_manager').setLevel(logging.CRITICAL)

@st.cache_resource(show_spinner="Configurando el navegador web (headless)...")
def setup_driver():
    """Configura el WebDriver de Selenium para un rendimiento óptimo. Usamos cache_resource para no reinstanciarlo en cada re-render."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def convert_handicap_to_float(handicap_str):
    if not handicap_str or not isinstance(handicap_str, str): return 0.0
    if '/' in handicap_str:
        try:
            parts = handicap_str.split('/')
            return (float(parts[0]) + float(parts[1])) / 2
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(handicap_str)
    except (ValueError, TypeError):
        return 0.0

def determine_ah_winner(home_score, away_score, handicap_float):
    adjusted_score = home_score + handicap_float
    if adjusted_score > away_score: return "HOME_WIN"
    if adjusted_score < away_score: return "AWAY_WIN"
    return "PUSH"

def parse_matches_table(soup, table_id):
    table = soup.select_one(f'table#{table_id}')
    if not table: return []
    
    matches = []
    # Usar el selector CSS correcto para las filas que contienen partidos
    rows = table.select('tr[id^="tr"][info]')
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 13: continue

        try:
            home_team = cells[2].get_text(strip=True)
            score_text_element = cells[3].select_one('span[class*="fscore"]')
            if not score_text_element: continue
            score_text = score_text_element.get_text(strip=True)
            
            away_team = cells[4].get_text(strip=True)
            handicap_str = cells[10].get_text(strip=True)
            
            score_match = re.match(r'(\d+)-(\d+)', score_text)
            if not score_match: continue
                
            home_score, away_score = map(int, score_match.groups())
            handicap_val = convert_handicap_to_float(handicap_str)
            ah_result = determine_ah_winner(home_score, away_score, handicap_val)

            matches.append({
                "home_team": home_team, "away_team": away_team,
                "home_score": home_score, "away_score": away_score,
                "handicap_line": handicap_val, "ah_result": ah_result
            })
        except (AttributeError, IndexError):
            continue
    return matches

def analyze_performance(matches, team_name, condition):
    count_total = 0
    count_covered = 0
    
    # Asignamos hándicaps ligeramente más laxos para capturar más escenarios
    home_fav_cond = lambda m: m['home_team'] == team_name and m['handicap_line'] < -0.1
    away_underdog_cond = lambda m: m['away_team'] == team_name and m['handicap_line'] > -0.1

    check_condition = home_fav_cond if condition == 'home_fav' else away_underdog_cond
    cover_condition = lambda m: m['ah_result'] == 'HOME_WIN' if condition == 'home_fav' else m['ah_result'] in ['AWAY_WIN', 'PUSH']

    for match in matches:
        if check_condition(match):
            count_total += 1
            if cover_condition(match):
                count_covered += 1
    
    return count_covered, count_total

def find_common_opponents(home_team_matches, away_team_matches, home_team_name, away_team_name):
    home_opps = {m['away_team'] if m['home_team'] == home_team_name else m['home_team']: m for m in home_team_matches}
    away_opps = {m['away_team'] if m['home_team'] == away_team_name else m['home_team']: m for m in away_team_matches}
    
    common_keys = set(home_opps.keys()) & set(away_opps.keys())
    results = []
    
    for opponent in common_keys:
        home_match = home_opps[opponent]
        away_match = away_opps[opponent]
        
        team1_covered = (home_match['home_team'] == home_team_name and home_match['ah_result'] == 'HOME_WIN') or \
                        (home_match['away_team'] == home_team_name and home_match['ah_result'] in ['AWAY_WIN', 'PUSH'])
        
        team2_covered = (away_match['home_team'] == away_team_name and away_match['ah_result'] == 'HOME_WIN') or \
                        (away_match['away_team'] == away_team_name and away_match['ah_result'] in ['AWAY_WIN', 'PUSH'])

        results.append({
            "Rival Común": opponent,
            f"Resultado vs {home_team_name}": f"{home_match['home_score']}-{home_match['away_score']} (H: {home_match['handicap_line']})",
            f"Cubrió AH": "✅ Sí" if team1_covered else "❌ No",
            f"Resultado vs {away_team_name}": f"{away_match['home_score']}-{away_match['away_score']} (H: {away_match['handicap_line']})",
            f"Cubrió AH ": "✅ Sí" if team2_covered else "❌ No" #Espacio extra en la key para evitar colisiones
        })
    return pd.DataFrame(results) if results else pd.DataFrame()


# Función que muestra la UI de Streamlit
def display_handicap_analyzer_ui():
    st.header("🔎 Analizador de Hándicap Asiático")
    st.info("Esta herramienta extrae y analiza el rendimiento de dos equipos contra el hándicap asiático (Bet365), basándose en su situación actual (favorito en casa vs. no favorito fuera).")

    match_id = st.text_input("Introduce el ID del partido de Nowgoal:", placeholder="Ej: 2607237")

    if st.button("🚀 Analizar Partido", key="analyze_button"):
        if match_id and match_id.isdigit():
            driver = setup_driver()
            try:
                with st.spinner(f"Accediendo al partido {match_id} y extrayendo datos... Esto puede tardar unos segundos."):
                    url = f"https://live19.nowgoal25.com/match/h2h-{match_id}"
                    driver.get(url)
                    WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.ID, "table_v3")))
                    time.sleep(1) 
                    soup = BeautifulSoup(driver.page_source, 'html.parser')

                st.success("Extracción completada. Analizando datos...")

                # ---- Extracción de Información y Análisis ----
                home_team_name = soup.select_one('.home .sclassName').get_text(strip=True)
                away_team_name = soup.select_one('.guest .sclassName').get_text(strip=True)
                handicap_actual_str = soup.select_one('#handicapGuess').get_text(strip=True)
                handicap_actual_val = convert_handicap_to_float(handicap_actual_str)

                home_team_recent = parse_matches_table(soup, 'table_v1')
                away_team_recent = parse_matches_table(soup, 'table_v2')

                st.subheader(f"⚽ Partido: {home_team_name} vs {away_team_name}")
                st.metric(label="Hándicap Asiático Actual (Bet365)", value=f"{home_team_name} ({handicap_actual_val})", delta_color="off")
                
                st.markdown("---")
                st.subheader("📈 Rendimiento Situacional Clave")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown(f"#### 🏠 Rendimiento de {home_team_name} (Favorito en Casa)")
                    covered_home, total_home = analyze_performance(home_team_recent, home_team_name, 'home_fav')
                    if total_home > 0:
                        percentage_home = (covered_home / total_home * 100)
                        st.metric(label=f"Ha cubierto el hándicap en:", 
                                  value=f"{covered_home} de {total_home} veces",
                                  delta=f"{percentage_home:.1f}%")
                    else:
                        st.warning("No hay suficientes datos como favorito en casa.")

                with col2:
                    st.markdown(f"#### ✈️ Rendimiento de {away_team_name} (No Favorito Visitante)")
                    covered_away, total_away = analyze_performance(away_team_recent, away_team_name, 'away_underdog')
                    if total_away > 0:
                        percentage_away = (covered_away / total_away * 100)
                        st.metric(label=f"Ha cubierto el hándicap en:",
                                  value=f"{covered_away} de {total_away} veces",
                                  delta=f"{percentage_away:.1f}%")
                    else:
                        st.warning("No hay suficientes datos como no favorito visitante.")
                        
                st.markdown("---")
                st.subheader("⚔️ Comparativa vs. Rivales Comunes")
                
                common_df = find_common_opponents(home_team_recent, away_team_recent, home_team_name, away_team_name)
                
                if not common_df.empty:
                    st.dataframe(common_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No se encontraron rivales comunes en los últimos 20 partidos de cada equipo.")

            except Exception as e:
                st.error(f"❌ Ocurrió un error inesperado: {e}")
                st.warning("Verifica el ID del partido o intenta de nuevo. A veces la web puede ser inestable.")
            finally:
                driver.quit()
        else:
            st.warning("Por favor, introduce un ID de partido válido (solo números).")
