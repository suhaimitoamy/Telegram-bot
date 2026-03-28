from src.trade_memory import load_memory


def evaluate():
    data = load_memory()
    if not data:
        print('No data')
        return
    closed = [d for d in data if d.get('result') in ['win', 'loss']]
    if not closed:
        print('No closed trades yet')
        return
    total = len(closed)
    wins = sum(1 for d in closed if d['result'] == 'win')
    losses = sum(1 for d in closed if d['result'] == 'loss')
    winrate = (wins / total) * 100
    print('\nEVALUATION RESULT')
    print('━━━━━━━━━━━━━━━━━━')
    print(f'Total Trades : {total}')
    print(f'Wins         : {wins}')
    print(f'Losses       : {losses}')
    print(f'Winrate      : {winrate:.2f}%')
    print('\nCONTEXT ANALYSIS')
    print('━━━━━━━━━━━━━━━━━━')
    impulse_win = 0
    impulse_total = 0
    no_impulse_win = 0
    no_impulse_total = 0
    state_stats = {}
    for trade in closed:
        ctx = trade.get('context', {})
        if ctx.get('impulse'):
            impulse_total += 1
            if trade['result'] == 'win':
                impulse_win += 1
        else:
            no_impulse_total += 1
            if trade['result'] == 'win':
                no_impulse_win += 1
        state = ctx.get('state', 'UNKNOWN')
        if state not in state_stats:
            state_stats[state] = {'win': 0, 'total': 0}
        state_stats[state]['total'] += 1
        if trade['result'] == 'win':
            state_stats[state]['win'] += 1
    if impulse_total > 0:
        print(f'With Impulse : {(impulse_win / impulse_total) * 100:.2f}% ({impulse_total} trades)')
    if no_impulse_total > 0:
        print(f'No Impulse   : {(no_impulse_win / no_impulse_total) * 100:.2f}% ({no_impulse_total} trades)')
    print('\nSTATE ANALYSIS')
    print('━━━━━━━━━━━━━━━━━━')
    for state, values in state_stats.items():
        wr = (values['win'] / values['total']) * 100
        print(f'{state:10} : {wr:.2f}% ({values["total"]})')


if __name__ == '__main__':
    evaluate()
