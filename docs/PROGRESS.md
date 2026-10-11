# Прогресс

| Этап | Статус | Проверка |
|---|---|---|
| 1. Каркас: Docker, compose, настройки, `.env.example`, pre-commit, CI | ✅ | `docker compose config`, GitHub Actions (ruff + pytest + docker build) |
| 2. Модели, админка, мультитенантность | ✅ | `tests/test_tenancy.py` — пользователь A не видит и не меняет данные B (веб + API) |
| 3. demo-shop, DemoShopAdapter, парсинг цены, Celery-задачи, Beat | ✅ | 30+ форматов цен в `test_price_parser.py`; планировщик и локи в `test_pipeline.py` |
| 4. JsonLd/Selector/Uzum адаптеры, rate limit, robots.txt, ретраи, здоровье парсеров | ✅ | `test_adapters.py`, `test_http.py` (respx), Uzum — на 3 живых страницах + фикстуры |
| 5. История, правила ценообразования, алерты | ✅ | `test_pricing.py`, `test_alerts.py` (группировка, анти-спам 30 мин) |
| 6. Telegram-бот | ✅ | `test_bot.py` (сервисный слой); бот стартует, healthcheck зелёный |
| 7. Веб-кабинет, графики, импорт/экспорт, i18n ru/uz/en | ✅ | `test_views.py`, скриншоты `docs/screenshots/` |
| 8. REST API + OpenAPI | ✅ | `test_api.py`, `/api/docs/` |
| 9. Тарифы/лимиты, заготовка платежей | ✅ | `test_billing.py` |
| 10. Продакшен-конфигурация, документация, финальная проверка | ✅ | см. ниже |

## Финальная проверка (12.10.2026)

- `docker compose up -d --build` → **10/10 сервисов healthy** (web, worker-fast, worker-browser, worker-default, beat, bot, db, redis, nginx, demo-shop).
- `seed_demo` → 25 товаров, 75 ссылок, 2 325 снимков за 30 дней; дашборд и графики открываются.
- Через ~5 минут после запуска: 70 проверок через три адаптера, **100% успешных**, 70 новых снимков, 22 `AlertEvent` (снижение цены, «дешевле меня», нет в наличии, снова в наличии), доставка с группировкой.
- Тесты: **217 passed, покрытие 90%**; `ruff check` и `ruff format --check` — без ошибок; `mypy` — без ошибок.
- UzumAdapter на живых страницах (из контейнера `worker-browser`, через очередь Celery): POCO X8 Pro Max — 8 699 000 (старая 9 500 000, в наличии); Redmi 15 — 2 090 000 (нет в наличии); Redmi Note 13 Pro — 5 500 000 (нет в наличии). Тест также на сохранённых HTML-фикстурах.
- Бэкап: `pg_dump` → `scripts/restore_check.sh` восстановил 25 товаров / 75 ссылок / 2 534 снимка.
- Скриншоты 16 страниц (светлая/тёмная тема, мобильная версия, админка) — `docs/screenshots/`.

## Не проверено
- Реальная отправка в Telegram (нужен `TELEGRAM_BOT_TOKEN`); проверена через мок Bot API в тестах и демо-режим (лог).
- Продакшен-деплой с HTTPS (нужны сервер и домен); `docker-compose.prod.yml` валидирован `docker compose config`.
- Интеграции Click/Payme — заготовки без ключей мерчанта.
