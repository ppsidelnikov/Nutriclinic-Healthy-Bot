from aiogram import Router, F
from aiogram.types import Message
from services.yandex_gpt import get_answer_from_gpt_text

router = Router(name="gpt_answer")  

@router.message()
async def answer_gpt(message: Message):
    if message.text[0] != '/':
        gpt_answer = await get_answer_from_gpt_text(message.text)
        await message.answer(f'{gpt_answer}')
