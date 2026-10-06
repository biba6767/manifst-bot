import asyncio
from html import escape
from datetime import datetime, timedelta, timezone
import os
import secrets
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)


def get_bot_token() -> str:
    for env_name in ("API_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_BOT_TOKEN"):
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    raise RuntimeError(
        "Telegram bot token is missing. Set API_BOT_TOKEN or BOT_TOKEN environment variable."
    )


API_BOT_TOKEN = get_bot_token()
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "@manifestvelo")
TELEGRAM_PAYMENT_PROVIDER_TOKEN = os.environ.get("TELEGRAM_PAYMENT_PROVIDER_TOKEN", "")
DATABASE_PATH = os.environ.get(
    "BOT_DATABASE_PATH", os.path.join(os.path.dirname(__file__), "bot_data.sqlite3")
)
FREE_PUBLICATION_PERIOD = timedelta(days=7)
EXTRA_PUBLICATION_PRICE = 200

bot = Bot(token=API_BOT_TOKEN)
dp = Dispatcher()
users_waiting_for_title: set[int] = set()
users_waiting_for_description: set[int] = set()
users_waiting_for_photos: set[int] = set()
users_waiting_for_price: set[int] = set()
users_waiting_for_phone_choice: set[int] = set()
users_waiting_for_contact: set[int] = set()
listing_titles: dict[int, str] = {}
listing_descriptions: dict[int, str] = {}
listing_photo_counts: dict[int, int] = {}
listing_photos: dict[int, list[str]] = {}
listing_prices: dict[int, int] = {}
listing_phone_visibility: dict[int, bool] = {}
listing_phone_numbers: dict[int, str] = {}
listing_types: dict[int, str] = {}
publication_locks: dict[int, asyncio.Lock] = {}
next_listing_id = 26401
LISTING_TYPE_LABELS = {
    "sell": "🛒 Продаю 👌",
    "buy": "🎁 Покупаю",
    "exchange": "🔄 Обменяю",
}


def initialize_database() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS listing_publications "
            "(user_id INTEGER NOT NULL, published_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS paid_publication_credits "
            "(user_id INTEGER PRIMARY KEY, credits INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS processed_payments "
            "(charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL)"
        )


def has_free_publication(user_id: int) -> bool:
    cutoff = (datetime.now(timezone.utc) - FREE_PUBLICATION_PERIOD).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT 1 FROM listing_publications "
            "WHERE user_id = ? AND published_at >= ? LIMIT 1",
            (user_id, cutoff),
        ).fetchone()
    return row is None


def has_paid_publication_credit(user_id: int) -> bool:
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT credits FROM paid_publication_credits WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row is not None and row[0] > 0


def record_successful_publication(user_id: int, use_paid_credit: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        if use_paid_credit:
            cursor = connection.execute(
                "UPDATE paid_publication_credits SET credits = credits - 1 "
                "WHERE user_id = ? AND credits > 0",
                (user_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("No paid publication credit available")
        connection.execute(
            "INSERT INTO listing_publications (user_id, published_at) VALUES (?, ?)",
            (user_id, now),
        )


def record_successful_payment(user_id: int, charge_id: str) -> bool:
    with sqlite3.connect(DATABASE_PATH) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO processed_payments (charge_id, user_id) VALUES (?, ?)",
            (charge_id, user_id),
        )
        if cursor.rowcount != 1:
            return False
        connection.execute(
            "INSERT INTO paid_publication_credits (user_id, credits) VALUES (?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET credits = credits + 1",
            (user_id,),
        )
    return True


def main_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Создать объявление"), KeyboardButton(text="Мой профиль")],
        [KeyboardButton(text="Продвижение"), KeyboardButton(text="Поддержка")],
        [KeyboardButton(text="Сообщение")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def listing_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Продам")],
            [KeyboardButton(text="🎁 Покупаю")],
            [KeyboardButton(text="🔄 Обмен")],
        ],
        resize_keyboard=True,
    )


async def on_startup() -> None:
    initialize_database()
    print("Бот запущен и готов к работе!")
    try:
        channel = await bot.get_chat(TELEGRAM_CHANNEL_ID)
        print(f"Канал публикации настроен: @{channel.username or TELEGRAM_CHANNEL_ID}")
    except TelegramAPIError as error:
        print(f"Не удалось проверить канал {TELEGRAM_CHANNEL_ID}: {error}")
        print("Проверьте username канала и добавление бота администратором.")
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)


async def request_extra_publication_payment(message: Message, user_id: int) -> None:
    if not TELEGRAM_PAYMENT_PROVIDER_TOKEN:
        await message.answer(
            "Вы уже опубликовали бесплатное объявление за последние 7 дней. "
            "Дополнительная публикация стоит 200 KZT, вы можете  оплатить пишите админу @Bei4ka."
        )
        return

    payload = f"extra_listing:{user_id}:{secrets.token_urlsafe(12)}"
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Дополнительное объявление",
            description="Публикация одного дополнительного объявления в канале",
            payload=payload,
            provider_token=TELEGRAM_PAYMENT_PROVIDER_TOKEN,
            currency="KZT",
            prices=[LabeledPrice(label="Публикация объявления", amount=EXTRA_PUBLICATION_PRICE * 100)],
        )
    except TelegramAPIError as error:
        await message.answer("Не удалось создать счёт. Попробуйте позже или обратитесь в поддержку.")
        print(f"Ошибка создания счёта на дополнительную публикацию: {error}")


@dp.pre_checkout_query()
async def confirm_extra_publication_payment(query: PreCheckoutQuery) -> None:
    expected_prefix = f"extra_listing:{query.from_user.id}:"
    if (
        query.invoice_payload.startswith(expected_prefix)
        and query.currency == "KZT"
        and query.total_amount == EXTRA_PUBLICATION_PRICE * 100
    ):
        await query.answer(ok=True)
        return
    await query.answer(ok=False, error_message="Счёт недействителен. Создайте объявление заново.")


@dp.message(F.successful_payment)
async def receive_extra_publication_payment(message: Message) -> None:
    if message.from_user is None or message.successful_payment is None:
        return
    payment = message.successful_payment
    expected_prefix = f"extra_listing:{message.from_user.id}:"
    if (
        not payment.invoice_payload.startswith(expected_prefix)
        or payment.currency != "KZT"
        or payment.total_amount != EXTRA_PUBLICATION_PRICE * 100
    ):
        await message.answer("Не удалось проверить платёж. Обратитесь в поддержку.")
        return
    if not record_successful_payment(
        message.from_user.id, payment.telegram_payment_charge_id
    ):
        await message.answer("Этот платёж уже учтён.")
        return

    user_id = message.from_user.id
    if (
        user_id in listing_titles
        and user_id in listing_descriptions
        and listing_prices.get(user_id, 0) > 0
        and user_id in listing_phone_visibility
    ):
        await message.answer("Оплата получена. Публикую ваше объявление.")
        await send_listing_preview(message)
    else:
        await message.answer(
            "Оплата получена. Дополнительная публикация доступна. "
            "Создайте объявление через меню."
        )


@dp.message(CommandStart())
async def start(message: Message) -> None:
    text = (
        "С возвращением,\n\n"
        "Отличное начало! Продолжайте добавлять объявления.\n\n"
        "Ваша статистика:\n"
        "📊 Объявлений: 4\n"
        "💰 Баланс: 0 KZT\n\n"
        "Наши каналы:\n"
        "🚲 Веломаркет @manifestvelo\n"
        "🖥️ Техномаркет @manifestvelo\n\n"
        "Выберите действие из меню ниже:"
    )
    await message.answer(text, reply_markup=main_menu())


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Это бот-манифест. Он помогает добавлять объявления, следить за балансом и управлять каналами.\n"
        "Команды: /start, /help"
    )


@dp.message(F.text == "Продвижение")
async def promotion(message: Message) -> None:
    await message.answer("Поддержите создателя бота донатом: @Bei4ka")


@dp.message(F.text == "Поддержка")
async def support(message: Message) -> None:
    await message.answer(
        "Если возникла ошибка или проблема, напишите администраторам этой группы."
    )


@dp.message(F.text == "Создать объявление")
async def create_listing(message: Message) -> None:
    if message.from_user is not None:
        users_waiting_for_title.discard(message.from_user.id)
        users_waiting_for_description.discard(message.from_user.id)
        users_waiting_for_photos.discard(message.from_user.id)
        users_waiting_for_price.discard(message.from_user.id)
        users_waiting_for_phone_choice.discard(message.from_user.id)
        users_waiting_for_contact.discard(message.from_user.id)
        listing_photo_counts.pop(message.from_user.id, None)
        listing_photos.pop(message.from_user.id, None)
        listing_types.pop(message.from_user.id, None)
    text = (
        "🎯 Создание объявления\n\n"
        "📝 Мы пройдём несколько простых шагов:\n"
        "1️⃣ Выбор категории\n"
        "2️⃣ Название и описание\n"
        "3️⃣ Фотографии товара\n"
        "4️⃣ Цена и доставка\n"
        "5️⃣ Контактная информация\n\n"
        "⏱️ Это займёт всего 2-3 минуты!\n\n"
        "Начнем с выбора типа объявления:"
    )
    await message.answer(text, reply_markup=listing_type_keyboard())


@dp.message(F.text == "🛒 Продам")
async def sell_listing(message: Message) -> None:
    await start_listing_type(message, "sell")


@dp.message(F.text == "🎁 Покупаю")
async def buy_listing(message: Message) -> None:
    await start_listing_type(message, "buy")


@dp.message(F.text == "🔄 Обмен")
async def exchange_listing(message: Message) -> None:
    await start_listing_type(message, "exchange")


async def start_listing_type(message: Message, listing_type: str) -> None:
    if message.from_user is None:
        return
    listing_types[message.from_user.id] = listing_type
    await request_listing_title(message)


async def request_listing_title(message: Message) -> None:
    if message.from_user is None:
        return
    users_waiting_for_description.discard(message.from_user.id)
    users_waiting_for_title.add(message.from_user.id)
    text = (
        "✏️ Шаг 2 из 5: Название\n\n"
        "Введите название товара.\n\n"
        "📝 Что указать:\n"
        "• Название товара\n"
        "• Бренд/производитель\n"
        "• Модель\n"
        "• Год выпуска (если важно)\n\n"
        "✅ Пример: Велосипед Fuji Declaration 2018\n\n"
        "💡 Хорошее название увеличивает интерес к объявлению!"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )
    await message.answer(text, reply_markup=keyboard)


@dp.message(
    F.text & ~F.text.startswith("/"),
    lambda message: message.from_user is not None
    and message.from_user.id in users_waiting_for_title
    and message.text != "⬅️ Назад",
)
async def receive_listing_title(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    title = message.text.strip()
    if not title:
        await message.answer("Название не должно быть пустым. Введите название товара:")
        return

    user_id = message.from_user.id
    listing_titles[user_id] = title
    users_waiting_for_title.discard(user_id)
    await request_listing_description(message)


async def request_listing_description(message: Message) -> None:
    if message.from_user is None:
        return
    users_waiting_for_title.discard(message.from_user.id)
    users_waiting_for_description.add(message.from_user.id)
    users_waiting_for_photos.discard(message.from_user.id)
    users_waiting_for_price.discard(message.from_user.id)
    text = (
        "📝 Шаг 3 из 5: Описание\n\n"
        "Опишите ваш товар максимально подробно.\n\n"
        "📋 Что указать:\n"
        "• Состояние товара\n"
        "• Комплектацию\n"
        "• Особенности\n"
        "• Причину продажи (по желанию)\n\n"
        "✅ Пример: Рама и вилка стальные, размер 52, все остальное новое, "
        "состояние хорошее, есть небольшие царапины на раме.\n\n"
        "⚠️ Максимум 700 символов\n\n"
        "💡 Подробное описание вызывает больше доверия!"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад к названию")]],
        resize_keyboard=True,
    )
    await message.answer(text, reply_markup=keyboard)


@dp.message(
    F.text & ~F.text.startswith("/"),
    lambda message: message.from_user is not None
    and message.from_user.id in users_waiting_for_description
    and message.text != "⬅️ Назад к названию",
)
async def receive_listing_description(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    description = message.text.strip()
    if not description:
        await message.answer("Описание не должно быть пустым. Опишите ваш товар:")
        return
    if len(description) > 700:
        await message.answer("Описание должно быть не длиннее 700 символов. Сократите его и отправьте снова:")
        return

    user_id = message.from_user.id
    listing_descriptions[user_id] = description
    users_waiting_for_description.discard(user_id)
    users_waiting_for_photos.add(user_id)
    listing_photo_counts[user_id] = 0
    listing_photos[user_id] = []
    text = (
        "📸 Шаг 4 из 5: Фотографии\n\n"
        "Загрузите фотографии вашего товара.\n\n"
        "📷 Рекомендации:\n"
        "• Сделайте фото при хорошем освещении\n"
        "• Покажите товар с разных ракурсов\n"
        "• Если есть дефекты — сфотографируйте их\n"
        "• Можно отправить до 10 фото\n\n"
        "💡 Качественные фото увеличивают продажи!\n\n"
        "⚠️ Можно отправить несколько фото альбомом"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад к описанию")]],
        resize_keyboard=True,
    )
    await message.answer(text, reply_markup=keyboard)


@dp.message(
    F.photo,
    lambda message: message.from_user is not None
    and (
        message.from_user.id in users_waiting_for_photos
        or message.from_user.id in users_waiting_for_price
    ),
)
async def receive_listing_photo(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    photo_count = listing_photo_counts.get(user_id, 0) + 1
    listing_photo_counts[user_id] = photo_count
    if photo_count <= 10 and message.photo:
        listing_photos.setdefault(user_id, []).append(message.photo[-1].file_id)

    if user_id in users_waiting_for_photos:
        users_waiting_for_photos.discard(user_id)
        users_waiting_for_price.add(user_id)
        text = (
            f"✅ Загружено фото: {photo_count}\n\n"
            "💰 Шаг 5 из 5: Цена и доставка\n\n"
            "Укажите цену товара.\n\n"
            "💡 Советы по ценообразованию:\n"
            "• Изучите цены на аналогичные товары\n"
            "• Учитывайте состояние товара\n"
            "• Оставьте небольшой запас для торга\n\n"
            "✅ Пример: 16000\n\n"
            "📝 Введите только число без валюты"
        )
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="⬅️ Назад к фото")]],
            resize_keyboard=True,
        )
        await message.answer(text, reply_markup=keyboard)
        return

    await message.answer(f"✅ Загружено фото: {photo_count}")


@dp.message(
    F.text & ~F.text.startswith("/"),
    lambda message: message.from_user is not None
    and message.from_user.id in users_waiting_for_price
    and message.text != "⬅️ Назад к фото",
)
async def receive_listing_price(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    price_text = message.text.strip().replace(" ", "")
    if not price_text.isdigit() or int(price_text) <= 0:
        await message.answer("Введите положительную цену только числом, например: 16000")
        return

    user_id = message.from_user.id
    listing_prices[user_id] = int(price_text)
    users_waiting_for_price.discard(user_id)
    users_waiting_for_phone_choice.add(user_id)
    text = (
        "📱 Контактная информация\n\n"
        "Хотите показать ваш номер телефона в объявлении?\n\n"
        "✅ Да — номер будет виден всем\n"
        "• Покупатели смогут позвонить напрямую\n"
        "• Быстрая связь\n\n"
        "❌ Нет — номер будет скрыт\n"
        "• Покупатели напишут через Telegram\n"
        "• Больше конфиденциальности\n\n"
        "💡 Вы всегда можете изменить это позже"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да")],
            [KeyboardButton(text="❌ Нет")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )
    await message.answer(text, reply_markup=keyboard)


@dp.message(F.text == "✅ Да")
async def show_phone_number_choice(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if user_id not in users_waiting_for_phone_choice:
        return
    users_waiting_for_phone_choice.discard(user_id)
    users_waiting_for_contact.add(user_id)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Нажмите кнопку ниже, чтобы поделиться своим номером телефона.",
        reply_markup=keyboard,
    )


@dp.message(F.contact)
async def receive_listing_contact(message: Message) -> None:
    if message.from_user is None or message.contact is None:
        return
    if message.from_user.id not in users_waiting_for_contact:
        return
    if message.contact.user_id != message.from_user.id:
        await message.answer("Пожалуйста, поделитесь своим номером через кнопку Telegram.")
        return
    users_waiting_for_contact.discard(message.from_user.id)
    listing_phone_numbers[message.from_user.id] = message.contact.phone_number
    listing_phone_visibility[message.from_user.id] = True
    await send_listing_preview(message)


@dp.message(F.text == "❌ Нет")
async def hide_phone_number(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if user_id not in users_waiting_for_phone_choice:
        return
    users_waiting_for_phone_choice.discard(user_id)
    listing_phone_visibility[user_id] = False
    await send_listing_preview(message)


async def send_listing_preview(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    lock = publication_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        await publish_listing_preview(message, user_id)


async def publish_listing_preview(message: Message, user_id: int) -> None:
    global next_listing_id
    use_paid_credit = not has_free_publication(user_id)
    if use_paid_credit and not has_paid_publication_credit(user_id):
        await request_extra_publication_payment(message, user_id)
        return

    listing_id = next_listing_id
    next_listing_id += 1

    photo_ids = listing_photos.get(user_id, [])[:10]
    if photo_ids:
        await message.answer_media_group(
            media=[InputMediaPhoto(media=photo_id) for photo_id in photo_ids]
        )

    title = escape(listing_titles.get(user_id, "Товар"))
    description = escape(listing_descriptions.get(user_id, ""))
    price = listing_prices.get(user_id, 0)
    listing_type = listing_types.get(user_id, "sell")
    listing_label = LISTING_TYPE_LABELS.get(listing_type, LISTING_TYPE_LABELS["sell"])
    if listing_phone_visibility.get(user_id, False):
        contact_text = f"📞 {escape(listing_phone_numbers.get(user_id, 'Номер передан Telegram'))}"
    else:
        contact_text = "📱 Номер скрыт, свяжитесь через Telegram"
    text = (
        f"{listing_label} | №{listing_id}\n\n"
        f"📍 Казахстан\n\n"
        f"<b>{title}</b>\n\n"
        f"{description}\n\n"
        f"💰 {price} KZT\n"
        f"🚚 Доставка: уточняется\n\n"
        f"{contact_text}\n\n"
        "✅ Объявление готово к публикации"
    )
    publication_error = None
    try:
        if photo_ids:
            await bot.send_media_group(
                chat_id=TELEGRAM_CHANNEL_ID,
                media=[InputMediaPhoto(media=photo_id) for photo_id in photo_ids],
            )
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Связаться", url=f"tg://user?id={user_id}")]
                ]
            ),
        )
    except TelegramAPIError as error:
        publication_error = str(error)

    if publication_error is None:
        record_successful_publication(user_id, use_paid_credit)

    channel_link = f"https://t.me/{TELEGRAM_CHANNEL_ID.lstrip('@')}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть канал", url=channel_link)]]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    if publication_error is None:
        await message.answer(f"🎉 Объявление №{listing_id} опубликовано в канале.")
        listing_titles.pop(user_id, None)
        listing_descriptions.pop(user_id, None)
        listing_photo_counts.pop(user_id, None)
        listing_photos.pop(user_id, None)
        listing_prices.pop(user_id, None)
        listing_phone_visibility.pop(user_id, None)
        listing_phone_numbers.pop(user_id, None)
        listing_types.pop(user_id, None)
    else:
        await message.answer(
            "Не удалось опубликовать объявление в канале. Предпросмотр отправлен вам. "
            "Проверьте, что бот добавлен администратором с правом публикации."
        )
        print(f"Ошибка публикации объявления №{listing_id}: {publication_error}")


@dp.message(F.text == "⬅️ Назад")
async def back_to_listing_type(message: Message) -> None:
    if message.from_user is not None:
        user_id = message.from_user.id
        if user_id in users_waiting_for_phone_choice or user_id in users_waiting_for_contact:
            await back_to_price(message)
            return
        users_waiting_for_title.discard(message.from_user.id)
        users_waiting_for_description.discard(message.from_user.id)
        users_waiting_for_photos.discard(message.from_user.id)
        users_waiting_for_price.discard(message.from_user.id)
        users_waiting_for_phone_choice.discard(message.from_user.id)
        users_waiting_for_contact.discard(message.from_user.id)
    await message.answer(
        "Выберите тип объявления:",
        reply_markup=listing_type_keyboard(),
    )


@dp.message(F.text == "⬅️ Назад к названию")
async def back_to_title(message: Message) -> None:
    await request_listing_title(message)


@dp.message(F.text == "⬅️ Назад к описанию")
async def back_to_description(message: Message) -> None:
    await request_listing_description(message)


@dp.message(F.text == "⬅️ Назад к фото")
async def back_to_photos(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    users_waiting_for_price.discard(user_id)
    users_waiting_for_photos.add(user_id)
    text = (
        "📸 Шаг 4 из 5: Фотографии\n\n"
        "Загрузите фотографии вашего товара.\n\n"
        "📷 Рекомендации:\n"
        "• Сделайте фото при хорошем освещении\n"
        "• Покажите товар с разных ракурсов\n"
        "• Если есть дефекты — сфотографируйте их\n"
        "• Можно отправить до 10 фото\n\n"
        "💡 Качественные фото увеличивают продажи!\n\n"
        "⚠️ Можно отправить несколько фото альбомом"
    )
    await message.answer(text)


@dp.message(F.text == "⬅️ Назад к цене")
async def back_to_price(message: Message) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    users_waiting_for_phone_choice.discard(user_id)
    users_waiting_for_contact.discard(user_id)
    users_waiting_for_price.add(user_id)
    await message.answer(
        "💰 Шаг 5 из 5: Цена и доставка\n\n"
        "Укажите цену товара. Введите только положительное число без валюты, например: 16000",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="⬅️ Назад к фото")]],
            resize_keyboard=True,
        ),
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