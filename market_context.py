"""Observed multi-horizon price context for AI; contains no entry signals."""
from datetime import timedelta
from market_math import number

def completed_rows(rows,day,cutoff):
    return sorted({r['stck_cntg_hour']:r for r in rows if r.get('stck_bsop_date')==day and
                   '090000'<=r.get('stck_cntg_hour','')<min(cutoff,'153000')}.values(),key=lambda r:r['stck_cntg_hour'])

def earlier_cursor(rows,day):
    if not rows or rows[0]['stck_cntg_hour']<='090000': return None
    from datetime import datetime
    oldest=datetime.strptime(day+rows[0]['stck_cntg_hour'],'%Y%m%d%H%M%S')
    return (oldest-timedelta(minutes=1)).strftime('%H%M%S')

def aggregate(rows,minutes,cutoff):
    """Closed clock intervals; sparse intervals disclose actual row counts."""
    cutoff_min=int(cutoff[:2])*60+int(cutoff[2:4])
    groups={}
    for r in rows:
        t=r['stck_cntg_hour']; minute=int(t[:2])*60+int(t[2:4])
        start=minute//minutes*minutes
        if start+minutes>cutoff_min: continue
        groups.setdefault(start,[]).append(r)
    result=[]
    for start,items in sorted(groups.items()):
        result.append({'start':f'{start//60:02d}{start%60:02d}00','interval_minutes':minutes,
            'open':number(items[0]['stck_oprc']),'high':max(number(r['stck_hgpr']) for r in items),
            'low':min(number(r['stck_lwpr']) for r in items),'close':number(items[-1]['stck_prpr']),
            'volume':sum(number(r['cntg_vol']) for r in items),'observed_minutes':len(items)})
    return result

def intraday_context(rows,quote,cutoff):
    observed=completed_rows(rows,rows[-1]['stck_bsop_date'],cutoff) if rows else []
    prices={k:number(quote[k]) for k in ('stck_oprc','stck_hgpr','stck_lwpr','stck_sdpr') if quote.get(k) not in (None,'')}
    return {'scope':'observed_completed_intraday_bars_and_quote_session_values_not_predictions',
        'first_observed':observed[0]['stck_cntg_hour'] if observed else None,
        'last_observed':observed[-1]['stck_cntg_hour'] if observed else None,
        'observed_minutes':len(observed),'starts_at_open':bool(observed and observed[0]['stck_cntg_hour']=='090000'),
        'coverage_note':'Missing minutes are not filled; starts_at_open does not certify gap-free coverage. Quote session values have their own collection time.',
        'quote_session_prices':prices,
        'bars_15m':aggregate(observed,15,cutoff), 'recent_bars_5m':aggregate(observed,5,cutoff)[-12:]}


def path_evidence(rows,day,cutoff):
    """Three adjacent clock windows; descriptive observations, never signals."""
    clean=completed_rows(rows,day,cutoff)
    end=int(cutoff[:2])*60+int(cutoff[2:4])
    windows=[]
    for start in (end-30,end-20,end-10):
        sample=[r for r in clean if start<=int(r['stck_cntg_hour'][:2])*60+int(r['stck_cntg_hour'][2:4])<start+10]
        row={'start':f'{start//60:02d}{start%60:02d}00','expected_minutes':10,'observed_minutes':len(sample)}
        if sample:
            op=number(sample[0]['stck_oprc']);close=number(sample[-1]['stck_prpr'])
            high=max(number(r['stck_hgpr']) for r in sample);low=min(number(r['stck_lwpr']) for r in sample)
            row.update(open=op,high=high,low=low,close=close,
                change_pct=(close/op-1)*100 if op>0 else None,
                close_location_in_range=(close-low)/(high-low) if high>low else None,
                volume=sum(number(r['cntg_vol']) for r in sample))
        windows.append(row)
    return {'role':'observations_only_not_entry_signal','windows_10m':windows,
        'note':'Adjacent windows are not independent confirmations. Missing minutes stay missing; volume is total traded volume, not buy pressure. Earlier highs are observed prices, not certified resistance or profit targets.'}


def observed_review_progress(rows,day,cutoff,previous_fact,current_price,current_received_at):
    """Price path since the prior quote, not P&L or proof of a filled trade."""
    from datetime import datetime
    from math import isfinite
    from broker import KST
    anchor=previous_fact.get('received_at');price=previous_fact.get('price')
    if (any(type(v) not in (int,float) or not isfinite(v) for v in (anchor,price,current_received_at))
        or price<=0 or anchor>current_received_at):
        return {'status':'unavailable','reason':'No comparable timestamped prior quote'}
    try:
        prior=datetime.fromtimestamp(anchor,KST);current=datetime.fromtimestamp(current_received_at,KST)
    except (ValueError,OverflowError,OSError):
        return {'status':'unavailable','reason':'Invalid quote timestamps'}
    if prior.strftime('%Y%m%d')!=day or current.strftime('%Y%m%d')!=day:
        return {'status':'unavailable','reason':'Quote dates differ from the current trading day'}
    # Exclude the minute containing a quote unless the quote is exactly at its
    # start. Otherwise a bar's earlier high/low could predate the observation.
    start=prior.hour*60+prior.minute+(bool(prior.second or prior.microsecond))
    end=min(int(cutoff[:2])*60+int(cutoff[2:4]),current.hour*60+current.minute)
    sample=[r for r in completed_rows(rows,day,cutoff)
            if start<=int(r['stck_cntg_hour'][:2])*60+int(r['stck_cntg_hour'][2:4])<end]
    return {'status':'observed_quote_comparison_not_trade_PnL','previous_price':price,
        'previous_quote_at':prior.isoformat(),'current_quote_at':current.isoformat(),
        'quote_change_pct':(current_price/price-1)*100 if current_price>0 else None,
        'expected_closed_minutes':max(0,end-start),'observed_closed_minutes':len(sample),
        'observed_high_change_pct':(max(number(r['stck_hgpr']) for r in sample)/price-1)*100 if sample else None,
        'observed_low_change_pct':(min(number(r['stck_lwpr']) for r in sample)/price-1)*100 if sample else None,
        'note':'Excludes both boundary partial minutes; gaps are not filled. Prior AI proposal and reference price are not execution facts.'}
