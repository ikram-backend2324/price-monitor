"""Bot UI strings (ru / uz / en). Kept separate from Django .po files so the bot
stays a self-contained service; alert/digest bodies come from Django i18n."""

TEXTS: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "👋 Привет! Я бот <b>PriceWatch</b> — слежу за ценами конкурентов.\n\nЧтобы привязать аккаунт, откройте веб-кабинет → Telegram и отправьте мне код: <code>/start КОД</code>",
        "uz": "👋 Salom! Men <b>PriceWatch</b> botiman — raqobatchilar narxlarini kuzataman.\n\nAkkauntni ulash uchun veb-kabinet → Telegram bo'limidan kodni oling va yuboring: <code>/start KOD</code>",
        "en": "👋 Hi! I'm the <b>PriceWatch</b> bot — I watch your competitors' prices.\n\nTo link your account open the dashboard → Telegram and send me the code: <code>/start CODE</code>",
    },
    "linked": {
        "ru": "✅ Аккаунт {email} привязан. Организация: <b>{org}</b>.\nКоманды: /products, /check SKU, /report, /lang",
        "uz": "✅ {email} akkaunti ulandi. Tashkilot: <b>{org}</b>.\nBuyruqlar: /products, /check SKU, /report, /lang",
        "en": "✅ Account {email} linked. Organization: <b>{org}</b>.\nCommands: /products, /check SKU, /report, /lang",
    },
    "already": {
        "ru": "Вы уже привязаны как {email}. Команды: /products, /check SKU, /report, /lang",
        "uz": "Siz {email} sifatida ulangansiz. Buyruqlar: /products, /check SKU, /report, /lang",
        "en": "You are linked as {email}. Commands: /products, /check SKU, /report, /lang",
    },
    "bad_code": {
        "ru": "❌ Код неверный или устарел. Получите новый в веб-кабинете → Telegram.",
        "uz": "❌ Kod noto'g'ri yoki eskirgan. Veb-kabinet → Telegram bo'limidan yangisini oling.",
        "en": "❌ The code is invalid or expired. Get a new one in the dashboard → Telegram.",
    },
    "not_linked": {
        "ru": "Сначала привяжите аккаунт: /start КОД (код — в веб-кабинете → Telegram).",
        "uz": "Avval akkauntni ulang: /start KOD (kod veb-kabinet → Telegram bo'limida).",
        "en": "Link your account first: /start CODE (the code is in the dashboard → Telegram).",
    },
    "no_products": {
        "ru": "Пока нет товаров. Добавьте их в веб-кабинете.",
        "uz": "Hozircha mahsulotlar yo'q. Ularni veb-kabinetda qo'shing.",
        "en": "No products yet. Add them in the dashboard.",
    },
    "products_header": {
        "ru": "📦 <b>Мои товары</b> (моя цена | мин. у конкурентов)",
        "uz": "📦 <b>Mahsulotlarim</b> (mening narxim | raqobatchilarda eng arzon)",
        "en": "📦 <b>My products</b> (my price | cheapest competitor)",
    },
    "check_usage": {"ru": "Использование: /check SKU", "uz": "Foydalanish: /check SKU", "en": "Usage: /check SKU"},
    "sku_not_found": {
        "ru": "Товар с SKU {sku} не найден.",
        "uz": "{sku} SKU'li mahsulot topilmadi.",
        "en": "Product with SKU {sku} not found.",
    },
    "check_queued": {
        "ru": "🔄 Проверяю {n} ссылок для {name}… Результат пришлю через ~20 сек.",
        "uz": "🔄 {name} uchun {n} ta havola tekshirilmoqda… Natija ~20 soniyada.",
        "en": "🔄 Checking {n} links for {name}… Results in ~20 s.",
    },
    "choose_lang": {"ru": "Выберите язык:", "uz": "Tilni tanlang:", "en": "Choose a language:"},
    "lang_set": {"ru": "Язык: русский 🇷🇺", "uz": "Til: o'zbekcha 🇺🇿", "en": "Language: English 🇬🇧"},
    "price_applied": {
        "ru": "✅ Новая цена {name}: {price} сум",
        "uz": "✅ {name} uchun yangi narx: {price} so'm",
        "en": "✅ New price for {name}: {price} UZS",
    },
    "forbidden": {
        "ru": "⛔ Недостаточно прав (нужна роль владелец/менеджер).",
        "uz": "⛔ Huquq yetarli emas (egasi/menejer roli kerak).",
        "en": "⛔ Not allowed (owner/manager role required).",
    },
    "muted": {
        "ru": "🔕 Правило «{rule}» отключено. Включить снова можно в веб-кабинете.",
        "uz": "🔕 «{rule}» qoidasi o'chirildi. Uni veb-kabinetda qayta yoqish mumkin.",
        "en": "🔕 Rule “{rule}” disabled. Re-enable it in the dashboard.",
    },
    "not_found": {"ru": "Не найдено.", "uz": "Topilmadi.", "en": "Not found."},
    "help": {
        "ru": "/products — мои товары\n/check SKU — проверить сейчас\n/report — дайджест\n/lang — язык",
        "uz": "/products — mahsulotlarim\n/check SKU — hozir tekshirish\n/report — dayjest\n/lang — til",
        "en": "/products — my products\n/check SKU — check now\n/report — digest\n/lang — language",
    },
}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    variants = TEXTS[key]
    return variants.get(lang, variants["ru"]).format(**kwargs)
