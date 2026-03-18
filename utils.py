import json
import os

BASE_DIR = "server_data"

def get_guild_path(guild_id: int, filename: str) -> str:
    """Створює папку для сервера, якщо її немає, і повертає шлях до файлу."""
    folder = os.path.join(BASE_DIR, str(guild_id))
    if not os.path.exists(folder):
        os.makedirs(folder)
    return os.path.join(folder, filename)

def load_guild_json(guild_id: int, filename: str):
    """Завантажує JSON файл конкретного сервера."""
    path = get_guild_path(guild_id, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_guild_json(guild_id: int, filename: str, data):
    """Зберігає JSON файл конкретного сервера."""
    path = get_guild_path(guild_id, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)