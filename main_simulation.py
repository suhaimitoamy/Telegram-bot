import argparse
import json

from src.simulator import run_simulation


def main():
    parser = argparse.ArgumentParser(description='Run historical simulation for the trading bot')
    parser.add_argument('--bars', type=int, default=800, help='Number of 5 minute candles to fetch')
    parser.add_argument(
        '--output',
        type=str,
        default='data/simulation_report.json',
        help='Path to the JSON report file',
    )
    args = parser.parse_args()
    result = run_simulation(limit=args.bars, output_path=args.output)
    print(json.dumps({
        'symbol': result.symbol,
        'bars': result.bars,
        'fill_model': result.fill_model,
        'setup_count': result.setup_count,
        'entry_count': result.entry_count,
        'win_count': result.win_count,
        'loss_count': result.loss_count,
        'open_count': result.open_count,
        'winrate': result.winrate,
        'blocker_counts': result.blocker_counts,
        'report': args.output,
        'warnings': result.warnings,
    }, indent=2))


if __name__ == '__main__':
    main()
