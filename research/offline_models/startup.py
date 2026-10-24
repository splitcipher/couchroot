"""Source/owner generation contract; intentionally no firmware adapter."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Evidence:
    boot: str
    app: str
    source: str | None
    owner: str | None
    generation: int | None
    powered: bool = True

    def known(self):
        return (bool(self.boot) and self.app in ('viewer','home')
                and self.source in ('tv','hdmi1','hdmi2')
                and self.owner == 'default-startup' and type(self.generation) is int
                and self.generation >= 0 and self.powered)

class DelayedLaunch:
    def __init__(self, baseline, claims):
        self.baseline=baseline;self.claims=claims;self.cancelled=False;self.submitted=False
        self.token=0;self.outcome='waiting'

    def cancel(self):
        self.cancelled=True;self.token+=1;self.outcome='cancelled';return None

    def tick(self, now, first, before_submit):
        if self.cancelled or self.submitted:return None
        if (now > 110 or not self.baseline.known() or not first.known()
                or first != self.baseline or first.boot in self.claims):return self.cancel()
        if now < 20:return None
        # A real firmware adapter must re-observe immediately before request.
        final=before_submit()
        if final != first or not final.known():return self.cancel()
        self.claims.add(first.boot);self.submitted=True;self.token+=1
        self.outcome='requested';return self.token

    def complete(self, token, success, observed):
        if self.cancelled or not self.submitted or token!=self.token:return
        if observed!=self.baseline:self.cancel();return
        self.outcome='request-accepted' if success else 'request-failed'
