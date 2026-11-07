"""Validation-only conservative dedup alternatives; no ground-truth inputs."""
from perception.deduplicator import Deduplicator, _Target, _OPENCLAW_COOLDOWN


class ReappearanceDeduplicator(Deduplicator):
    """Keep continuous-track cooldown; request again after a candidate gap.

    A fresh track cannot inherit a nearby track's cooldown. The1s gap is fixed
    before replay and matches the existing target reappearance definition.
    This is an experimental policy, not a guarantee of unseen-scene recall.
    """
    def __init__(self, reset_on_gap=True):
        super().__init__()
        self.reset_on_gap=reset_on_gap

    def should_verify_target(self,camera_id,track_id,color,bbox,now):
        with self._lock:
            key=(camera_id,track_id)
            target=self._targets.get(key)
            if target is None:
                self._track_target[key]=key
                self._targets[key]=_Target(color,list(bbox),now,now)
                return True,'new_track'
            gap=now-target.last_seen
            changed=color!=target.color
            target.color,target.bbox,target.last_seen=color,list(bbox),now
            if changed:
                target.last_verify=now
                return True,'color_changed'
            if self.reset_on_gap and gap>1.+1e-6:
                target.last_verify=now
                return True,'reappeared'
            if now-target.last_verify>=_OPENCLAW_COOLDOWN:
                target.last_verify=now
                return True,'cooldown_expired'
            return False,'same_target_cooldown'
