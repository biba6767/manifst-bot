import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup


def get_bot_token() -> str:
    for env_name in ("API_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    raise RuntimeError(
        "Telegram bot token is missing. Set API_BOT_TOKEN or BOT_TOKEN environment variable."
    )


API_BOT_TOKEN = get_bot_token()
bot = Bot(token=API_BOT_TOKEN)
dp = Dispatcher()


def main_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Создать объявление"), KeyboardButton(text="Мой профиль")],
        [KeyboardButton(text="Продвижение"), KeyboardButton(text="Поддержка")],
        [KeyboardButton(text="Сообщение")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


async def on_startup() -> None:
    print("Бот запущен и готов к работе!")
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    text = (
        "С возвращением,\n\n"
        "Отличное начало! Продолжайте добавлять объявления.\n\n"
        "Ваша статистика:\n"
        "📊 Объявлений: 4\n"
        "💰 Баланс: 0 KZT\n\n"
        "Наши каналы:\n"
        "🚲 Веломаркет @CineleKz\n"
        "🖥️ Техномаркет @CineleTechnoKz\n\n"
        "Выберите действие из меню ниже:"
    )
    await message.answer(text, reply_markup=main_menu())


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Это бот-манифест. Он помогает добавлять объявления, следить за балансом и управлять каналами.\n"
        "Команды: /start, /help"
    )


@dp.message()
async def handle_text(message: Message) -> None:
    await message.answer(f"Вы нажали: {message.text}\n\nЭто демо-реакция бота под интерфейс из примера.")


async def main() -> None:
    await on_startup()
    print("Ожидание сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())