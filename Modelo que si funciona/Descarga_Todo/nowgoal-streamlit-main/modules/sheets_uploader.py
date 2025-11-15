import streamlit as st
import tempfile
from typing import List, Dict

from modules.bulk_sheets_scraper import process_ranges


def _parse_ranges(text: str) -> List[Dict[str, int]]:
    ranges: List[Dict[str, int]] = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 1:
            continue
        id_part = parts[0]
        label = " ".join(parts[1:]) if len(parts) > 1 else ""
        if '-' not in id_part:
            continue
        start_str, end_str = id_part.split('-', 1)
        try:
            start = int(start_str)
            end = int(end_str)
        except ValueError:
            continue
        ranges.append({'start_id': start, 'end_id': end, 'label': label})
    return ranges


def display_sheets_uploader_ui():
    st.header("📤 Carga masiva a Google Sheets")

    cred_file = st.file_uploader("Credenciales (.json)", type="json")
    sheet_name = st.text_input("Nombre del Spreadsheet")
    sheet_neg = st.text_input("Hoja para AH <= 0", value="Locales")
    sheet_pos = st.text_input("Hoja para AH > 0", value="Visitantes")
    ranges_text = st.text_area(
        "Rangos de IDs (formato: inicio-fin etiqueta opcional)", height=150
    )
    workers = st.number_input("Número de Workers", min_value=1, max_value=5, value=3)

    if st.button("Procesar y subir"):
        if not cred_file or not sheet_name or not ranges_text.strip():
            st.error("⚠️ Debes proporcionar credenciales, nombre de sheet e IDs.")
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
            tmp.write(cred_file.getvalue())
            creds_path = tmp.name
        ranges = _parse_ranges(ranges_text)
        if not ranges:
            st.warning("No se pudieron interpretar los rangos de IDs.")
            return
        with st.spinner("Procesando..."):
            try:
                process_ranges(creds_path, sheet_name, sheet_neg, sheet_pos, ranges, max_workers=int(workers))
                st.success("Proceso finalizado. Revisa tu Google Sheet.")
            except Exception as e:
                st.error(f"Error en el proceso: {e}")

