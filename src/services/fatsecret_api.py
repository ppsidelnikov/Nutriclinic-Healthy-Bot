import sys
from pathlib import Path
import requests
import base64

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from config.config import config

# Твои данные (после одобрения)
CLIENT_ID = config.FATSECRET_CLIENT_ID
CLIENT_SECRET = config.FATSECRET_CLIENT_SECRET

# Кодируем client_id:client_secret в Base64
credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

url = "https://oauth.fatsecret.com/connect/token"
headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": f"Basic {credentials}"
}
data = {"grant_type": "client_credentials", "scope": "basic"}

response = requests.post(url, headers=headers, data=data)

if response.status_code == 200:
    token_data = response.json()
    access_token = token_data["access_token"]
    print("✅ Токен получен")
else:
    print("❌ Ошибка:", response.status_code, response.text)


url = "https://platform.fatsecret.com/rest/server.api"
headers = {"Authorization": f"Bearer {access_token}"}
params = {
    "method": "foods.search",
    "search_expression": "chicken breast",
    "format": "json"
}

response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    # foods = data["foods"]["food"]
    # for food in foods[:3]:
    #     name = food["food_name"]
    #     calories = food.get("calories", "N/A")
    #     serving = food.get("serving_description", "N/A")
        # print(f"🍽 {name} | {calories} ккал | {serving}")
    print(data)
else:
    print("Ошибка:", response.status_code, response.text)