from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import data_path
from .http import HttpClient
from .providers import markets, monetary, options, rebalances
from .render import render
from .storage import Store, merge_with_confirmed_cache
from .telegram import Telegram

KST = ZoneInfo('Asia/Seoul')
LOG = logging.getLogger('marketbot')


def refresh_all(store: Store, today: date | None = None, client: HttpClient | None = None) -> list:
    today = today or datetime.now(KST).date()
    client = client or HttpClient()
    start, end = today - timedelta(days=15), today + timedelta(days=400)
    market_result = markets.collect(client, start, end)
    market_result = merge_with_confirmed_cache(store.get('markets'), market_result)
    store.put(market_result)
    collected = [market_result]
    for provider, call in (
        ('monetary', lambda: monetary.collect(client, start, end)),
        ('options', lambda: options.collect(client, start, end, market_result.sessions)),
        ('rebalances', lambda: rebalances.collect(client, start, end, market_result.sessions)),
    ):
        try:
            result = call()
            result = merge_with_confirmed_cache(store.get(provider), result)
            store.put(result)
            collected.append(result)
        except Exception as exc:
            LOG.exception('%s provider failed', provider)
            old = store.get(provider)
            if old:
                old.warnings.append(f'현재 갱신 실패로 이전 확인값 사용: {type(exc).__name__}')
                collected.append(old)
    dispatch_corrections(store)
    return collected


def dispatch_corrections(store: Store) -> None:
    token, chat_id = os.getenv('MARKET_BOT_TOKEN', ''), os.getenv('MARKET_BOT_CHAT_ID', '')
    for change_id, old, new in store.pending_corrections():
        prior_key = f"{old.get('trade_date')}:{old.get('slot')}"
        if not store.was_sent(prior_key):
            store.mark_change_notified(change_id)
            continue
        if not token or not chat_id:
            LOG.warning('correction pending but Telegram settings are absent: %s', change_id)
            continue
        details = '\n'.join('• ' + line for line in new.get('details', [])[:5])
        message = (f"[일정 정정]\n{new.get('title', old.get('title', '시장 일정'))}\n"
                   f"기존 기준일: {old.get('trade_date')}\n변경 기준일: {new.get('trade_date')}\n{details}")[:4096]
        Telegram(token).send(chat_id, message)
        store.mark_change_notified(change_id)
        LOG.info('correction sent for %s', new.get('id'))


def cached_results(store: Store) -> list:
    return store.all()


def send_slot(store: Store, day: date, slot: str, dry_run: bool = False,
              force: bool = False) -> str:
    results = cached_results(store)
    if not results:
        results = refresh_all(store, day)
    message = render(results, day, slot)
    key = f'{day.isoformat()}:{slot}'
    if dry_run:
        return message
    if store.was_sent(key) and not force:
        LOG.info('already sent: %s', key)
        return message
    token, chat_id = os.getenv('MARKET_BOT_TOKEN', ''), os.getenv('MARKET_BOT_CHAT_ID', '')
    if not chat_id:
        raise ValueError('MARKET_BOT_CHAT_ID가 설정되지 않았습니다')
    Telegram(token).send(chat_id, message)
    store.mark_sent(key, message)
    LOG.info('sent: %s', key)
    return message


def _inside(now: datetime, hour: int, minute: int, window: int) -> bool:
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return scheduled <= now < scheduled + timedelta(minutes=window)


def run_forever() -> None:
    store = Store(data_path())
    completed: set[str] = set()
    if not store.all():
        LOG.info('cache empty; initial refresh')
        refresh_all(store)
    try:
        while True:
            now = datetime.now(KST)
            jobs = [
                ('refresh-am', 7, 30, 25, lambda: refresh_all(store, now.date())),
                ('send-am', 8, 0, 30, lambda: send_slot(store, now.date(), 'morning')),
                ('refresh-pm', 20, 30, 25, lambda: refresh_all(store, now.date())),
                ('send-pm', 21, 0, 30, lambda: send_slot(store, now.date(), 'evening')),
            ]
            for label, hour, minute, window, action in jobs:
                key = f'{now.date()}:{label}'
                if key not in completed and _inside(now, hour, minute, window):
                    try:
                        action()
                    except Exception:
                        LOG.exception('scheduled job failed: %s', label)
                    completed.add(key)
            completed = {k for k in completed if k.startswith(now.date().isoformat())}
            time.sleep(20)
    finally:
        store.close()
