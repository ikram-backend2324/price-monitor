"""PriceWatch Telegram bot (aiogram 3).

Run:  python -m bot.main
Modes: BOT_MODE=polling (default) or BOT_MODE=webhook (needs BOT_WEBHOOK_URL).
Without TELEGRAM_BOT_TOKEN the process idles (keeps the container healthy) and logs a warning.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from aiogram import Bot, Dispatcher, F, Router  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.filters import Command, CommandObject, CommandStart  # noqa: E402
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message  # noqa: E402
from asgiref.sync import sync_to_async  # noqa: E402
from django.conf import settings  # noqa: E402

from bot import services  # noqa: E402
from bot.texts import t  # noqa: E402

log = logging.getLogger("bot")
HEARTBEAT = Path(os.environ.get("BOT_HEARTBEAT_FILE", "/tmp/bot-heartbeat"))
CODE_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

router = Router()
db = sync_to_async  # all ORM calls go through the thread pool


async def account_or_reply(message: Message):
    account = await db(services.get_account)(message.chat.id)
    if account is None or account.org is None:
        lang = (message.from_user.language_code or "ru")[:2] if message.from_user else "ru"
        await message.answer(t("not_linked", lang if lang in ("ru", "uz", "en") else "ru"))
        return None
    return account


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    code = (command.args or "").strip()
    if code:
        await try_link(message, code)
        return
    account = await db(services.get_account)(message.chat.id)
    if account:
        await message.answer(t("already", account.lang, email=account.link.user.email))
    else:
        await message.answer(t("welcome", "ru") + "\n\n" + t("welcome", "uz"))


@router.message(F.text.regexp(CODE_RE))
async def plain_code(message: Message):
    await try_link(message, message.text)


async def try_link(message: Message, code: str):
    username = message.from_user.username if message.from_user else ""
    account = await db(services.link_account)(message.chat.id, username or "", code)
    if account is None:
        await message.answer(t("bad_code", "ru"))
        return
    org_name = account.org.name if account.org else "—"
    await message.answer(t("linked", account.lang, email=account.link.user.email, org=org_name))


@router.message(Command("products"))
async def cmd_products(message: Message):
    account = await account_or_reply(message)
    if not account:
        return
    text = await db(services.products_text)(account)
    if not text:
        await message.answer(t("no_products", account.lang))
        return
    await message.answer(t("products_header", account.lang) + "\n\n" + text)


@router.message(Command("check"))
async def cmd_check(message: Message, command: CommandObject):
    account = await account_or_reply(message)
    if not account:
        return
    sku = (command.args or "").strip()
    if not sku:
        await message.answer(t("check_usage", account.lang))
        return
    product = await db(services.find_product)(account, sku)
    if product is None:
        await message.answer(t("sku_not_found", account.lang, sku=sku))
        return
    n = await db(services.queue_check)(product)
    await message.answer(t("check_queued", account.lang, n=n, name=product.name))
    await asyncio.sleep(20)
    summary = await db(services.product_summary)(product.pk, account)
    if summary:
        await message.answer(summary)


@router.message(Command("report"))
async def cmd_report(message: Message):
    account = await account_or_reply(message)
    if account:
        await message.answer(await db(services.digest_text)(account))


@router.message(Command("lang"))
async def cmd_lang(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )
    await message.answer(t("choose_lang", "ru"), reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: Message):
    account = await db(services.get_account)(message.chat.id)
    await message.answer(t("help", account.lang if account else "ru"))


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(call: CallbackQuery):
    lang = call.data.split(":", 1)[1]
    await db(services.set_language)(call.message.chat.id, lang)
    await call.message.edit_text(t("lang_set", lang))
    await call.answer()


@router.callback_query(F.data.startswith("open:"))
async def cb_open(call: CallbackQuery):
    account = await db(services.get_account)(call.message.chat.id)
    if account is None:
        await call.answer(t("not_linked", "ru"), show_alert=True)
        return
    summary = await db(services.product_summary)(int(call.data.split(":")[1]), account)
    await call.message.answer(summary or t("not_found", account.lang))
    await call.answer()


@router.callback_query(F.data.startswith("apply:"))
async def cb_apply(call: CallbackQuery):
    account = await db(services.get_account)(call.message.chat.id)
    if account is None:
        await call.answer(t("not_linked", "ru"), show_alert=True)
        return
    _, product_id, price = call.data.split(":")
    try:
        product = await db(services.apply_price)(account, int(product_id), int(price))
    except PermissionError:
        await call.answer(t("forbidden", account.lang), show_alert=True)
        return
    if product is None:
        await call.answer(t("not_found", account.lang), show_alert=True)
        return
    price_s = f"{int(price):,}".replace(",", " ")
    await call.message.answer(t("price_applied", account.lang, name=product.name, price=price_s))
    await call.answer("✅")


@router.callback_query(F.data.startswith("mute:"))
async def cb_mute(call: CallbackQuery):
    account = await db(services.get_account)(call.message.chat.id)
    if account is None:
        await call.answer(t("not_linked", "ru"), show_alert=True)
        return
    try:
        rule = await db(services.mute_rule)(account, int(call.data.split(":")[1]))
    except PermissionError:
        await call.answer(t("forbidden", account.lang), show_alert=True)
        return
    await call.message.answer(t("muted", account.lang, rule=str(rule)) if rule else t("not_found", account.lang))
    await call.answer()


async def heartbeat() -> None:
    while True:
        with contextlib.suppress(OSError):
            HEARTBEAT.write_text(str(int(time.time())))
        await asyncio.sleep(30)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    hb = asyncio.create_task(heartbeat())
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN is empty — bot is idle. Set it in .env and restart the 'bot' service.")
        await hb
        return
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands(
        [
            BotCommand(command="products", description="Мои товары / My products"),
            BotCommand(command="check", description="Проверить SKU сейчас / Check now"),
            BotCommand(command="report", description="Дайджест / Digest"),
            BotCommand(command="lang", description="Язык / Til / Language"),
        ]
    )
    mode = os.environ.get("BOT_MODE", "polling")
    if mode == "webhook":  # pragma: no cover - needs public HTTPS
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        from aiohttp import web

        url = os.environ["BOT_WEBHOOK_URL"]
        secret = os.environ.get("BOT_WEBHOOK_SECRET") or None
        await bot.set_webhook(url, secret_token=secret, drop_pending_updates=True)
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path="/tg/webhook")
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", 8081).start()
        log.info("Webhook mode on :8081 → %s", url)
        await hb
    else:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Polling mode started")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
