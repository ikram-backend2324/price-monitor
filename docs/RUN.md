# Как запустить PriceWatch

## 1. Что установить

| ОС | Что нужно | Как |
|---|---|---|
| **Windows 10/11** | WSL2 + Docker Desktop + Git | 1) В PowerShell от администратора: `wsl --install`, перезагрузка. 2) Скачать Docker Desktop: https://www.docker.com/products/docker-desktop/ → установить (галочка «Use WSL 2»). 3) Git: https://git-scm.com/download/win |
| **Ubuntu/Debian** | Docker Engine + Compose plugin + Git | `curl -fsSL https://get.docker.com \| sh` → `sudo usermod -aG docker $USER` → перелогиниться. `sudo apt install -y git` |
| **macOS** | Docker Desktop + Git | Docker Desktop для Apple Silicon/Intel с сайта Docker; Git: `xcode-select --install` |

Проверка:
```bash
docker --version          # Docker 24+
docker compose version    # v2+
git --version
```
Минимум ресурсов для Docker: **4 ГБ RAM** (Chromium для Playwright требовательный), 10 ГБ диска.

## 2. Запуск по шагам

```bash
# 1. Клонировать
git clone <URL-вашего-репозитория> price-monitor
cd price-monitor

# 2. Создать конфиг
cp .env.example .env          # Windows PowerShell: copy .env.example .env

# 3. Заполнить .env (минимум — SECRET_KEY, остальное можно оставить для демо)
python -c "import secrets; print(secrets.token_urlsafe(50))"   # вставьте результат в SECRET_KEY

# 4. Собрать и запустить (первый раз 5–10 минут: скачивается Chromium)
docker compose up -d --build

# 5. Миграции выполняются автоматически контейнером web. Проверить:
docker compose ps             # все сервисы должны быть (healthy)

# 6. Демо-данные: 25 товаров × 3 конкурента, 30 дней истории
docker compose exec web python manage.py seed_demo

# 7. Открыть в браузере
#    http://localhost            (через Nginx)
#    http://localhost:8000       (напрямую в Django)
```

Логин: `demo@pricewatch.local` / значение `DEMO_USER_PASSWORD` (по умолчанию `demo12345`).
Админка: http://localhost/admin/ — `admin@pricewatch.local` / тот же пароль.
API-документация: http://localhost/api/docs/
Демо-магазин: http://localhost:8001/?shop=techbozor (также `megasavdo`, `smartmarket`).

Пересоздать демо с нуля: `docker compose exec web python manage.py seed_demo --reset`

Свой суперпользователь: `docker compose exec web python manage.py createsuperuser`

## 3. Что где работает

| Сервис | Назначение |
|---|---|
| `web` | Django + Gunicorn (веб-кабинет, API, админка), при старте делает `migrate` |
| `worker-fast` | Celery, очередь `fast`: httpx-парсинг (8 параллельно) |
| `worker-browser` | Celery, очередь `browser`: Playwright/Chromium (2 параллельно) — Uzum и JS-сайты |
| `worker-default` | Celery, очередь `default`: планировщик проверок, алерты, дайджесты, здоровье парсеров |
| `beat` | Celery Beat — расписания хранятся в БД (видны в админке → Periodic tasks) |
| `bot` | Telegram-бот (long polling) |
| `db`, `redis` | PostgreSQL 16, Redis 7 |
| `nginx` | Реверс-прокси на порту 80 |
| `demo-shop` | Фейковые магазины для демо (цены меняются каждые `DEMO_SHOP_CHANGE_INTERVAL` секунд) |

## 4. Как запустить бота

1. Получите токен у @BotFather (подробно — `docs/DATA.md`), впишите в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:AA...
   TELEGRAM_BOT_USERNAME=my_pricewatch_bot
   ADMIN_TELEGRAM_CHAT_ID=123456789
   ```
2. Перезапустите сервисы, которые читают токен:
   ```bash
   docker compose up -d bot worker-default worker-fast worker-browser web
   ```
3. В веб-кабинете → **Telegram** → появится код. Отправьте боту `/start КОД` (или нажмите ссылку).
4. Проверьте: `/products`, `/check PH-SAM-A55`, `/report`, `/lang`.

Без токена бот работает «вхолостую» (контейнер здоров), а алерты пишутся в лог `worker-default`.

## 5. Как проверить, что Celery работает

```bash
docker compose exec worker-default celery -A config inspect ping          # все воркеры отвечают pong
docker compose exec worker-default celery -A config inspect active_queues # кто какую очередь слушает
docker compose logs -f worker-default | grep "Queued"                     # каждую минуту: "Queued N offers"
docker compose exec web python manage.py shell -c "from apps.scraping.models import ScrapeRun; print(ScrapeRun.objects.count())"
```
Через 2–5 минут после `seed_demo` на дашборде появятся новые изменения, а в «Алертах» — события.

## 6. Логи

```bash
docker compose logs -f web              # веб
docker compose logs -f worker-fast      # парсинг (httpx)
docker compose logs -f worker-browser   # парсинг (браузер)
docker compose logs -f worker-default   # планировщик, алерты, дайджесты
docker compose logs -f beat             # расписание
docker compose logs -f bot              # Telegram
docker compose logs --tail 100 nginx
```

## 7. Как добавить новый магазин без кода (SelectorAdapter)

Пример: магазин `texnomart.uz` (условно).

1. **Сначала попробуйте ничего не настраивать.** Добавьте ссылку на товар в кабинете (Товар → «Добавить ссылку»). Магазин создастся автоматически с адаптером **JSON-LD** — многие магазины отдают разметку `schema.org/Product`, и всё заработает сразу. Проверьте статус ссылки через минуту.
2. Если статус «Ошибка» — откройте **Админка → Stores → нужный магазин**.
3. Откройте страницу товара в Chrome → правой кнопкой по цене → **Просмотреть код**. Найдите стабильный класс/атрибут, например `<span class="product-price">1 299 000 сум</span>`.
4. В карточке магазина:
   - **Adapter**: `CSS selectors (configured below)`
   - **Price selector**: `.product-price`
   - **Old price selector**: `.old-price` (если есть зачёркнутая цена)
   - **Title selector**: `h1`
   - **In stock selector**: `button.add-to-cart` (кнопка есть → в наличии)
   - **Out of stock selector** или **Out of stock text**: `нет в наличии, mavjud emas`
   - **Price regex** (если в элементе лишний текст): `([\d\s]+)\s*сум`
   - **Rate limit per minute**: 10–20 для небольших магазинов
   - Если сайт показывает цену только после JavaScript — включите **Requires browser** и укажите **Wait selector** (тот же, что и цена).
5. Сохраните и нажмите **«Test selectors on URL»** в списке магазинов → вставьте ссылку → **Fetch & extract**. Вы увидите извлечённые цену, старую цену, наличие и название.
6. Готово: все ссылки этого домена начнут парситься по новым правилам.

> Используйте селекторы по `data-*`-атрибутам или осмысленным классам. Классы вида `css-1x2y3z` меняются при каждой сборке сайта.

## 8. Запуск без Docker (для разработки)

```bash
python -m venv .venv
.venv\Scripts\activate                     # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium                # только если нужен Uzum/браузерный режим
```
Создайте `.env.local`:
```
SECRET_KEY=dev
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=
DEMO_SHOP_HOSTS=techbozor=127.0.0.2:8001,megasavdo=127.0.0.3:8001,smartmarket=127.0.0.4:8001
```
Без Redis Celery работает в «eager»-режиме (задачи выполняются сразу, без воркеров), кэш — в памяти.
```bash
# PowerShell: $env:ENV_FILE=".env.local"   bash: export ENV_FILE=.env.local
python manage.py migrate
python manage.py seed_demo
cd demo_shop && uvicorn main:app --port 8001 &   # демо-магазин
python manage.py runserver
pytest --cov                                      # тесты
```

## 9. Частые ошибки

| Симптом | Причина и решение |
|---|---|
| `Bind for 0.0.0.0:80 failed: port is already allocated` | Порт занят (IIS, Skype, другой nginx). Освободите порт или в `docker-compose.yml` у `nginx` замените `"80:80"` на `"8080:80"` и открывайте http://localhost:8080. Аналогично `8000`, `8001`. Найти процесс: Windows `netstat -ano \| findstr :80`, Linux `sudo lsof -i :80` |
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop не запущен. Запустите его и дождитесь «Engine running». На Windows нужен WSL2: `wsl --install` |
| `worker-browser` падает / `Executable doesn't exist` | Образ собран без Chromium: `docker compose build --no-cache worker-browser`. Мало памяти: дайте Docker ≥ 4 ГБ (Settings → Resources) |
| `TargetClosedError` / `out of memory` в браузерном воркере | Уменьшите `--concurrency` в `worker-browser`, проверьте `shm_size: 1gb` |
| Бот не отвечает | 1) `docker compose logs bot` — если «TELEGRAM_BOT_TOKEN is empty», впишите токен и `docker compose up -d bot`. 2) Токен перевыпущен — обновите. 3) Один токен нельзя одновременно использовать в двух местах (polling конфликтует) — остановите бота на другом компьютере. 4) Если раньше ставили webhook, бот сам его снимет при старте |
| «Код неверный или устарел» | Код живёт 15 минут, на странице Telegram нажмите «Новый код» |
| Ссылка в статусе «Запрещено robots.txt» | Сайт запрещает обход этого пути. Это правильное поведение; используйте другую страницу или откажитесь от источника |
| Ссылки Uzum с ошибкой «page not rendered» | Uzum изменил вёрстку или медленно грузится: см. `docs/PRODUCTION.md` → «Сайт-донор поменял вёрстку» |
| На дашборде нет новых изменений | Проверьте `docker compose logs worker-default \| grep Queued`, что подписка организации активна (Тариф и лимиты) и что demo-shop healthy |
| `CSRF verification failed` за доменом/HTTPS | Добавьте домен в `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS=https://ваш-домен` |
| Изменили `.env`, ничего не поменялось | Переменные читаются при старте: `docker compose up -d` (пересоздаст контейнеры) |
| Скрипт `entrypoint.sh: not found` на Windows | Git сконвертировал переносы строк. В репозитории есть `.gitattributes`; выполните `git rm --cached -r . && git reset --hard` |
