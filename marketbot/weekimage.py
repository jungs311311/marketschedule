"""이번 주 시장 개장·휴장 표를 PNG 이미지로 그린다."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WEEKDAY = ('월', '화', '수', '목', '금', '토', '일')
MARKETS = (('KR', '한국'), ('JP', '일본'), ('US', '미국'))
LABEL = {'open': '개장', 'closed': '휴장', 'early_close': '조기폐장',
         'changed': '시간변경', 'unknown': '확인불가'}
COLOR = {'open': (34, 139, 94), 'closed': (200, 60, 60), 'early_close': (200, 140, 40),
         'changed': (200, 140, 40), 'unknown': (130, 130, 130)}
BG, LINE, TEXT, SUB, TODAY_BG = (255, 255, 255), (226, 229, 234), (26, 30, 36), (120, 128, 138), (240, 246, 255)

# 굵은 글씨 후보와 보통 글씨 후보. 앞에서부터 있는 것을 쓴다.
BOLD = ('/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')
PLAIN = ('/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf',
         '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
         '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')


def _font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError('한글 글꼴을 찾을 수 없습니다 (fonts-nanum 설치 필요)')


def draw_week(sessions: dict, day: date, path: str | Path) -> Path:
    monday = day - timedelta(days=day.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    notes: list[str] = []

    pad, head, row_h, name_w, col_w = 36, 96, 74, 120, 128
    width = pad * 2 + name_w + col_w * 7
    image = Image.new('RGB', (width, head + row_h * (len(MARKETS) + 1) + 220), BG)
    draw = ImageDraw.Draw(image)

    f_title, f_sub = _font(BOLD, 36), _font(PLAIN, 22)
    f_head, f_cell, f_note = _font(BOLD, 26), _font(BOLD, 26), _font(PLAIN, 22)

    draw.text((pad, 28), '이번 주 증시 일정', font=f_title, fill=TEXT)
    draw.text((pad, 72), f'{monday:%Y.%m.%d} ~ {days[-1]:%m.%d}', font=f_sub, fill=SUB)

    top = head + 26
    for index, each in enumerate(days):
        x = pad + name_w + col_w * index
        if each == day:
            draw.rounded_rectangle(
                [x + 4, top - 6, x + col_w - 4, top + row_h * (len(MARKETS) + 1) - 10],
                12, fill=TODAY_BG)
        draw.text((x + col_w // 2, top + 8), WEEKDAY[each.weekday()], font=f_head,
                  fill=(200, 60, 60) if each.weekday() >= 5 else TEXT, anchor='mm')
        draw.text((x + col_w // 2, top + 36), f'{each:%m/%d}', font=f_sub, fill=SUB, anchor='mm')

    for order, (market, label) in enumerate(MARKETS):
        y = top + row_h * (order + 1)
        draw.line([pad, y - 4, width - pad, y - 4], fill=LINE, width=2)
        draw.text((pad + 8, y + 30), label, font=f_head, fill=TEXT, anchor='lm')
        for index, each in enumerate(days):
            session = sessions.get((market, each.isoformat()))
            status = session.status if session else 'unknown'
            x = pad + name_w + col_w * index
            draw.text((x + col_w // 2, y + 30), LABEL.get(status, status),
                      font=f_cell, fill=COLOR.get(status, SUB), anchor='mm')
            if session and status != 'open' and each.weekday() < 5:
                notes.append(f'{each:%m/%d}({WEEKDAY[each.weekday()]}) {label} '
                             f'{LABEL.get(status, status)} · {session.reason}')

    y = top + row_h * (len(MARKETS) + 1)
    draw.line([pad, y - 4, width - pad, y - 4], fill=LINE, width=2)
    y += 16
    for note in dict.fromkeys(notes):
        draw.text((pad + 8, y), '· ' + note, font=f_note, fill=SUB)
        y += 32

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.crop((0, 0, width, y + 20)).save(out)
    return out
