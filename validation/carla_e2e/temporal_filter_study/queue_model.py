"""Exploratory FIFO model, not a measurement of production end-to-end latency.

10 Hz logical arrivals, one VLM worker, production's20 waiting slots, dedup at
worker service time. Service times are explicitly supplied, ideally from real
VLM probes. Result/alert queues, worker scheduling and detector drops are absent.
"""
from collections import deque
from perception.deduplicator import Deduplicator


def simulate(candidates,service_times,capacity=20,dedup=True):
    if not service_times or any(t<=0 for t in service_times):
        raise ValueError('positive measured service times required')
    waiting=deque();available=0.;calls=[];suppressed=0;dropped=0
    state=Deduplicator()
    def drain(until):
        nonlocal available,suppressed
        while waiting and max(available,waiting[0]['t'])<=until:
            event=waiting.popleft()
            started=max(available,event['t'])
            allowed,reason=True,'dedup_off'
            if dedup:
                allowed,reason=state.should_verify_target('camera',event['track'],event['color'],event['bbox'],started)
            if not allowed:
                suppressed+=1;available=started;continue
            duration=service_times[len(calls)%len(service_times)]
            available=started+duration
            calls.append(dict(event,started_s=started,finished_s=available,wait_s=started-event['t'],
                              end_to_end_proxy_s=available-event['t'],service_s=duration,reason=reason))
    for event in sorted(candidates,key=lambda e:e['t']):
        drain(event['t'])
        if len(waiting)>=capacity:
            dropped+=1;continue
        waiting.append(event)
        drain(event['t'])
    drain(float('inf'))
    return dict(calls=calls,suppressed=suppressed,dropped=dropped)
