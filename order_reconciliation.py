"""Local order ledger and reconciliation of already-observed order records."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import sqlite3

from market_math import TradingError

KST = timezone(timedelta(hours=9))


class OrderStatePending(TradingError):
    """Broker account and order views must be refreshed before another action."""


def order_id(value):
    return str(value or '').strip().lstrip('0')


def order_completion(row, qty):
    """Direct terminal evidence on the original broker order."""
    remaining = row.get('rmn_qty')
    if remaining not in ('', None) and int(remaining) > 0:
        return ''
    filled = int(row.get('tot_ccld_qty') or 0)
    if qty > 0 and filled >= qty:
        return '전량 체결'
    if row.get('cncl_yn') == 'Y':
        return '취소 확인'
    cancelled = int(row.get('cncl_cfrm_qty') or row.get('cnc_cfrm_qty') or 0)
    rejected = int(row.get('rjct_qty') or 0)
    if remaining not in ('', None) and int(remaining) == 0 and qty > 0 and filled + cancelled + rejected >= qty:
        return '체결·취소·거절 수량 대조'
    return ''


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, scope TEXT, day TEXT, symbol TEXT, side TEXT, qty INTEGER, price INTEGER, state TEXT, broker_id TEXT, kind TEXT)')
            if 'receipt_id' not in {r[1] for r in db.execute('PRAGMA table_info(intents)')}:
                db.execute("ALTER TABLE intents ADD COLUMN receipt_id TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, uid, scope, symbol, side, qty, price, kind='order', broker_id=''):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM intents WHERE scope=? AND state IN ('SENDING','UNKNOWN')", (scope,)).fetchone():
                raise OrderStatePending('결과가 확인되지 않은 요청이 있습니다. 증권사 주문 내역과 대조하세요.')
            if kind == 'order' and db.execute("SELECT 1 FROM intents WHERE scope=? AND symbol=? AND state='ACCEPTED'", (scope, symbol)).fetchone():
                raise OrderStatePending('이 종목의 이전 주문이 아직 완료되지 않았습니다.')
            day = datetime.now(KST).strftime('%Y%m%d')
            if kind == 'cancel' and self._cancel_requested(db, scope, day, broker_id):
                raise OrderStatePending('이 주문은 이미 취소 접수되어 증권사 확인을 기다리고 있습니다.')
            try:
                db.execute('INSERT INTO intents (id,scope,day,symbol,side,qty,price,state,broker_id,kind) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (uid, scope, day, symbol, side, qty, price, 'SENDING', broker_id, kind))
            except sqlite3.IntegrityError:
                raise TradingError('이미 처리한 신호입니다. 중복 요청을 차단했습니다.') from None

    def state(self, uid, state, broker_id='', *, receipt_id=None):
        with self.db() as db:
            db.execute('UPDATE intents SET state=?, broker_id=?, receipt_id=COALESCE(?,receipt_id) WHERE id=?',
                       (state, broker_id, receipt_id, uid))

    @staticmethod
    def _cancel_requested(db, scope, day, broker_id):
        return db.execute("SELECT 1 FROM intents WHERE scope=? AND day=? AND kind='cancel' AND state='CANCEL_REQUESTED' AND ltrim(broker_id,'0')=?",
                          (scope, day, order_id(broker_id))).fetchone() is not None

    def cancel_requested(self, scope, broker_id):
        with self.db() as db:
            return self._cancel_requested(db, scope, datetime.now(KST).strftime('%Y%m%d'), broker_id)

    def unresolved(self, scope):
        with self.db() as db:
            return db.execute("SELECT id, day, symbol, side, qty, price, state, broker_id FROM intents WHERE scope=? AND state IN ('SENDING','UNKNOWN','ACCEPTED')", (scope,)).fetchall()

    def past_order_days(self, scope, day):
        with self.db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT day FROM intents WHERE scope=? AND day<? AND state='ACCEPTED' AND kind='order' ORDER BY day", (scope, day))]

    def reconcile(self, scope, orders, pending=None, *, day=None):
        day = day or datetime.now(KST).strftime('%Y%m%d')
        rows = {order_id(r.get('odno')): r for r in orders if order_id(r.get('odno')) and r.get('ord_dt', day) == day}
        open_ids = {order_id(r.get('odno')) for r in (pending or [])}
        linked = {}
        for r in rows.values():
            parent = order_id(r.get('orgn_odno'))
            if parent:
                linked.setdefault(parent, []).append(r)
        settled = {}
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            intents = db.execute("SELECT id,symbol,side,qty,state,broker_id,kind,receipt_id FROM intents WHERE scope=? AND day=? AND state IN ('ACCEPTED','CANCEL_REQUESTED','DONE')", (scope, day)).fetchall()
            cancels = {}
            for uid, symbol, side, qty, state, bid, kind, receipt in intents:
                if kind == 'cancel' and state in ('CANCEL_REQUESTED','DONE'):
                    cancels.setdefault(order_id(bid), []).append((uid, symbol, receipt))
            for uid, symbol, side, qty, state, bid, kind, _ in intents:
                oid = order_id(bid)
                row = rows.get(oid)
                if kind != 'order' or not oid or not row or oid in open_ids:
                    continue
                direction = '02' if side == 'buy' else '01'
                if row.get('pdno', symbol) != symbol or row.get('sll_buy_dvsn_cd', direction) != direction:
                    continue
                reason = '장부 완료 확인' if state == 'DONE' else order_completion(row, qty)
                requests = cancels.get(oid, [])
                if not reason and pending is not None and requests:
                    reason = self._linked_cancel_completion(row, qty, linked.get(oid, []), requests, open_ids)
                if reason:
                    settled[oid] = reason
                    db.execute("UPDATE intents SET state='DONE' WHERE id=? AND state='ACCEPTED'", (uid,))
                    db.executemany("UPDATE intents SET state='DONE' WHERE id=? AND state='CANCEL_REQUESTED'",
                                   [(cid,) for cid, csymbol, _ in requests if csymbol == symbol])
        return settled

    @staticmethod
    def _linked_cancel_completion(row, qty, children, requests, open_ids):
        # KIS can return blank cancellation flags and zero confirmed cancel qty
        # even when the accepted cancel child closed the original. Require all
        # corroborating fields, including absence from the separate pending view.
        if str(row.get('rmn_qty')) != '0' or len(children) != 1 or len(requests) != 1:
            return ''
        child = children[0]
        _, symbol, receipt = requests[0]
        if (row.get('pdno') != symbol or child.get('pdno') != symbol or
                child.get('sll_buy_dvsn_cd') != row.get('sll_buy_dvsn_cd') or
                order_id(child.get('odno')) in open_ids or
                (receipt and order_id(child.get('odno')) != order_id(receipt)) or
                str(child.get('rmn_qty')) != '0' or str(child.get('rjct_qty')) != '0' or
                str(child.get('tot_ccld_qty')) != '0' or str(child.get('ord_unpr')) != '0'):
            return ''
        filled = int(row.get('tot_ccld_qty') or 0)
        if int(child.get('ord_qty') or 0) < qty - filled:
            return ''
        return '원주문·취소 접수·취소 내역·미체결 대조'
