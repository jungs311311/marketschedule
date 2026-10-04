from __future__ import annotations

import json
import mimetypes
import urllib.parse
import uuid
from pathlib import Path

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

    def send_photo(self, chat_id: str, photo: str | Path, caption: str = '') -> int:
        """이미지 한 장을 보낸다. multipart/form-data로 파일을 직접 올린다."""
        file = Path(photo)
        boundary = uuid.uuid4().hex
        fields = {'chat_id': chat_id}
        if caption:
            fields['caption'] = caption
        parts = bytearray()
        for name, value in fields.items():
            parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                      f'\r\n\r\n{value}\r\n').encode('utf-8')
        mime = mimetypes.guess_type(file.name)[0] or 'image/png'
        parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
                  f'filename="{file.name}"\r\nContent-Type: {mime}\r\n\r\n').encode('utf-8')
        parts += file.read_bytes() + f'\r\n--{boundary}--\r\n'.encode('utf-8')
        url = f'https://api.telegram.org/bot{self.token}/sendPhoto'
        raw = self.client.request_bytes(url, bytes(parts),
            {'Content-Type': f'multipart/form-data; boundary={boundary}'}).decode('utf-8')
        result = json.loads(raw)
        if not result.get('ok'):
            raise RuntimeError('Telegram 사진 전송이 거절되었습니다: ' + str(result.get('description', 'unknown')))
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
