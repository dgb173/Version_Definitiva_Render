import asyncio
import json

# Importamos la función principal de scraping
from scraping_logic import fetch_and_process_data

async def main():
    """
    Función principal que ejecuta el scraper y guarda los resultados.
    """
    print("Iniciando el proceso de scraping principal...")
    
    # Obtenemos los partidos próximos y los finalizados con una sola llamada
    proximos, finalizados = await fetch_and_process_data()
    
    print(f"Scraping finalizado. {len(proximos)} partidos próximos y {len(finalizados)} finalizados.")

    # Creamos un diccionario con todos los datos
    scraped_data = {
        "upcoming_matches": proximos,
        "finished_matches": finalizados
    }
    
    # Guardamos los datos en el archivo data.json
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, indent=2, ensure_ascii=False)
    
    print("Archivo data.json guardado correctamente.")

if __name__ == "__main__":
    asyncio.run(main())