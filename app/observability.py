import functools
import logging

log = logging.getLogger("prodRag.trace")


def trace(name: str):
    """Decorator to trace/log execution of pipeline stages."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log.debug("Entering stage: %s", name)
            try:
                result = fn(*args, **kwargs)
                log.debug("Exited stage: %s", name)
                return result
            except Exception:
                log.exception("Error in stage: %s", name)
                raise
        return wrapper
    return decorator
