# Telegram-bot

Bot ini sekarang fokus sebagai **market reader** untuk trader manual.

Fungsi utamanya:
- membaca level keputusan market dari `config.json`
- memantau harga live lewat Twelve Data WebSocket
- mengonfirmasi skenario penting dengan candle 5 menit
- mengirim narasi market ke Telegram
- **tidak** melakukan auto entry, auto TP/SL, atau tracking hasil trade

## Struktur repo

- `main.py` -> entrypoint utama
- `src/config.py` -> loader konfigurasi
- `src/market_reader.py` -> aturan pembacaan market
- `src/telegram_bot.py` -> pengirim pesan Telegram
- `src/ws_client.py` -> client websocket live price

## Setup cepat di Termux

```bash
pkg update && pkg upgrade
pkg install python git
git clone https://github.com/suhaimitoamy/Telegram-bot.git
cd Telegram-bot
pip install -r requirements.txt
cp .env.example .env
nano .env
nano config.json
python main.py
```

## Isi `.env`

```env
TWELVE_API_KEY=isi_api_key_twelvedata
TELEGRAM_BOT_TOKEN=isi_token_bot_telegram
TELEGRAM_CHAT_ID=isi_chat_id_telegram
```

## Ubah level market di `config.json`

Bot ini membaca market berdasarkan level yang Anda gambar sendiri.
Edit bagian `levels` sesuai chart Anda.

Contoh default saat ini:
- lower_decision
- upper_supply
- upper_breakout
- upper_extreme

## Cara kerja bot

1. bootstrap candle 5 menit dari Twelve Data
2. subscribe live tick harga
3. bentuk candle live per 5 menit
4. baca state market:
   - near lower range
   - bounce confirmed
   - breakdown confirmed
   - upper rejection
   - breakout confirmed
5. kirim narasi Telegram hanya saat state berubah

## Catatan penting

Bot ini sengaja didesain untuk **manual execution**.
Artinya:
- bot membaca market
- bot menjelaskan skenario aktif
- keputusan entry tetap oleh manusia
