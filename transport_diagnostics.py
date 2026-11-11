"""Bounded, allowlisted context for diagnosing broker gateway failures."""
from collections import deque
from datetime import timezone
from email.utils import parsedate_to_datetime
import re
import uuid


RUN_ID = uuid.uuid4().hex
CONTINUATION_VALUES = frozenset(('', 'D', 'E', 'F', 'M', 'N'))
TRACE_HEADERS = ('x-request-id', 'x-correlation-id', 'x-trace-id', 'x-amzn-requestid')
TRACE_ID = re.compile(r'(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})', re.I)
MESSAGE_HINTS = {
    'call_limit': ('초당', '호출 제한', '호출 한도', 'rate limit', 'too many requests'),
    'timeout': ('시간 초과', '응답시간 초과', 'timeout', 'timed out'),
    'account': ('계좌', 'account'),
    'authorization': ('권한', '인증', '토큰', 'authorization', 'token'),
    'routing': ('라우팅', 'routing'),
    'temporary': ('일시', '잠시', 'temporarily', 'try again'),
    'maintenance': ('점검', 'maintenance'),
    'server_error': ('서버 오류', '내부 오류', 'server error', 'internal error'),
}


def ms(seconds):
    return round(seconds * 1000, 3)


def http_date(value):
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def response_headers(headers, sensitive_values):
    allowed = {'date', 'retry-after', 'content-type', 'tr_cont', *TRACE_HEADERS}
    fields = {name.lower(): value.strip() for name, value in (headers or {}).items()
              if name.lower() in allowed and isinstance(value, str) and len(value) <= 256}
    result = {}
    server_date = http_date(fields.get('date'))
    if server_date:
        result['server_date_utc'] = server_date
    retry_after = fields.get('retry-after', '')
    if re.fullmatch(r'[0-9]{1,6}', retry_after):
        result['retry_after_seconds'] = int(retry_after)
    else:
        retry_date = http_date(retry_after)
        if retry_date:
            result['retry_after_utc'] = retry_date
    media_type = fields.get('content-type', '').split(';', 1)[0].strip().lower()
    if media_type in ('application/json', 'text/html', 'text/plain', 'application/problem+json'):
        result['content_type'] = media_type
    if fields.get('tr_cont') in CONTINUATION_VALUES:
        result['tr_cont'] = fields['tr_cont']
    secrets = [s.casefold() for s in sensitive_values if s]
    trace = {}
    for name in TRACE_HEADERS:
        value = fields.get(name, '')
        if TRACE_ID.fullmatch(value) and not any(secret in value.casefold() for secret in secrets):
            trace[name] = value
    if trace:
        result['trace_ids'] = trace
    return result


def response_body(body):
    if not isinstance(body, dict):
        return {'body_kind':'non_object_json'}
    raw = body.get('msg1')
    message = raw[:2048].casefold() if isinstance(raw, str) else ''
    result = {'body_kind':'json_object', 'has_msg1':bool(message),
              'message_hints':[key for key, phrases in MESSAGE_HINTS.items()
                               if any(phrase in message for phrase in phrases)]}
    if body.get('rt_cd') in ('0', '1'):
        result['rt_cd'] = body['rt_cd']
    return result


class AttemptHistory:
    """A small history owned by one app-key lane and accessed inside its slot."""

    def __init__(self):
        self.lane_id = uuid.uuid4().hex
        self.recent = deque(maxlen=256)

    def context(self, now, endpoint):
        local = {'prior_attempts_last_1s':0, 'prior_attempts_last_10s':0, 'prior_attempts_last_60s':0}
        for started, _, _ in reversed(self.recent):
            age = now - started
            if age > 60:
                break
            local['prior_attempts_last_60s'] += 1
            if age <= 10:
                local['prior_attempts_last_10s'] += 1
            if age <= 1:
                local['prior_attempts_last_1s'] += 1
        if self.recent:
            started, ended, previous = self.recent[-1]
            local['previous_attempt'] = previous
            local['since_previous_start_ms'] = ms(now - started)
            local['since_previous_end_ms'] = ms(now - ended)
        for _, ended, previous in reversed(self.recent):
            if previous['endpoint'] == endpoint:
                local['since_previous_same_endpoint_end_ms'] = ms(now - ended)
                local['previous_same_endpoint_request_id'] = previous['request_id']
                local['previous_same_endpoint_code'] = previous['code']
                break
        return local

    def add(self, started, ended, attempt):
        self.recent.append((started, ended, attempt))
