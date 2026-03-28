import os
import re
import time

import feedparser
import requests
from dotenv import load_dotenv

from src.telegram_bot import send_news

load_dotenv()
RSS_FEEDS = [
    'https://nitter.net/Fxhedgers/rss',
    'https://nitter.net/zerohedge/rss',
    'https://nitter.net/financialjuice/rss',
    'https://nitter.net/DeItaone/rss',
]
KEYWORDS = [
    'gold', 'xau', 'usd', 'dollar',
    'fed', 'inflation', 'interest rate',
    'iran', 'war', 'oil',
]
CHECK_INTERVAL = 30
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
sent_news = set()


def is_relevant(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def get_news_type(text):
    lowered = text.lower()
    if any(k in lowered for k in ['cpi', 'nfp', 'gdp', 'ppi', 'interest rate', 'fed', 'inflation']):
        return 'ECONOMIC'
    if any(k in lowered for k in ['war', 'iran', 'military', 'attack', 'conflict', 'oil']):
        return 'GEOPOLITICAL'
    return 'MARKET'


def detect_event(text):
    lowered = text.lower()
    if 'cpi' in lowered or 'inflation' in lowered:
        return 'CPI'
    if 'nfp' in lowered or 'nonfarm' in lowered:
        return 'NFP'
    if 'gdp' in lowered:
        return 'GDP'
    if 'interest rate' in lowered or 'rate decision' in lowered or 'fed rate' in lowered:
        return 'RATE'
    if 'ppi' in lowered:
        return 'PPI'
    return None


def extract_numbers(text):
    return re.findall(r'\d+\.\d+%|\d+K', text)


def get_strength(actual, forecast):
    try:
        a = float(actual.replace('%', '').replace('K', ''))
        f = float(forecast.replace('%', '').replace('K', ''))
        diff = abs(a - f)
        if diff >= 0.3:
            return 'STRONG'
        if diff >= 0.1:
            return 'MEDIUM'
        return 'WEAK'
    except Exception:
        return '-'


def get_reaction(event, actual, forecast):
    try:
        a = float(actual.replace('%', '').replace('K', ''))
        f = float(forecast.replace('%', '').replace('K', ''))
        if event == 'CPI':
            return 'USD naik -> Gold turun' if a > f else 'USD turun -> Gold naik'
        if event == 'NFP':
            return 'Job kuat -> Gold turun' if a > f else 'Job lemah -> Gold naik'
        if event == 'GDP':
            return 'Ekonomi kuat -> Gold turun' if a > f else 'Ekonomi lemah -> Gold naik'
        if event == 'RATE':
            return 'Hawkish -> Gold turun' if a > f else 'Dovish -> Gold naik'
        if event == 'PPI':
            return 'Inflasi naik -> Gold turun' if a > f else 'Inflasi turun -> Gold naik'
    except Exception:
        pass
    return 'Tunggu konfirmasi market'


def translate_ai(text):
    if not GROQ_API_KEY:
        return None
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'llama3-70b-8192',
                'messages': [
                    {'role': 'system', 'content': 'Terjemahkan ke bahasa Indonesia, singkat.'},
                    {'role': 'user', 'content': text},
                ],
            },
            timeout=10,
        )
        return response.json()['choices'][0]['message']['content']
    except Exception:
        return None


def check_news():
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.title.strip().replace('\n', ' ')
            if title in sent_news or not is_relevant(title):
                continue
            news_type = get_news_type(title)
            event = detect_event(title)
            if event:
                nums = extract_numbers(title)
                actual = nums[0] if len(nums) > 0 else '-'
                forecast = nums[1] if len(nums) > 1 else '-'
                strength = get_strength(actual, forecast)
                reaction = get_reaction(event, actual, forecast)
                msg = f"""
🟥 ECONOMIC NEWS ({event})
{title}
━━━━━━━━━━━━━━━━━━
Actual   : {actual}
Forecast : {forecast}
Strength : {strength}
━━━━━━━━━━━━━━━━━━
📊 Reaction:
{reaction}
━━━━━━━━━━━━━━━━━━
📍 Note:
Tunggu breakout dan retest
"""
                send_news(msg, 'ECONOMIC')
                sent_news.add(title)
                continue
            indo = translate_ai(title)
            send_news(title, news_type, indo)
            sent_news.add(title)


def run():
    print('NEWS ROUTER RUNNING...')
    while True:
        try:
            check_news()
        except Exception as e:
            print('ERROR:', e)
        time.sleep(CHECK_INTERVAL)
