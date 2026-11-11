"""Monotonic canvas-only clock; widget actions have no mouse/timing events."""
import copy
import math
import time

from trace_schema import EVENT_CATEGORIES


class TraceRecorder:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.events = []
        self.origin = None
        self.offset = 0.0
        self.enabled = True
        self.motion = {}

    def reset_motion(self):
        self.motion.clear()

    def pause(self):
        # Preserve elapsed time up to this point when canceled; a successful
        # submission still uses the last canvas event, not this timestamp.
        if self.origin is not None:
            self.offset += (self.clock() - self.origin) * 1000
        self.origin = None
        self.enabled = False
        self.reset_motion()

    def resume(self):
        self.enabled = True
        if self.events:
            self.origin = self.clock()

    def restore(self, events):
        self.events = copy.deepcopy(events)
        self.offset = self.events[-1]["t"] if self.events else 0.0
        self.origin = None
        self.enabled = True
        self.reset_motion()

    def record(self, kind, pos=None, **fields):
        if not self.enabled:
            return None
        now = self.clock()
        if self.origin is None:
            self.origin = now
        relative = round(self.offset + (now - self.origin) * 1000, 1)
        category = EVENT_CATEGORIES[kind]
        velocity = acceleration = 0.0
        if kind in ("hover_move", "zoom_move", "drag_move", "edit_move") and pos is not None:
            previous = self.motion.get(category)
            if previous:
                dt = now - previous[0]
                if dt < 0.1:
                    return None
                velocity = math.hypot(pos.x() - previous[1], pos.y() - previous[2]) / dt
                if previous[3] is not None:
                    acceleration = (velocity - previous[3]) / dt
            self.motion[category] = (now, pos.x(), pos.y(), velocity if previous else None)
        event = dict(type=kind, t=relative, v=round(velocity, 2), a=round(acceleration, 2), category=category)
        if pos is not None:
            event.update(x=round(pos.x()), y=round(pos.y()))
        event.update(copy.deepcopy(fields))
        self.events.append(event)
        return event
