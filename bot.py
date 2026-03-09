
import telebot
import requests
import json
import os
import threading
import time
from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams

# --- Configuration ---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DAYTONA_API_KEY = os.environ.get("DAYTONA_API_KEY", "YOUR_DAYTONA_API_KEY")
SNAPSHOT_NAME = "firefox-vnc-snapshot"
PROXY_FILE = "proxies.json"

# --- Initialize bot and Daytona ---
bot = telebot.TeleBot(BOT_TOKEN)
daytona_config = DaytonaConfig(api_key=DAYTONA_API_KEY)
daytona = Daytona(daytona_config)

# --- Proxy Management ---

def load_proxies():
    if not os.path.exists(PROXY_FILE):
        return []
    with open(PROXY_FILE, 'r') as f:
        return json.load(f)

def save_proxies(proxies):
    with open(PROXY_FILE, 'w') as f:
        json.dump(proxies, f, indent=4)

def add_proxy(proxy_str):
    proxies = load_proxies()
    proxies.append(proxy_str)
    save_proxies(proxies)

def get_random_proxy():
    proxies = load_proxies()
    if not proxies:
        return None
    return proxies[0] # For now, just return the first one

# --- Bot Handlers ---

@bot.message_handler(commands=["start"])
def send_welcome(message):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2)
    itembtn1 = telebot.types.KeyboardButton("Spotify (VNC)")
    itembtn2 = telebot.types.KeyboardButton("Discord (VNC)")
    itembtn3 = telebot.types.KeyboardButton("Кастомная ссылка")
    itembtn4 = telebot.types.KeyboardButton("Прокси-меню")
    itembtn5 = telebot.types.KeyboardButton("Info")
    itembtn6 = telebot.types.KeyboardButton("ID")
    markup.add(itembtn1, itembtn2, itembtn3, itembtn4, itembtn5, itembtn6)
    bot.send_message(message.chat.id, "Привет! Я бот для создания безопасных платежных окружений.", reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.text == "Spotify (VNC)":
        create_sandbox_and_get_vnc(message.chat.id, "https://accounts.spotify.com/uk/login?continue=https%3A%2F%2Fopen.spotify.com%2Fartist%2F65di5PBniO97sBvpK6lW49")
    elif message.text == "Discord (VNC)":
        create_sandbox_and_get_vnc(message.chat.id, "https://discord.com/app")
    elif message.text == "Кастомная ссылка":
        bot.send_message(message.chat.id, "Отправь мне ссылку:")
        bot.register_next_step_handler(message, handle_custom_url)
    elif message.text == "Прокси-меню":
        send_proxy_menu(message.chat.id)
    elif message.text == "Info":
        bot.send_message(message.chat.id, "Этот бот создает временные и безопасные окружения для онлайн-платежей.")
    elif message.text == "ID":
        bot.send_message(message.chat.id, f"Ваш ID: {message.chat.id}")

def handle_custom_url(message):
    create_sandbox_and_get_vnc(message.chat.id, message.text)


# --- Daytona Integration ---

def create_sandbox_and_get_vnc(chat_id, url):
    bot.send_message(chat_id, "Создаю сессию... Это может занять несколько минут.")
    try:
        # Create a sandbox from the snapshot
        sandbox = daytona.create(
            CreateSandboxFromSnapshotParams(
                snapshot=SNAPSHOT_NAME,
                # Pass the URL as an environment variable to the container
                env={"URL": url}
            )
        )

        bot.send_message(chat_id, f"Сессия `{sandbox.id}` создана. Запускаю VNC...")

        # Start VNC processes
        sandbox.computer_use.start()

        # Get a signed preview URL for the VNC (port 6080 is where noVNC is listening)
        signed_url = sandbox.create_signed_preview_url(6080, expires_in_seconds=420) # 7 minutes

        bot.send_message(chat_id, f"VNC-ссылка (действует 7 минут): {signed_url.url}")

        # Schedule sandbox deletion
        threading.Timer(420, lambda: sandbox.delete()).start()

    except Exception as e:
        bot.send_message(chat_id, f"Произошла ошибка: {e}")


# --- Proxy Menu ---

def send_proxy_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2)
    itembtn1 = telebot.types.KeyboardButton("Добавить прокси")
    itembtn2 = telebot.types.KeyboardButton("Список прокси")
    itembtn3 = telebot.types.KeyboardButton("Проверить прокси")
    itembtn4 = telebot.types.KeyboardButton("Назад")
    markup.add(itembtn1, itembtn2, itembtn3, itembtn4)
    bot.send_message(chat_id, "Меню управления прокси:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "Добавить прокси")
def handle_add_proxy(message):
    bot.send_message(message.chat.id, "Отправь прокси в формате IP:port:user:pass или IP:port")
    bot.register_next_step_handler(message, save_proxy_handler)

def save_proxy_handler(message):
    add_proxy(message.text)
    bot.send_message(message.chat.id, "Прокси добавлен.")
    send_proxy_menu(message.chat.id)

@bot.message_handler(func=lambda message: message.text == "Список прокси")
def handle_list_proxies(message):
    proxies = load_proxies()
    if not proxies:
        bot.send_message(message.chat.id, "Список прокси пуст.")
        return
    proxy_list = "\n".join(proxies)
    bot.send_message(message.chat.id, f"Список прокси:\n{proxy_list}")

@bot.message_handler(func=lambda message: message.text == "Проверить прокси")
def handle_check_proxy(message):
    # Placeholder for proxy checking logic
    bot.send_message(message.chat.id, "Функция проверки прокси в разработке.")

@bot.message_handler(func=lambda message: message.text == "Назад")
def handle_back_to_main_menu(message):
    send_welcome(message)

# --- Main Loop ---
if __name__ == "__main__":
    print("Bot is running...")
    bot.polling()
