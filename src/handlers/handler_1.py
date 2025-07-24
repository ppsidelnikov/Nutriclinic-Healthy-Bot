from aiogram import Router, F
from aiogram.types import Message

router = Router(name="base")  

@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("Привет!")

@router.message(F.text == "/help")
async def help(message: Message):
    await message.answer('''
Основные команды бота:                                        
                         ''')