import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path('data')
FILE = DATA_DIR / 'engine_memory.json'
DEFAULT = {
    'alerts': [],
    'levels': {},
    'last_check': ''
}


def ensure_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FILE.exists():
        with open(FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT, f, indent=2)


def load_memory():
    ensure_file()
    with open(FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_memory(memory):
    ensure_file()
    with open(FILE, 'w', encoding='utf-8') as f:
        json.dump(memory, f, indent=2)


def alert_already_sent(memory, key):
    return key in memory.get('alerts', [])


def mark_alert_sent(memory, key):
    if key not in memory['alerts']:
        memory['alerts'].append(key)
        memory['last_check'] = datetime.utcnow().isoformat()
        save_memory(memory)


def reset_alerts():
    memory = load_memory()
    memory['alerts'] = []
    save_memory(memory)
