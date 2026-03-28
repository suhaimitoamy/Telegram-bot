import json
from pathlib import Path

DATA_DIR = Path('data')
FILE = DATA_DIR / 'memory.json'


def ensure_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FILE.exists():
        FILE.write_text('[]', encoding='utf-8')


def load_memory():
    ensure_file()
    with open(FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_memory(data):
    ensure_file()
    with open(FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def log_trade(trade):
    data = load_memory()
    data.append(trade)
    save_memory(data[-200:])
