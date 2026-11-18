# Деплой Telegram-бота

Точка входа: `main.py` (для Render — `serve.py`, который дополнительно держит открытым порт `$PORT` для health-check веб-сервиса). Токен берётся из переменной окружения `API_BOT_TOKEN`
(или `BOT_TOKEN` / `TELEGRAM_BOT_TOKEN`).

## Render.com (бесплатный worker)

1. Залей этот репозиторий в GitHub (уже есть `origin`).
2. Зайди на <https://dashboard.render.com/blueprints> → **New Blueprint** → выбери репозиторий.
3. Render прочитает `render.yaml` и создаст worker `manifest-bot`.
4. При создании введи `API_BOT_TOKEN` (токен от @BotFather).
   `TELEGRAM_PAYMENT_PROVIDER_TOKEN` можно оставить пустым, если платежи не используются.
5. Готово: worker будет крутиться круглосуточно, логи смотри во вкладке **Logs**.

## Docker (любой хостинг с контейнерами / VPS)

```sh
docker build -t manifest-bot .
docker run -d --name manifest-bot --restart unless-stopped \
  -e API_BOT_TOKEN="токен от BotFather" \
  manifest-bot
```

Для VPS с постоянным хранилищем добавь `-v $(pwd)/data:/app/data` и задай
`BOT_DATABASE_PATH=/app/data/bot_data.sqlite3`, иначе база переживёт перезапуск
контейнера, но не пересоздание.

## Локально

```sh
python -m pip install -r requirements.txt
$env:API_BOT_TOKEN="токен от BotFather"
python main.py
```

## Важное про базу

`bot_data.sqlite3` — локальный файл. На Render (бесплатный план) диск временный:
при каждом новом деплое база создаётся заново. Если нужна сохранность данных между
деплоями, переходи на Postgres или подключай постоянный диск на platном плане.
