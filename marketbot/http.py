from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import urllib.parse

from bs4 import BeautifulSoup
from pypdf import PdfReader


class FetchError(RuntimeError):
    pass


class HttpClient:
    def __init__(self, timeout: int = 25):
        self.timeout = timeout

    def request_bytes(self, url: str, data: bytes | None = None,
                      headers: dict | None = None) -> bytes:
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, data=data, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; PersonalMarketCalendar/1.0)',
                    'Accept': 'text/html,application/pdf,application/json,*/*',
                    **(headers or {}),
                })
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    value = response.read(20_000_001)
                    if len(value) > 20_000_000:
                        raise FetchError('Source document exceeds 20 MB')
                    return value
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == 2:
                    raise FetchError(f'Source request failed ({type(exc).__name__})') from None
                time.sleep(attempt + 1)
        raise FetchError('Request failed')

    def get_bytes(self, url: str, headers: dict | None = None) -> bytes:
        return self.request_bytes(url, headers=headers)

    def get_text(self, url: str, headers: dict | None = None) -> str:
        return self.get_bytes(url, headers=headers).decode('utf-8-sig', errors='replace')

    def post_form(self, url: str, data: dict, headers: dict | None = None) -> str:
        body = urllib.parse.urlencode(data).encode('utf-8')
        merged = {'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})}
        return self.request_bytes(url, body, merged).decode('utf-8-sig', errors='replace')

    def get_soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.get_bytes(url), 'html.parser')

    def pdf_text(self, url: str) -> str:
        # Default extraction preserves words better on MSCI/OCC documents than
        # layout mode, which can insert spaces inside nearly every word.
        return '\n'.join(page.extract_text() or ''
                         for page in PdfReader(io.BytesIO(self.get_bytes(url))).pages)
