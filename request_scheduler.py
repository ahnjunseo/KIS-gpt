"""One paced I/O lane per key, urgent priority and bounded ordinary fairness."""
from contextlib import contextmanager
import threading
import time


class SlotUnavailable(Exception):
    pass


class FairGate:
    RECOVERY_SECONDS=30
    def __init__(self):
        self.lock=threading.RLock()
        self.condition=threading.Condition(self.lock)
        self.interval=1.25;self.base_interval=1.25
        self.next_at=0.;self.cool_until=0.;self.strikes=0
        self.queue=[];self.sequence=0;self.active=False
        self.foreground_streak=0
        self.last_limit=0.;self.last_recovery=0.;self.successes=0

    def _choose(self):
        urgent=[t for t in self.queue if t['priority']==0]
        if urgent:return min(urgent,key=lambda t:t['id'])
        analysis=[t for t in self.queue if t['priority']==2]
        if analysis and self.foreground_streak>=3:return min(analysis,key=lambda t:t['id'])
        return min(self.queue,key=lambda t:(t['priority'],t['id']))

    @contextmanager
    def slot(self,*,priority=3,deadline=None,cancelled=None,timing=None):
        timing=timing if timing is not None else {}
        timing.update(queue_wait_ms=0.,pace_wait_ms=0.)
        with self.condition:
            self.sequence+=1;ticket={'id':self.sequence,'priority':priority}
            self.queue.append(ticket)
        owns=False
        try:
            while True:
                with self.condition:
                    if cancelled and cancelled():raise SlotUnavailable('조회 중지')
                    remaining=deadline-time.monotonic() if deadline is not None else float('inf')
                    if remaining<=0:raise SlotUnavailable('자료 수집 시간 예산 소진: 통신 차례 대기')
                    if not self.active and self._choose() is ticket:
                        delay=max(self.next_at,self.cool_until)-time.monotonic()
                        if delay<=0:
                            self.queue.remove(ticket);self.active=True;owns=True
                            self.next_at=time.monotonic()+self.interval
                            self.foreground_streak=0 if priority==2 else self.foreground_streak+1
                            timing.update(effective_interval=self.interval,queue_depth=len(self.queue))
                            break
                    else:
                        start=time.monotonic()
                        self.condition.wait(timeout=min(.1,remaining))
                        timing['queue_wait_ms']+=(time.monotonic()-start)*1000
                        continue
                # The condition and lane are both free during pacing. A newly
                # arrived urgent request can take the next eligible slot.
                start=time.monotonic()
                time.sleep(min(delay,remaining,.1) if cancelled else min(delay,remaining))
                timing['pace_wait_ms']+=(time.monotonic()-start)*1000
            yield timing
        finally:
            with self.condition:
                if owns:self.active=False
                elif ticket in self.queue:self.queue.remove(ticket)
                self.condition.notify_all()

    def rate_limited(self):
        with self.condition:
            self.strikes+=1;self.successes=0;self.last_limit=time.monotonic()
            self.interval=min(5.,self.interval*2)
            self.cool_until=max(self.cool_until,time.monotonic()+min(8,2**min(self.strikes,3)))
            self.condition.notify_all()

    def transient_failure(self,attempt):
        # Unknown transient gateway errors get a bounded shared cooldown, not a
        # permanent reduction of all later account/market/order throughput.
        with self.condition:
            self.cool_until=max(self.cool_until,time.monotonic()+min(4,2**(attempt+1)))
            self.condition.notify_all()

    def succeeded(self):
        with self.condition:
            self.successes+=1
            if (self.interval>self.base_interval and self.successes>=8 and
                time.monotonic()-max(self.last_limit,self.last_recovery)>=self.RECOVERY_SECONDS):
                self.interval=max(self.base_interval,self.interval/2)
                self.strikes=max(0,self.strikes-1);self.successes=0
                self.last_recovery=time.monotonic()
                self.condition.notify_all()
