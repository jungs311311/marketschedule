from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import date

from .config import data_path, load_env
from .engine import refresh_all, run_forever, send_slot
from .storage import Store
from .telegram import Telegram


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description='텔레그램 증시 일정봇')
    root.add_argument('--env', default='.env', help='.env 파일 경로')
    commands = root.add_subparsers(dest='command', required=True)
    commands.add_parser('refresh', help='공식 일정을 지금 갱신')
    render = commands.add_parser('render', help='메시지 미리보기')
    render.add_argument('--date', required=True)
    render.add_argument('--slot', choices=('morning', 'evening'), required=True)
    send = commands.add_parser('send', help='텔레그램으로 한 번 발송')
    send.add_argument('--date', required=True)
    send.add_argument('--slot', choices=('morning', 'evening'), required=True)
    send.add_argument('--force', action='store_true', help='중복방지를 무시하고 재발송')
    commands.add_parser('chat-id', help='/start를 보낸 채팅의 CHAT_ID 확인')
    commands.add_parser('bot-info', help='토큰의 봇 username 확인')
    commands.add_parser('test-message', help='연결 확인 메시지 발송')
    commands.add_parser('status', help='캐시 상태와 오류 확인')
    commands.add_parser('run', help='오전 8시·오후 9시 상시 스케줄러')
    return root


def main() -> None:
    args = parser().parse_args()
    load_env(args.env)
    log_path = Path(os.getenv('MARKET_BOT_LOG', 'data/marketbot.log'))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'),
                        format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stderr),
                                  logging.FileHandler(log_path, encoding='utf-8')])
    if args.command == 'run':
        run_forever()
        return
    if args.command == 'chat-id':
        values = Telegram(os.getenv('MARKET_BOT_TOKEN', '')).chat_candidates()
        if not values:
            print('최근 채팅이 없습니다. 새 봇에게 /start를 보낸 뒤 다시 실행하세요.')
        for chat_id, label in values:
            print(f'{chat_id}\t{label}')
        return
    if args.command == 'bot-info':
        print('@' + Telegram(os.getenv('MARKET_BOT_TOKEN', '')).bot_username())
        return
    if args.command == 'test-message':
        chat_id = os.getenv('MARKET_BOT_CHAT_ID', '')
        if not chat_id or chat_id.startswith('replace_'):
            raise ValueError('MARKET_BOT_CHAT_ID가 아직 설정되지 않았습니다')
        Telegram(os.getenv('MARKET_BOT_TOKEN', '')).send(
            chat_id, '[연결 확인]\n증시 일정봇이 정상적으로 연결되었습니다.\n아직 자동 알림은 시작하지 않았습니다.')
        print('시험 메시지를 발송했습니다.')
        return
    store = Store(data_path())
    try:
        if args.command == 'refresh':
            results = refresh_all(store)
            for result in results:
                print(f'{result.provider}: events={len(result.events)}, sessions={len(result.sessions)}, '
                      f'ok={result.successful_scopes}, failed={result.failed_scopes}')
                for warning in result.warnings:
                    print('  WARNING:', warning)
        elif args.command in ('render', 'send'):
            day = date.fromisoformat(args.date)
            print(send_slot(store, day, args.slot, dry_run=args.command == 'render',
                            force=getattr(args, 'force', False)))
        elif args.command == 'status':
            values = store.all()
            if not values:
                print('캐시 없음: refresh를 실행하세요.')
            for result in values:
                print(f'{result.provider} fetched={result.fetched_at} events={len(result.events)} '
                      f'sessions={len(result.sessions)}')
                for warning in result.warnings:
                    print('  WARNING:', warning)
    finally:
        store.close()


if __name__ == '__main__':
    main()
