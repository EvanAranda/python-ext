import threading
from functools import wraps


def debounce(wait: float):
    """Debounce decorator.

    :param wait: Time in seconds to wait before calling the function.

    Returns:
        function: Debounced function.
    """

    def decorator(func):
        t: threading.Timer | None = None

        @wraps(func)
        def debounced(*args, **kwargs):
            nonlocal t

            try:
                if t is not None:
                    t.cancel()
            except:
                pass

            t = threading.Timer(wait, func, args, kwargs)
            t.start()

        return debounced

    return decorator
