# Fichero: app.py (CORREGIDO Y ACTUALIZADO)

import streamlit as st
from modules.datos import display_other_feature_ui
from modules.estudio import display_other_feature_ui2



def main():
    st.set_page_config(
        page_title="Con este programa me hare abundante!!!",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("⚽📊 App de Análisis de Datos y Herramientas 📊⚽")
    st.markdown("""
    Bienvenido a la aplicación central. Usa el menú lateral para navegar entre las diferentes herramientas disponibles.
    """)

    st.sidebar.header("🛠️ Herramientas Disponibles")
    
    tool_options = (
        "Entreno",
        "Analisis"
    )
    
    selected_tool = st.sidebar.radio(
        "Selecciona una herramienta:",
        tool_options,
        key="main_tool_selection" 
    )

    # Ahora las condiciones coincidirán perfectamente con las opciones
    if selected_tool == "Entreno":
        display_other_feature_ui2()
    elif selected_tool == "Analisis":
        display_other_feature_ui() 

if __name__ == "__main__":
    main()
