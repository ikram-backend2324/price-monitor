# Какие данные нужны и как их получить

## 1. Переменные окружения (`.env`)

Скопируйте `.env.example` → `.env`. Для локального демо достаточно заполнить только `SECRET_KEY`.

| Переменная | Назначение | Обязательна | Пример |
|---|---|---|---|
| `SECRET_KEY` | Ключ подписи сессий Django | **Да** | `k3J9…` (50+ символов) |
| `DEBUG` | Режим отладки. В продакшене **False** | Да | `True` / `False` |
| `ALLOWED_HOSTS` | Домены, на которых отвечает сайт | Да | `pricewatch.uz,www.pricewatch.uz` |
| `CSRF_TRUSTED_ORIGINS` | Полные адреса сайта (для форм за HTTPS) | В продакшене | `https://pricewatch.uz` |
| `SITE_URL` | Публичный адрес (кнопки в Telegram, письма) | Да | `https://pricewatch.uz` |
| `ADMIN_URL` | Путь к админке | Нет | `control-7f3a/` |
| `TIME_ZONE` | Часовой пояс | Нет | `Asia/Tashkent` |
| `POSTGRES_DB/USER/PASSWORD` | Учётка БД для контейнера `db` | Да | `pricewatch` / сложный пароль |
| `DATABASE_URL` | Строка подключения Django к БД | Да | `postgres://pricewatch:ПАРОЛЬ@db:5432/pricewatch` |
| `REDIS_URL` | Кэш, локи, rate limit | Да | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | Очередь задач | Да | `redis://redis:6379/1` |
| `DEMO_USER_PASSWORD` | Пароль demo/admin из `seed_demo` | Для демо | `demo12345` |
| `DEMO_SHOP_CHANGE_INTERVAL` | Как часто меняются цены в демо-магазине (сек) | Нет | `120` |
| `TELEGRAM_BOT_TOKEN` | Токен бота | Для алертов | `1234567890:AAH…` |
| `TELEGRAM_BOT_USERNAME` | Имя бота без `@` (ссылка в кабинете) | Желательно | `pricewatch_uz_bot` |
| `ADMIN_TELEGRAM_CHAT_ID` | Куда слать `SCRAPER_DEGRADED` | Желательно | `123456789` |
| `BOT_MODE` | `polling` или `webhook` | Нет | `polling` |
| `BOT_WEBHOOK_URL`, `BOT_WEBHOOK_SECRET` | Только для webhook-режима | Нет | `https://pricewatch.uz/tg/webhook` |
| `PROXY_URLS` | Прокси через запятую | Нет | `http://user:pass@1.2.3.4:8000,...` |
| `SCRAPER_TIMEOUT`, `SCRAPER_MAX_RETRIES`, `SCRAPER_RESPECT_ROBOTS` | Тонкая настройка парсинга | Нет | `20`, `3`, `True` |
| `SENTRY_DSN` | Отправка ошибок в Sentry | Желательно в проде | `https://abc@o123.ingest.sentry.io/456` |
| `SENTRY_ENVIRONMENT`, `LOG_LEVEL` | Окружение и уровень логов | Нет | `production`, `INFO` |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | SMTP для писем (приглашения, email-алерты) | Нет | см. ниже |
| `DOMAIN`, `ACME_EMAIL` | Для HTTPS через Caddy в продакшене | В продакшене | `pricewatch.uz`, `you@mail.com` |

### SECRET_KEY
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
# или без Python:
openssl rand -base64 48
```
Никогда не коммитьте настоящий ключ в git. Смена ключа разлогинит всех пользователей.

### TELEGRAM_BOT_TOKEN — через @BotFather (2 минуты)
1. В Telegram найдите **@BotFather** (с синей галочкой).
2. Отправьте `/newbot`.
3. Введите отображаемое имя, например `PriceWatch Uzbekistan`.
4. Введите username, оканчивающийся на `bot`, например `pricewatch_uz_bot`.
5. BotFather пришлёт токен вида `1234567890:AAH...` → `TELEGRAM_BOT_TOKEN`. Username → `TELEGRAM_BOT_USERNAME`.
6. (Желательно) `/setdescription`, `/setuserpic` — описание и аватар.
7. Если токен утёк: `/revoke` в BotFather → обновите `.env` → `docker compose up -d`.

### ADMIN_TELEGRAM_CHAT_ID — ваш личный chat id
**Способ 1:** напишите **@userinfobot** → он ответит `Id: 123456789`.
**Способ 2 (getUpdates):** напишите что-нибудь своему боту, затем откройте в браузере
`https://api.telegram.org/bot<ТОКЕН>/getUpdates` → найдите `"chat":{"id":123456789`.
(Если бот уже запущен в polling-режиме, getUpdates вернёт пусто — остановите `bot` на минуту: `docker compose stop bot`.)
Для группы: добавьте бота в группу, напишите в ней, id группы будет отрицательным (`-100…`).
Обязательно отправьте своему боту `/start`, иначе он не сможет вам писать.

### SENTRY_DSN — бесплатный тариф
1. Зарегистрируйтесь на https://sentry.io (план Developer бесплатный: 5 000 ошибок/мес).
2. **Create Project** → платформа **Django** → имя `pricewatch`.
3. **Settings → Projects → pricewatch → Client Keys (DSN)** → скопируйте DSN.
4. Вставьте в `SENTRY_DSN`, `docker compose up -d`. Ошибки Django и Celery начнут приходить автоматически.

### PROXY_URLS — когда нужны и сколько стоят
**Для старта прокси не нужны.** Система делает мало запросов (rate limit на домен, проверки раз в 30–360 мин). Прокси понадобятся, если:
- магазин начал отвечать 403/429 на ваш IP-адрес сервера;
- вы следите за тысячами ссылок одного магазина;
- магазин блокирует IP дата-центров (Hetzner, DigitalOcean).

| Тип | Плюсы | Минусы | Примерная цена (2026) |
|---|---|---|---|
| Датацентровые | Дёшево, быстро | Легко распознаются | $1–3 за IP в месяц; пакет 10 IP ≈ $15–25 |
| Резидентные (оплата за трафик) | Выглядят как обычные пользователи | Дороже, медленнее | $3–8 за ГБ; 1 страница ≈ 0,3–1 МБ (браузер) или 50–200 КБ (httpx) |
| Мобильные (UZ-операторы) | Максимальное доверие | Дорого | $40–100 за порт в месяц |

Формат: `http://user:pass@host:port` (также `socks5://…`), несколько через запятую — система ротирует их по кругу.
Выбирайте провайдера с IP в Узбекистане/СНГ (меньше капч и редиректов). Не используйте прокси для обхода явных запретов (robots.txt, капчи) — это противоречит политике проекта.

### Почта (необязательно)
По умолчанию письма печатаются в лог (`console`). Для реальной отправки, например через Gmail:
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=<пароль приложения: Google аккаунт → Безопасность → Пароли приложений>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=PriceWatch <you@gmail.com>
```
Для рассылок клиентам лучше Brevo/Mailgun/Amazon SES (бесплатные лимиты 300 писем/день у Brevo).

## 2. Данные клиента

### Что нужно от клиента
| Поле | Обязательно | Комментарий |
|---|---|---|
| `sku` | Да | Артикул — уникальный в пределах клиента |
| `name` | Да | Название товара |
| `my_price` | Да | Текущая цена клиента, сум |
| `cost_price` | Желательно | Себестоимость — без неё рекомендация не проверяет минимальную маржу |
| `category` | Нет | Для правил по категориям и фильтров |
| `url_1…url_N` | Да | Ссылки на **тот же самый** товар у конкурентов |

### Как собрать
1. В кабинете → **Импорт / экспорт** → скачайте **шаблон Excel**.
2. Клиент выгружает каталог из своей учётной системы (1С, МойСклад, кабинет продавца Uzum → «Товары» → экспорт) и вставляет колонки sku, name, my_price, cost_price.
3. Ссылки на конкурентов:
   - **Uzum Market:** поиск по названию/модели → откройте карточку → скопируйте адрес вида `https://uzum.uz/ru/product/...-1234567`. Сверяйте модель, объём памяти, цвет, комплектацию (иначе сравнение некорректно).
   - **Интернет-магазины** (Mediapark, Texnomart, Elmakon, Asaxiy, Olcha и т. п.): поиск по модели, копируйте адрес карточки.
   - Начните с 3–5 главных конкурентов и 20–50 самых продаваемых товаров (правило 80/20) — этого хватает для пилота.
4. Загрузите файл в кабинете → система покажет отчёт: сколько товаров создано/обновлено и ошибки по строкам.

### Сколько времени это занимает
| Объём | Время на ссылки (вручную) |
|---|---|
| 20 товаров × 3 конкурента | 1–1,5 часа |
| 100 товаров × 3 конкурента | 4–6 часов (1 рабочий день помощника) |
| 500+ товаров | 2–4 дня; выгодно продавать как «внедрение под ключ» (см. BUSINESS.md) |

Совет: ищите по точному коду модели (например `SM-A556E`) — так быстрее и точнее, чем по названию.

## 3. Домен и DNS (для продакшена)

1. Купите домен:
   - `.uz` — через аккредитованных регистраторов (например, cctld.uz → список регистраторов: Billur Com, Ahost и др.), ≈ 100–200 тыс. сум/год.
   - `.com` / `.app` — Namecheap, Cloudflare Registrar, ≈ $10–15/год.
2. В панели DNS создайте записи:
   ```
   A     pricewatch.uz        → <IP вашего сервера>
   A     www.pricewatch.uz    → <IP вашего сервера>
   ```
3. Подождите 5–60 минут (проверка: `nslookup pricewatch.uz`).
4. В `.env`: `DOMAIN=pricewatch.uz`, `ACME_EMAIL=you@mail.com`, `ALLOWED_HOSTS=pricewatch.uz,www.pricewatch.uz`, `CSRF_TRUSTED_ORIGINS=https://pricewatch.uz`, `SITE_URL=https://pricewatch.uz`. Caddy сам получит сертификат Let's Encrypt.
