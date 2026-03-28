from src.ws_client import run_ws


if __name__ == '__main__':
    try:
        print('WS CLIENT RUNNING (BALANCED MODE)...')
        run_ws()
    except KeyboardInterrupt:
        print('\nWS STOPPED')
