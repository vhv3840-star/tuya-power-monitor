"""Pure measurement logic. Missing readings are never interpreted as zero watts."""
from dataclasses import dataclass


def in_window(now: str, start: str, end: str) -> bool:
    return start <= now < end if start < end else now >= start or now < end


@dataclass
class SessionTracker:
    start_w: float
    end_w: float
    hold_s: float
    max_gap_s: float = 90
    start_hold_s: float = 0
    active: bool = False
    started_at: float | None = None
    last_at: float | None = None
    last_w: float | None = None
    low_since: float | None = None
    energy_kwh: float = 0
    peak_w: float = 0
    observed_s: float = 0
    high_since: float | None = None
    candidate_energy: float = 0
    candidate_seconds: float = 0
    candidate_peak: float = 0

    @property
    def average_w(self):
        return self.energy_kwh * 3600000 / self.observed_s if self.observed_s else self.last_w or 0

    def feed(self, now: float, watts: float | None):
        if watts is None:
            self.last_at = self.last_w = self.low_since = None
            self.high_since = None
            return None
        if not self.active and watts >= self.start_w:
            if self.high_since is None or (self.last_at is not None and now-self.last_at>self.max_gap_s):
                self.high_since=now
                self.candidate_energy=self.candidate_seconds=0
                self.candidate_peak=watts
            elif self.last_at is not None and self.last_w is not None:
                dt=max(0,now-self.last_at)
                self.candidate_energy+=(watts+self.last_w)/2*dt/3600000
                self.candidate_seconds+=dt
                self.candidate_peak=max(self.candidate_peak,watts)
            self.last_at,self.last_w=now,watts
            if now-self.high_since<self.start_hold_s:
                return None
            self.active = True
            self.started_at = self.high_since
            self.last_at, self.last_w = now, watts
            self.energy_kwh,self.observed_s=self.candidate_energy,self.candidate_seconds
            self.peak_w = self.candidate_peak
            self.high_since=None
            self.low_since = None
            return 'started'
        if not self.active:
            self.high_since=None
            self.last_at=self.last_w=None
            return None
        dt = now - self.last_at if self.last_at is not None else 0
        if 0 < dt <= self.max_gap_s and self.last_w is not None:
            self.energy_kwh += (watts + self.last_w) / 2 * dt / 3600000
            self.observed_s += dt
        elif dt > self.max_gap_s:
            self.low_since = None
        self.peak_w = max(self.peak_w, watts)
        self.last_at, self.last_w = now, watts
        if watts <= self.end_w:
            if self.low_since is None:
                self.low_since = now
            if now - self.low_since >= self.hold_s:
                self.active = False
                return 'completed'
        else:
            self.low_since = None
        return None
