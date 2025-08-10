import sys
from pathlib import Path
import requests

PARENT_DIR = Path(__file__).parent.parent 
sys.path.append(str(PARENT_DIR))

from config.config import config

test_key = config.USDA_API_KEY
print(test_key)

search_term = "chicken breast raw"
url = "https://api.nal.usda.gov/fdc/v1/foods/search"


params = {
    "query": search_term,
    "pageSize": 5,  # количество результатов
    "api_key": test_key
}

response = requests.get(url, params=params)

if response.status_code == 200:
    data = response.json()
    for food in data["foods"]:
        fdc_id = food["fdcId"]
        description = food["description"]
        print(f"ID: {fdc_id} | Продукт: {description}")

        # Покажем основные нутриенты
        for nutrient in food.get("foodNutrients", [])[:5]:
            name = nutrient["nutrientName"]
            value = nutrient["value"]
            unit = nutrient["unitName"]
            if name in ["Energy", "Protein", "Total lipid (fat)", "Carbohydrate, by difference"]:
                print(f"  {name}: {value} {unit}")
        print("-" * 50)
else:
    print("Ошибка:", response.status_code, response.text)