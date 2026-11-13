"""Bounded data routing only. Never scores an entry or creates a buy signal."""
from datetime import datetime
import math

from market_math import number,tick_price

DETAIL_TARGET = 8
DETAIL_LIMIT = 10


def within_analysis_hours(now, cutoff='15:15'):
    """Check the weekday and configured request cutoff in exchange-local time."""
    return now.weekday() < 5 and '10:00' <= now.strftime('%H:%M') < cutoff


def has_time_for_detail(completed, durations, remaining):
    if remaining <= 0:
        return False
    if not completed:
        return True
    expected = max(durations[-3:], default=0) if completed >= DETAIL_TARGET else 0
    return remaining >= max(8, expected)


def select_news_headlines(rows, candidates, now):
    """Keep a small, time-verified first-page sample for context only."""
    relevant, general, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get('hts_pbnt_titl_cntt')
        if not isinstance(title, str) or not title.strip():
            continue
        date, clock = str(row.get('data_dt', '')), str(row.get('data_tm', ''))
        if len(date) != 8 or len(clock) != 6 or not (date + clock).isdigit():
            continue
        try:
            published = datetime.strptime(date + clock, '%Y%m%d%H%M%S').replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if published.date() != now.date() or published > now:
            continue
        codes = {str(row.get(f'iscd{i}', '')).strip() for i in range(1, 6)}
        codes = {code for code in codes if len(code) == 6 and code.isdigit()}
        matching = sorted(codes.intersection(candidates))
        if codes and not matching:
            continue
        title = title.strip()[:180]
        if title in seen:
            continue
        seen.add(title)
        record = {'title':title, 'published_at':published.isoformat(), 'symbols':matching,
                  'provider':str(row.get('dorg', ''))[:50]}
        (relevant if matching else general).append(record)
    return (relevant + general)[:8]


def minimum_share_amount(price,commission_pct):
    """Feasibility only; does not choose an entry, weight, or price target."""
    return tick_price(number(price),up=True)*(1+commission_pct/100)


def analysis_route(universe,holdings,previous,cursor=0):
    """Full reserve queue, unlike a fixed number of attempted candidates."""
    available=list(dict.fromkeys(row['symbol'] for row in universe))
    primary=list(holdings)
    for row in previous.get('entry_reviews',[])[:2]:
        symbol=row.get('symbol')
        if row.get('stance') in ('watch','ready') and symbol in available and symbol not in primary:
            primary.append(symbol)
    pool=[s for s in available if s not in primary]
    offset=cursor%len(pool) if pool else 0
    return primary+pool[offset:]+pool[:offset],len(primary)


def analysis_batch(universe, holdings, previous, limit, cursor=0):
    """Holdings, bounded AI watches, then rotating ranking rows; AI decides trades."""
    available=list(dict.fromkeys(row['symbol'] for row in universe))
    maximum=max(len(holdings),min(DETAIL_LIMIT,limit))
    selected=list(holdings)
    for row in previous.get('entry_reviews',[])[:2]:
        symbol=row.get('symbol')
        if row.get('stance') in ('watch','ready') and symbol in available and symbol not in selected and len(selected)<maximum:
            selected.append(symbol)
    pool=[s for s in available if s not in selected]
    if pool:
        offset=cursor%len(pool)
        rotated=pool[offset:]+pool[:offset]
        count=max(0,maximum-len(selected))
        selected.extend(rotated[:count])
        cursor+=min(count,len(pool))
    return selected,cursor


def freshness_issue(candidate, now, wall_now):
    """Do not refresh timestamps to disguise time spent collecting other stocks."""
    stamp=candidate.get('received_at')
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=wall_now-stamp<=180:
        return '최종 요청 시점 현재가 자료가 180초 이내가 아님'
    try:
        bar=datetime.strptime(now.strftime('%Y%m%d')+candidate['indicators']['last_bar'],
                              '%Y%m%d%H%M%S').replace(tzinfo=now.tzinfo)
    except (KeyError,ValueError,TypeError):
        return '최종 요청 시점 완료 분봉 시각 확인 불가'
    if not 0<(now-bar).total_seconds()<=180:
        return '최종 요청 시점 완료 분봉이 오래되거나 미완료임'
    return ''
