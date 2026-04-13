import time
import functools
import threading
import os
import json
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, List
from src.core.config import Config


class Monitor:
    """Performance Monitoring Utility.
    Only active when Config.PROFILE is True.
    """

    _metrics: Dict[str, List[float]] = {}
    _lock = threading.Lock()
    _log_file: Optional[str] = None
    _start_time: float = 0.0

    @staticmethod
    def _initialize():
        if not Config.PROFILE or Monitor._log_file:
            return
        
        with Monitor._lock:
            if Monitor._log_file:
                return
            
            profile_dir = Config.get_profile_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            Monitor._log_file = os.path.join(profile_dir, f"perf_{timestamp}.jsonl")
            Monitor._start_time = time.time()
            
            # Initial header entry
            Monitor._write_entry({
                "type": "header",
                "timestamp": timestamp,
                "version": "1.0",
                "start_time": Monitor._start_time
            })

    @staticmethod
    def _write_entry(entry: dict):
        if not Monitor._log_file:
            return
        try:
            with open(Monitor._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[PERF] Error writing to log: {e}")

    @staticmethod
    def record(name: str, value: float):
        if not Config.PROFILE:
            return
        
        Monitor._initialize()
        
        with Monitor._lock:
            if name not in Monitor._metrics:
                Monitor._metrics[name] = []
            Monitor._metrics[name].append(value)
            
            # Write individual event to JSONL for real-time persistence
            Monitor._write_entry({
                "type": "event",
                "name": name,
                "value": value,
                "timestamp": time.time() - Monitor._start_time
            })

    @staticmethod
    def get_summary():
        with Monitor._lock:
            summary = {}
            for name, values in Monitor._metrics.items():
                if not values:
                    continue
                summary[name] = {
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values)
                }
            return summary

    @staticmethod
    def finalize():
        """Called at app exit to write final summary."""
        if not Monitor._log_file:
            return
            
        summary = Monitor.get_summary()
        Monitor._write_entry({
            "type": "summary",
            "metrics": summary,
            "end_time": time.time(),
            "total_duration": time.time() - Monitor._start_time
        })
        print(f"[PERF] Session monitoring finalized. Data saved to: {Monitor._log_file}")

    @staticmethod
    def time_func(name: Optional[str] = None):
        """Decorator to time a function."""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if not Config.PROFILE:
                    return func(*args, **kwargs)

                start_time = time.perf_counter()
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start_time
                metric_name = name or func.__name__
                
                # Immediate console feedback
                # print(f"[PERF] {metric_name}: {elapsed:.4f}s")
                Monitor.record(metric_name, elapsed)
                return result

            return wrapper

        return decorator

    @staticmethod
    @contextmanager
    def time_block(name: str):
        """Context manager to time a block of code."""
        if not Config.PROFILE:
            yield
            return

        start_time = time.perf_counter()
        yield
        elapsed = time.perf_counter() - start_time
        # print(f"[PERF] {name}: {elapsed:.4f}s")
        Monitor.record(name, elapsed)
