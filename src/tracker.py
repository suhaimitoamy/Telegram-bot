from src.trade_memory import load_memory, save_memory


def update_results(current_price):
    data = load_memory()
    updated = False
    for trade in data:
        if trade.get('result') != 'open':
            continue
        sl = trade['sl']
        tp = trade['tp']
        if trade['signal'] == 'BUY':
            if current_price <= sl:
                trade['result'] = 'loss'
                updated = True
            elif current_price >= tp:
                trade['result'] = 'win'
                updated = True
        elif trade['signal'] == 'SELL':
            if current_price >= sl:
                trade['result'] = 'loss'
                updated = True
            elif current_price <= tp:
                trade['result'] = 'win'
                updated = True
    if updated:
        save_memory(data)
