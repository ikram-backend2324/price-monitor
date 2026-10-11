# Как стабильно запустить PriceWatch в продакшене

## 1. Выбор сервера

| Нагрузка | Минимум | Рекомендация |
|---|---|---|
| До ~2 000 ссылок, проверка раз в 30–120 мин | **2 vCPU / 4 GB RAM / 40 GB SSD** | 4 vCPU / 8 GB |
| > 5 000 ссылок или много сайтов через Playwright | 4 vCPU / 8 GB | 8 vCPU / 16 GB или отдельный сервер под `worker-browser` |

Playwright (Chromium) — самый требовательный компонент: ~300–500 МБ RAM на одну параллельную вкладку.

| Хостинг | Плюсы | Минусы |
|---|---|---|
| **Локальные UZ-провайдеры** (Uzcloud, Ahost, Billur Com и др.) | IP в Узбекистане — местные магазины реже блокируют; низкая задержка; оплата в сумах | Дороже за ту же мощность, меньше автоматизации (снапшоты, API), разное качество поддержки |
| **Hetzner** (Германия/Финляндия) | Очень дёшево (CX32 4/8 ≈ €8), надёжно, снапшоты, S3-хранилище | IP дата-центра ЕС — некоторые сайты могут ограничивать; оплата картой |
| **DigitalOcean** (Франкфурт/Амстердам) | Удобная панель, managed PostgreSQL, Spaces (S3) | Дороже Hetzner в 2–3 раза |

Практичный вариант: Hetzner для всего + при блокировках отдельные прокси с UZ-IP (`PROXY_URLS`).

## 2. Пошаговый деплой (Ubuntu 24.04)

### 2.1. Подготовка сервера
```bash
# с вашего компьютера: ключ SSH (если ещё нет)
ssh-keygen -t ed25519 -C "you@mail.com"
ssh-copy-id root@SERVER_IP

# на сервере (под root)
apt update && apt upgrade -y
adduser deploy                       # пользователь без root
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# запретить вход по паролю и под root
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh

# firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# fail2ban (защита SSH от перебора)
apt install -y fail2ban
systemctl enable --now fail2ban

# автообновления безопасности
apt install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades

# swap 2 ГБ (страховка для Chromium)
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

> Важно: Docker публикует порты в обход ufw. В `docker-compose.prod.yml` наружу открыты только 80/443 (Caddy), базы и Redis не публикуются.

### 2.2. Docker
```bash
ssh deploy@SERVER_IP
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy && exit     # перелогиниться
ssh deploy@SERVER_IP
docker compose version
```

### 2.3. Код и конфигурация
```bash
sudo mkdir -p /opt/pricewatch && sudo chown deploy:deploy /opt/pricewatch
git clone <URL-репозитория> /opt/pricewatch
cd /opt/pricewatch
cp .env.example .env
nano .env
```
Обязательно в `.env` для продакшена:
```
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(50))">
DEBUG=False
DOMAIN=pricewatch.uz
ACME_EMAIL=you@mail.com
ALLOWED_HOSTS=pricewatch.uz,www.pricewatch.uz
CSRF_TRUSTED_ORIGINS=https://pricewatch.uz
SITE_URL=https://pricewatch.uz
ADMIN_URL=control-<случайные-символы>/
POSTGRES_PASSWORD=<длинный случайный пароль>
DATABASE_URL=postgres://pricewatch:<тот же пароль>@db:5432/pricewatch
TELEGRAM_BOT_TOKEN=...
ADMIN_TELEGRAM_CHAT_ID=...
SENTRY_DSN=...
DEMO_USER_PASSWORD=<сложный, если будете запускать seed_demo>
```

### 2.4. Запуск
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py createsuperuser
```
Для удобства: `alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'` в `~/.bashrc`.

Демо-магазин в проде выключен; включить для показа клиентам: `dc --profile demo up -d demo-shop`.

### 2.5. HTTPS (Let's Encrypt)
Уже встроено: сервис **Caddy** в `docker-compose.prod.yml` сам получает и продлевает сертификат для `DOMAIN` (нужны A-записи DNS на IP сервера и открытые 80/443). Проверка: `curl -I https://pricewatch.uz/health/`.

Альтернатива — certbot + nginx на хосте: `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx -d pricewatch.uz` (тогда удалите сервис caddy и пробросьте порт nginx).

## 3. Бэкапы PostgreSQL

### Ежедневный дамп
```bash
chmod +x scripts/backup.sh scripts/restore_check.sh
crontab -e
# каждый день в 03:15
15 3 * * * cd /opt/pricewatch && ./scripts/backup.sh >> backups/backup.log 2>&1
```
Скрипт делает `pg_dump | gzip`, хранит 14 последних копий локально.

### Хранение вне сервера (S3-совместимое)
```bash
sudo apt install -y rclone
rclone config            # remote "backup": Hetzner Object Storage / Backblaze B2 / DO Spaces / AWS S3
echo 'RCLONE_REMOTE=backup:pricewatch-backups' >> .env
```
Включите версионирование/lifecycle в бакете (хранить 30–90 дней).

### Проверка восстановления (раз в месяц — обязательно!)
```bash
./scripts/restore_check.sh backups/pricewatch-YYYYMMDD-HHMMSS.sql.gz
```
Скрипт поднимает временный Postgres, восстанавливает дамп и показывает количество товаров/ссылок/снимков. Бэкап, который ни разу не восстанавливали, — не бэкап.

### Полное восстановление на новом сервере
```bash
dc up -d db
gunzip -c pricewatch-....sql.gz | dc exec -T db psql -U pricewatch -d pricewatch
dc up -d
```

## 4. Мониторинг

| Что | Как |
|---|---|
| Ошибки кода | **Sentry** (`SENTRY_DSN`) — Django и Celery подключены автоматически |
| Доступность | `https://ваш-домен/health/` (проверяет БД и Redis, 200/503). Подключите **UptimeRobot** (бесплатно, проверка каждые 5 мин, уведомление в Telegram) |
| Контейнеры | Healthcheck у каждого сервиса: `dc ps` показывает `(healthy)`. Политика `restart: always` перезапускает упавшие |
| Качество парсинга | Страница «Состояние парсеров»: success rate за час по каждому магазину, проблемные ссылки. Событие `SCRAPER_DEGRADED` (< 70% успешных за час или 5 ошибок подряд у ссылки) уходит в Telegram админу |
| Очереди | `dc exec worker-default celery -A config inspect active`, длина очереди: `dc exec redis redis-cli -n 1 llen fast` |
| Ресурсы | `docker stats`; при необходимости Netdata или Prometheus + Grafana |
| Логи | `dc logs -f --tail 200 worker-fast`; логи ротируются (json-file, 5 × 20 МБ) |

## 5. Масштабирование

1. **Больше параллельности:** `--concurrency` у `worker-fast` (16–32, httpx почти не грузит CPU); `worker-browser` — по 1 вкладке на ~0,5 ГБ RAM.
2. **Больше воркеров:** `dc up -d --scale worker-fast=3`.
3. **Отдельный сервер под браузер:** запустите на втором сервере только `worker-browser` с тем же `.env`, указав `DATABASE_URL`/`REDIS_URL` первого сервера (через приватную сеть/WireGuard).
4. **Managed PostgreSQL** (DigitalOcean, Hetzner): поменяйте `DATABASE_URL`, уберите сервис `db`.
5. **Рост `PriceSnapshot`:** благодаря дедупликации пишется ~1–5 строк на ссылку в сутки. При > 50 млн строк:
   - **партиционирование по месяцам** (`PARTITION BY RANGE (checked_at)`), миграция через `pg_partman`;
   - **ретеншн:** старше 180 дней сжимать до одного значения в день (min/max/последнее), старше 2 лет — удалять. `ScrapeRun` хранить 30 дней (`DELETE ... WHERE started_at < now() - interval '30 days'` по крону).
6. **Redis:** `maxmemory 512mb` + `noeviction` (очереди нельзя вытеснять); при росте — отдельный Redis для кэша.

## 6. Обновления без простоя

```bash
cd /opt/pricewatch
git pull
dc build                                  # собрать новые образы, старые продолжают работать
dc up -d                                  # web применит миграции при старте (RUN_MIGRATIONS=1)
dc ps                                     # убедиться, что всё healthy
```
Правила миграций: изменения схемы — **обратно совместимые** (сначала добавить колонку nullable → задеплоить код → заполнить → в следующем релизе сделать NOT NULL/удалить старое). Тогда старые воркеры не падают во время переката.

**Откат:**
```bash
git log --oneline -5
git checkout <предыдущий-коммит>
dc up -d --build
```
Если релиз содержал миграцию — откатите её явно: `dc exec web python manage.py migrate <app> <номер_предыдущей>`. Перед каждым крупным релизом делайте `./scripts/backup.sh`.

Для быстрых откатов можно тегировать образы: `docker tag pricewatch-app:latest pricewatch-app:2026-10-12` перед сборкой.

## 7. Сайт-донор поменял вёрстку: регламент

1. **Сигнал:** Telegram-алерт `SCRAPER_DEGRADED` / `OFFER_FAILING`, на странице «Состояние парсеров» success rate магазина падает.
2. **Диагностика (15 мин):** админка → Stores → **Test selectors on URL** на проблемной ссылке. Смотрите, что извлеклось.
3. **Исправление:**
   - SelectorAdapter — поменять CSS-селектор в админке, проверить кнопкой — **без деплоя**.
   - Uzum/свой адаптер — сохранить новую страницу как фикстуру (`tests/fixtures/`), поправить единственную функцию разбора (`parse_uzum_html`), прогнать `pytest tests/test_adapters.py`, задеплоить.
4. **Проверка:** «Проверить сейчас» на нескольких товарах, success rate возвращается > 90%, придёт событие `SCRAPER_RECOVERED`.
5. **Коммуникация с клиентами:** если простой > 4 часов — короткое сообщение затронутым клиентам; SLA: исправление в течение 1 рабочего дня (Enterprise — 4 часа).
6. **Профилактика:** раз в неделю смотреть «Проблемные ссылки» (товар удалён/перемещён) и уведомлять клиента.

## 8. Чек-лист безопасности

- [ ] `DEBUG=False`, корректные `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
- [ ] Уникальный длинный `SECRET_KEY`, сложный `POSTGRES_PASSWORD`; `.env` не в git (`git status` чистый, `.env` в `.gitignore`)
- [ ] Админка по нестандартному пути (`ADMIN_URL`), сложные пароли, только нужные staff-пользователи
- [ ] Rate limit на вход: Nginx `limit_req` на `/login/` (10 в минуту), DRF throttle на получение токена
- [ ] HTTPS везде (Caddy), HSTS включён, cookies `Secure`
- [ ] Наружу открыты только 22/80/443 (ufw), SSH только по ключу, fail2ban
- [ ] БД и Redis не публикуются наружу
- [ ] Ежедневные бэкапы вне сервера + ежемесячная проверка восстановления
- [ ] Регулярные обновления: `apt upgrade` (unattended-upgrades), пересборка образов раз в месяц (`dc build --pull && dc up -d`), обновление зависимостей (`pip list --outdated`, Dependabot в GitHub)
- [ ] Sentry и UptimeRobot настроены, алерты приходят в Telegram
- [ ] Токен Telegram-бота и прокси-пароли — только в `.env`; при утечке — перевыпуск
