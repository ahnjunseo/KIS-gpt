"""Offline projection of the application analysis payload."""
from collections import Counter
import copy

BAR_FIELDS = ('stck_bsop_date','stck_cntg_hour','stck_oprc','stck_hgpr','stck_lwpr','stck_prpr','cntg_vol')


def compact_context(context, *, subscription=False):
    """Keep every bar and every price/volume field used by this strategy."""
    if subscription:
        candidates = {}
        for symbol, source in context.get('candidates', {}).items():
            candidate = dict(source)
            if 'recent_bars' in candidate:
                candidate['recent_bars'] = [[row.get(key) for key in BAR_FIELDS] for row in candidate['recent_bars']]
            candidates[symbol] = candidate
        result = dict(context, candidates=candidates)
        if any('recent_bars' in c for c in candidates.values()):
            result['recent_bars_columns'] = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
        ranked = context.get('candidate_summary', [])
        if isinstance(ranked, list) and 'candidate_summary' in context:
            detailed_ranks = [row for row in ranked if row['symbol'] in candidates]
            result['candidate_summary'] = detailed_ranks
            result['undetailed_rank_count'] = len(ranked) - len(detailed_ranks)
        rejections = context.get('candidate_data_rejections', {})
        if rejections:
            # Keep individual reasons for positions or active watch ideas.
            previous = context.get('previous_analysis', {})
            relevant = set(context.get('holdings', {})) | {r['symbol'] for r in previous.get('entry_reviews', [])}
            result['candidate_data_rejections'] = {s: reason for s, reason in rejections.items() if s in relevant}
            result['candidate_rejection_counts'] = dict(Counter(rejections.values()))
        return result
    result=copy.deepcopy(context)
    for candidate in result.get('candidates',{}).values():
        if 'recent_bars' in candidate:
            candidate['recent_bars']=[{k:r[k] for k in BAR_FIELDS if k in r} for r in candidate['recent_bars']]
    return result
