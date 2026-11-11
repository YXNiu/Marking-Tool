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

    @property
    def running(self):
        return self.enabled and self.origin is not None

    def stop_clock(self, now=None):
        if self.origin is not None:
            self.offset += ((self.clock() if now is None else now) - self.origin) * 1000
        self.origin = None
        self.reset_motion()

    def pause(self):
        """Suspend the session (for a dialog, navigation or submission)."""
        self.stop_clock()
        self.enabled = False

    def resume(self, running=True):
        """Allow events again; only restart time if the pointer is in the canvas."""
        self.enabled = True
        if running and self.events and self.origin is None:
            self.origin = self.clock()
        elif not running:
            self.stop_clock()

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
        if kind == "canvas_enter" and self.origin is None:
            self.origin = now
            self.reset_motion()
        if self.origin is None and kind not in ("zoom_reset", "delete_bbox"):
            return None  # No pointer samples outside the canvas.
        elapsed = self.offset + ((now - self.origin) * 1000 if self.origin is not None else 0)
        relative = round(elapsed, 1)
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
        if kind == "canvas_leave":
            self.stop_clock(now)  # Freeze at the very same instant as the leave event.
        return event
