import requests
import json

# Probar la API de preview con un ID real del archivo data.json
match_id = "2776232"  # ID que existe en el archivo data.json
url = f"http://127.0.0.1:8080/api/preview/{match_id}"

try:
    response = requests.get(url, timeout=30)  # Añadimos timeout para evitar esperas infinitas
    print("Status Code:", response.status_code)
    print("Response Headers:", dict(response.headers))
    print("Response Text:", response.text)
    
    # Intentar parsear como JSON
    try:
        data = response.json()
        print("Response JSON (first 1000 chars):", json.dumps(data, indent=2, ensure_ascii=False)[:1000])
    except Exception as e:
        print("Error parsing JSON:", e)
        
except requests.exceptions.ConnectionError:
    print("La aplicación no parece estar corriendo en http://127.0.0.1:8080")
    print("Asegúrate de que has iniciado la aplicación con 'py app.py'")
except Exception as e:
    print("Error making request:", e)