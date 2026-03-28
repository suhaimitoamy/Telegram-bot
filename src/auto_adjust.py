import json
from pathlib import Path

from src.trade_memory import load_memory

CONFIG_FILE = Path('config.json')
DEFAULT_CONFIG = {
    'use_retest': True,
    'use_impulse': False,
    'allow_counter': False,
    'min_rr': 2.0,
}


def load_config():
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


def winrate(items):
    if not items:
        return 0.0
    wins = sum(1 for item in items if item.get('result') == 'win')
    return (wins / len(items)) * 100


def auto_adjust(min_samples=20):
    memory = load_memory()
    config = load_config()
    closed = [d for d in memory if d.get('result') in ['win', 'loss']]
    if len(closed) < min_samples:
        print(f'Data kurang ({len(closed)}/{min_samples})')
        return
    with_impulse = [d for d in closed if d.get('context', {}).get('impulse')]
    no_impulse = [d for d in closed if not d.get('context', {}).get('impulse')]
    counter = [d for d in closed if d.get('context', {}).get('state') == 'COUNTER']
    total_wr = winrate(closed)
    if len(no_impulse) >= 5 and winrate(no_impulse) < 40:
        config['use_impulse'] = True
    if len(counter) >= 5 and winrate(counter) < 35:
        config['allow_counter'] = False
    if total_wr < 45:
        config['min_rr'] = max(1.5, config.get('min_rr', 2.0) - 0.2)
    elif total_wr > 60:
        config['min_rr'] = min(3.0, config.get('min_rr', 2.0) + 0.2)
    save_config(config)
    print(json.dumps(config, indent=2))


if __name__ == '__main__':
    auto_adjust()
