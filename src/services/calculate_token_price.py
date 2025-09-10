price_list = {
    'gpt-5' : {'input' : 306, 'output' : 2448},
    'gpt-5-mini' : {'input' : 61.2, 'output' : 489.6},
    'gpt-5-nano' : {'input' : 12.24, 'output' : 97.92},
    'gpt-4.1' : {'input' : 489.6, 'output' : 1958.4},
    'gpt-4.1-mini' : {'input' : 97.92, 'output' : 391.68},
    'gpt-4.1-nano' : {'input' : 24.48, 'output' : 97.92},
    'gpt-4o' : {'input' : 612, 'output' : 2448},
    'gpt-4o-mini' : {'input' : 36.72, 'output' : 146.88},
    'gemini-2.5-pro' : {'input' : 306, 'output' : 2448},
    'gpt-2.5-flash' : {'input' : 73.44, 'output' : 612},
    'o4-mini' : {'input' : 269.28, 'output' : 1077.12},
    'o3' : {'input' : 576, 'output' : 1600},
    'o3-pro' : {'input' : 2400, 'output' : 9600},
}

def get_model_call_price(model, input_tokens, output_tokens, price_list=price_list):
    try:
        return round((price_list[model]['input'] / 10e6) * input_tokens + (price_list[model]['output'] / 10e6) * output_tokens, 4)
    except:
        raise ValueError("Модель не найдена в списке с ценами")