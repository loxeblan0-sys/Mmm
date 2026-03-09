#!/usr/bin/env python3
"""
Telegram-бот для создания Daytona sandbox с Firefox в kiosk-режиме.
"""

import os
import sys
import json
import logging
import threading
import time
import telebot
from telebot import types

# --- Проверка версии Python ---
if sys.version_info < (3, 10):
    print("Требуется Python 3.10+")
    sys.exit(1)

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/bot.log"),
    ],
)
log = logging.getLogger(__name__)

# --- Конфигурация ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DAYTONA_API_KEY = os.environ.get("DAYTONA_API_KEY", "")
SNAPSHOT_NAME = "ubuntu-4vcpu-8ram-100gb"
PROXY_FILE = "/opt/payment-bot/proxies.json"
SESSION_TTL = 420  # 7 минут

if not BOT_TOKEN or not DAYTONA_API_KEY:
    log.error("Не заданы TELEGRAM_BOT_TOKEN или DAYTONA_API_KEY")
    sys.exit(1)

# --- Импорт Daytona SDK ---
try:
    from daytona_sdk import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams
    log.info("Daytona SDK загружен успешно")
except ImportError as e:
    log.error(f"Не удалось импортировать daytona SDK: {e}")
    sys.exit(1)

# --- Инициализация ---
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
daytona = Daytona(DaytonaConfig(api_key=DAYTONA_API_KEY))

# Хранилище активных сессий: {chat_id: sandbox_id}
active_sessions: dict = {}

# ─────────────────────────────────────────────
#  ПРОКСИ
# ─────────────────────────────────────────────

def load_proxies():
    if not os.path.exists(PROXY_FILE):
        return []
    try:
        with open(PROXY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_proxies(proxies):
    os.makedirs(os.path.dirname(PROXY_FILE), exist_ok=True)
    with open(PROXY_FILE, "w") as f:
        json.dump(proxies, f, indent=2, ensure_ascii=False)

def parse_proxy(proxy_str):
    """Парсит строку прокси."""
    s = proxy_str.strip()
    try:
        if "://" in s:
            from urllib.parse import urlparse
            p = urlparse(s)
            proto = p.scheme.upper()
            host = p.hostname
            port = p.port
            user = p.username or ""
            pwd = p.password or ""
        else:
            parts = s.split(":")
            proto = "HTTP"
            if len(parts) == 2:
                host, port, user, pwd = parts[0], int(parts[1]), "", ""
            elif len(parts) == 4:
                host, port, user, pwd = parts[0], int(parts[1]), parts[2], parts[3]
            else:
                return None
        return {"proto": proto, "host": host, "port": int(port), "user": user, "pwd": pwd, "raw": s}
    except Exception:
        return None

def check_proxy(proxy_str):
    """Проверяет прокси через ip-api.com."""
    import requests as req
    p = parse_proxy(proxy_str)
    if not p:
        return False, "Неверный формат"
    try:
        proto = p["proto"].lower()
        auth = f"{p['user']}:{p['pwd']}@" if p["user"] else ""
        if proto in ("http", "https"):
            proxies = {"http": f"http://{auth}{p['host']}:{p['port']}", "https": f"http://{auth}{p['host']}:{p['port']}"}
        else:
            proxies = {"http": f"socks5://{auth}{p['host']}:{p['port']}", "https": f"socks5://{auth}{p['host']}:{p['port']}"}
        r = req.get("http://ip-api.com/json", proxies=proxies, timeout=10)
        data = r.json()
        if data.get("status") == "success":
            return True, f"✅ {data.get('query')} | {data.get('country')} | {data.get('isp')}"
        return False, "Прокси не работает"
    except Exception as e:
        return False, f"Ошибка: {e}"

# ─────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🎵 Spotify (VNC)"),
        types.KeyboardButton("🎮 Discord (VNC)"),
        types.KeyboardButton("🔗 Кастомная ссылка"),
        types.KeyboardButton("🌐 Прокси-меню"),
        types.KeyboardButton("ℹ️ Info"),
        types.KeyboardButton("🆔 ID"),
    )
    return kb

def proxy_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("➕ Добавить прокси"),
        types.KeyboardButton("📋 Список прокси"),
        types.KeyboardButton("✅ Проверить прокси"),
        types.KeyboardButton("📤 Экспорт прокси"),
        types.KeyboardButton("🗑 Удалить прокси"),
        types.KeyboardButton("🔙 Назад"),
    )
    return kb

# ─────────────────────────────────────────────
#  DAYTONA: создание sandbox
# ─────────────────────────────────────────────

def create_vnc_session(chat_id, url, proxy_str=None):
    """Создаёт sandbox, запускает Firefox в kiosk-режиме, возвращает VNC-ссылку."""
    bot.send_message(chat_id, "⏳ Создаю sandbox... Подождите ~30 секунд.")
    try:
        env = {"URL": url, "DISPLAY": ":1"}
        if proxy_str:
            p = parse_proxy(proxy_str)
            if p:
                env["PROXY_HOST"] = str(p["host"])
                env["PROXY_PORT"] = str(p["port"])
                env["PROXY_TYPE"] = p["proto"].lower()
                env["PROXY_USER"] = p.get("user", "")
                env["PROXY_PASS"] = p.get("pwd", "")

        sandbox = daytona.create(
            CreateSandboxFromSnapshotParams(
                snapshot=SNAPSHOT_NAME,
                env=env,
            )
        )
        log.info(f"Sandbox создан: {sandbox.id} для chat_id={chat_id}")
        active_sessions[chat_id] = sandbox.id

        # Ждём пока sandbox полностью стартует (Xvfb, x11vnc, noVNC уже запущены через start.sh)
        bot.send_message(chat_id, "🖥 Запускаю браузер...")
        import time as _time
        _time.sleep(5)  # Даём время start.sh отработать

        # Запускаем Firefox через bash -c (Xvfb/VNC/noVNC уже запущены в образе)
        # Убиваем старый Firefox если был
        try:
            sandbox.process.exec('bash -c "pkill -f firefox 2>/dev/null; sleep 1"', timeout=5)
        except Exception:
            pass

        # Запускаем Firefox с флагами для headless окружения без GPU
        firefox_cmd = (
            f'DISPLAY=:1 MOZ_DISABLE_RDD_SANDBOX=1 '
            f'nohup firefox-esr '
            f'--kiosk "{url}" '
            f'--no-sandbox '
            f'--disable-gpu '
            f'--disable-dev-shm-usage '
            f'--ignore-certificate-errors '
            f'>/tmp/firefox.log 2>&1 &'
        )
        result = sandbox.process.exec(f'bash -c \'{firefox_cmd}\'', timeout=30)
        log.info(f"Firefox launch result: {result.result}")

        # Ждём запуска Firefox
        _time.sleep(5)

        # Получаем VNC-ссылку (подписанная, действует 7 минут = 420 сек)
        signed = sandbox.create_signed_preview_url(6080, expires_in_seconds=420)
        vnc_base = signed.url  # https://6080-TOKEN.daytonaproxy01.net
        vnc_lite = f"{vnc_base}/vnc_lite.html?autoconnect=1&reconnect=1"

        proxy_line = f"\n🌐 <b>Прокси:</b> <code>{proxy_str}</code>" if proxy_str else ""
        msg = (
            f"✅ <b>Сессия готова!</b>\n\n"
            f"🌐 <b>URL:</b> <code>{url}</code>{proxy_line}\n\n"
            f"🖥 <b>VNC-ссылка (7 мин):</b>\n{vnc_lite}\n\n"
            f"⏱ Сессия удалится через 7 минут.\n"
            f"🆔 ID: <code>{sandbox.id}</code>"
        )
        bot.send_message(chat_id, msg, disable_web_page_preview=True)

        # Удаляем sandbox через 7 минут
        def delete_later():
            time.sleep(SESSION_TTL)
            try:
                sandbox.delete()
                active_sessions.pop(chat_id, None)
                bot.send_message(chat_id, "🗑 Сессия завершена и удалена.")
                log.info(f"Sandbox {sandbox.id} удалён")
            except Exception as e:
                log.error(f"Ошибка при удалении sandbox {sandbox.id}: {e}")

        threading.Thread(target=delete_later, daemon=True).start()

    except Exception as e:
        err = str(e)
        log.error(f"Ошибка создания sandbox: {err}")
        # Если превышен лимит диска — автоматически чистим старые sandbox
        if "disk limit" in err.lower() or "Total disk limit" in err:
            bot.send_message(chat_id, "⚠️ Лимит диска исчерпан. Автоматически удаляю старые сессии...")
            try:
                sandboxes = daytona.list()
                deleted = 0
                for sb in sandboxes:
                    try:
                        sb.delete()
                        deleted += 1
                    except Exception:
                        pass
                if deleted > 0:
                    bot.send_message(chat_id, f"🗑 Удалено {deleted} старых сессий. Пробую снова...")
                    time.sleep(3)
                    create_vnc_session(chat_id, url, proxy_str)
                    return
                else:
                    bot.send_message(chat_id, "❌ Не удалось освободить место. Зайди на app.daytona.io и удали старые sandbox вручную.")
            except Exception as ce:
                log.error(f"Ошибка при очистке: {ce}")
                bot.send_message(chat_id, "❌ Лимит диска исчерпан. Зайди на app.daytona.io → Sandboxes и удали старые сессии.")
        else:
            bot.send_message(chat_id, f"❌ Ошибка при создании сессии:\n<code>{err}</code>")

# ─────────────────────────────────────────────
#  ОБРАБОТЧИКИ КОМАНД
# ─────────────────────────────────────────────

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "👋 <b>Привет!</b>\n\nЯ создаю изолированные браузерные сессии для безопасных платежей.\n\nВыбери действие:",
        reply_markup=main_keyboard(),
    )

@bot.message_handler(commands=["id"])
def cmd_id(message):
    bot.send_message(message.chat.id, f"🆔 Ваш Telegram ID: <code>{message.chat.id}</code>")

# ─────────────────────────────────────────────
#  ОБРАБОТЧИКИ КНОПОК
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🎵 Spotify (VNC)")
def btn_spotify(message):
    proxies = load_proxies()
    proxy = proxies[0] if proxies else None
    url = "https://accounts.spotify.com/uk/login?continue=https%3A%2F%2Fopen.spotify.com%2Fartist%2F65di5PBniO97sBvpK6lW49"
    threading.Thread(target=create_vnc_session, args=(message.chat.id, url, proxy), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "🎮 Discord (VNC)")
def btn_discord(message):
    proxies = load_proxies()
    proxy = proxies[0] if proxies else None
    threading.Thread(target=create_vnc_session, args=(message.chat.id, "https://discord.com/app", proxy), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "🔗 Кастомная ссылка")
def btn_custom(message):
    msg = bot.send_message(message.chat.id, "🔗 Отправь ссылку (например: https://example.com):")
    bot.register_next_step_handler(msg, handle_custom_url)

def handle_custom_url(message):
    url = message.text.strip()
    if not url.startswith("http"):
        url = "https://" + url
    proxies = load_proxies()
    proxy = proxies[0] if proxies else None
    threading.Thread(target=create_vnc_session, args=(message.chat.id, url, proxy), daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "ℹ️ Info")
def btn_info(message):
    proxies = load_proxies()
    active = active_sessions.get(message.chat.id, "нет")
    bot.send_message(
        message.chat.id,
        f"ℹ️ <b>Информация о боте</b>\n\n"
        f"🔧 <b>Снапшот:</b> <code>{SNAPSHOT_NAME}</code>\n"
        f"⏱ <b>TTL сессии:</b> 7 минут\n"
        f"🌐 <b>Прокси в базе:</b> {len(proxies)} шт.\n"
        f"🖥 <b>Активная сессия:</b> <code>{active}</code>\n\n"
        f"<b>Поддерживаемые сервисы:</b> Spotify, Discord, любой URL",
    )

@bot.message_handler(func=lambda m: m.text == "🆔 ID")
def btn_id(message):
    bot.send_message(message.chat.id, f"🆔 Ваш Telegram ID: <code>{message.chat.id}</code>")

# ─────────────────────────────────────────────
#  ПРОКСИ-МЕНЮ
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "🌐 Прокси-меню")
def btn_proxy_menu(message):
    proxies = load_proxies()
    bot.send_message(
        message.chat.id,
        f"🌐 <b>Прокси-меню</b>\nВ базе: <b>{len(proxies)}</b> прокси",
        reply_markup=proxy_keyboard(),
    )

@bot.message_handler(func=lambda m: m.text == "➕ Добавить прокси")
def btn_add_proxy(message):
    msg = bot.send_message(
        message.chat.id,
        "➕ Отправь прокси в одном из форматов:\n"
        "<code>ip:port</code>\n"
        "<code>ip:port:user:pass</code>\n"
        "<code>socks5://ip:port</code>\n"
        "<code>http://user:pass@ip:port</code>\n\n"
        "Можно несколько — каждый с новой строки.",
    )
    bot.register_next_step_handler(msg, handle_add_proxy)

def handle_add_proxy(message):
    lines = message.text.strip().splitlines()
    added, failed = 0, 0
    proxies = load_proxies()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if parse_proxy(line):
            if line not in proxies:
                proxies.append(line)
                added += 1
        else:
            failed += 1
    save_proxies(proxies)
    bot.send_message(
        message.chat.id,
        f"✅ Добавлено: <b>{added}</b>\n❌ Неверный формат: <b>{failed}</b>\n📋 Всего: <b>{len(proxies)}</b>",
        reply_markup=proxy_keyboard(),
    )

@bot.message_handler(func=lambda m: m.text == "📋 Список прокси")
def btn_list_proxies(message):
    proxies = load_proxies()
    if not proxies:
        bot.send_message(message.chat.id, "📋 Список прокси пуст.", reply_markup=proxy_keyboard())
        return
    chunk_size = 50
    for i in range(0, len(proxies), chunk_size):
        chunk = proxies[i:i+chunk_size]
        text = f"📋 <b>Прокси [{i+1}-{i+len(chunk)}]:</b>\n" + "\n".join(f"<code>{p}</code>" for p in chunk)
        bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "✅ Проверить прокси")
def btn_check_proxy(message):
    proxies = load_proxies()
    if not proxies:
        bot.send_message(message.chat.id, "❌ Список прокси пуст.", reply_markup=proxy_keyboard())
        return
    msg = bot.send_message(message.chat.id, f"🔍 Проверяю {min(len(proxies), 10)} прокси...")

    def do_check():
        results = []
        for p in proxies[:10]:
            ok, info = check_proxy(p)
            results.append(f"{'✅' if ok else '❌'} <code>{p}</code>\n   {info}")
        text = "\n\n".join(results)
        if len(proxies) > 10:
            text += f"\n\n<i>Показаны первые 10 из {len(proxies)}</i>"
        try:
            bot.edit_message_text(text, message.chat.id, msg.message_id)
        except Exception:
            bot.send_message(message.chat.id, text)

    threading.Thread(target=do_check, daemon=True).start()

@bot.message_handler(func=lambda m: m.text == "📤 Экспорт прокси")
def btn_export_proxies(message):
    proxies = load_proxies()
    if not proxies:
        bot.send_message(message.chat.id, "❌ Список прокси пуст.", reply_markup=proxy_keyboard())
        return
    export_path = "/tmp/proxies_export.txt"
    with open(export_path, "w") as f:
        f.write("\n".join(proxies))
    with open(export_path, "rb") as f:
        bot.send_document(message.chat.id, f, caption=f"📤 Экспорт {len(proxies)} прокси")

@bot.message_handler(func=lambda m: m.text == "🗑 Удалить прокси")
def btn_delete_proxy(message):
    msg = bot.send_message(
        message.chat.id,
        "🗑 Отправь прокси для удаления или напиши <b>all</b> для очистки всего списка:",
    )
    bot.register_next_step_handler(msg, handle_delete_proxy)

def handle_delete_proxy(message):
    proxies = load_proxies()
    if message.text.strip().lower() == "all":
        save_proxies([])
        bot.send_message(message.chat.id, "🗑 Все прокси удалены.", reply_markup=proxy_keyboard())
        return
    to_delete = message.text.strip()
    if to_delete in proxies:
        proxies.remove(to_delete)
        save_proxies(proxies)
        bot.send_message(message.chat.id, f"✅ Прокси удалён. Осталось: {len(proxies)}", reply_markup=proxy_keyboard())
    else:
        bot.send_message(message.chat.id, "❌ Прокси не найден в списке.", reply_markup=proxy_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def btn_back(message):
    bot.send_message(message.chat.id, "🏠 Главное меню:", reply_markup=main_keyboard())

# ─────────────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info(f"Python: {sys.version}")
    log.info(f"Snapshot: {SNAPSHOT_NAME}")
    log.info("Бот запущен")
    log.info("=" * 50)
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
