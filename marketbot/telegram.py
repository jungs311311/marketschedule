from __future__ import annotations

import json
import urllib.parse

from .http import HttpClient


class Telegram:
    def __init__(self, token: str, client: HttpClient | None = None):
        if not token or ':' not in token:
            raise ValueError('MARKET_BOT_TOKEN이 없거나 형식이 올바르지 않습니다')
        self.token = token
        self.client = client or HttpClient()

    def call(self, method: str, values: dict) -> dict:
        url = f'https://api.telegram.org/bot{self.token}/{method}'
        payload = urllib.parse.urlencode(values).encode('utf-8')
        # FetchError never includes the URL, preventing token leakage in logs.
        raw = self.client.request_bytes(url, payload,
            {'Content-Type': 'application/x-www-form-urlencoded'}).decode('utf-8')
        result = json.loads(raw)
        if not result.get('ok'):
            raise RuntimeError('Telegram API 요청이 거절되었습니다: ' + str(result.get('description', 'unknown')))
        return result

    def send(self, chat_id: str, message: str) -> int:
        result = self.call('sendMessage', {
            'chat_id': chat_id, 'text': message,
            'disable_web_page_preview': 'true',
        })
        return int(result['result']['message_id'])

    def bot_username(self) -> str:
        result = self.call('getMe', {})
        return str(result['result']['username'])

    def chat_candidates(self) -> list[tuple[str, str]]:
        result = self.call('getUpdates', {'limit': 100, 'timeout': 0})
        found = {}
        for update in result.get('result', []):
            message = update.get('message') or update.get('channel_post') or {}
            chat = message.get('chat') or {}
            if 'id' in chat:
                label = chat.get('title') or chat.get('username') or '개인 채팅'
                found[str(chat['id'])] = str(label)
        return sorted(found.items())
