import asyncio
import time
from collections import Counter


def log_checkpoint(message):
    print(message, flush=True)


def increment_counter(counters, name):
    if counters is None or not name:
        return
    counters[name] += 1


async def run_sync_phase(
    phase,
    func,
    timeout,
    fallback=None,
    counters=None,
    timeout_counter=None,
):
    log_checkpoint(f"[phase] {phase} START")
    start = time.perf_counter()

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(func),
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        log_checkpoint(f"[phase] {phase} DONE duration={elapsed:.2f}s")
        return result
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        increment_counter(counters, timeout_counter)
        log_checkpoint(
            f"[phase] {phase} TIMEOUT duration={elapsed:.2f}s timeout={timeout}s"
        )
        return fallback() if callable(fallback) else fallback
    except Exception as exc:
        elapsed = time.perf_counter() - start
        log_checkpoint(
            f"[phase] {phase} ERROR duration={elapsed:.2f}s "
            f"error={exc.__class__.__name__}: {exc}"
        )
        return fallback() if callable(fallback) else fallback


async def run_async_phase(
    phase,
    awaitable_factory,
    timeout,
    fallback=None,
    counters=None,
    timeout_counter=None,
):
    log_checkpoint(f"[phase] {phase} START")
    start = time.perf_counter()

    try:
        result = await asyncio.wait_for(
            awaitable_factory(),
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        log_checkpoint(f"[phase] {phase} DONE duration={elapsed:.2f}s")
        return result
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        increment_counter(counters, timeout_counter)
        log_checkpoint(
            f"[phase] {phase} TIMEOUT duration={elapsed:.2f}s timeout={timeout}s"
        )
        return fallback() if callable(fallback) else fallback
    except Exception as exc:
        elapsed = time.perf_counter() - start
        log_checkpoint(
            f"[phase] {phase} ERROR duration={elapsed:.2f}s "
            f"error={exc.__class__.__name__}: {exc}"
        )
        return fallback() if callable(fallback) else fallback


def empty_network_counter():
    return Counter(
        {
            "rss_timeout": 0,
            "article_timeout": 0,
            "telegram_timeout": 0,
            "market_data_timeout": 0,
            "coinmetrics_timeout": 0,
            "openai_timeout": 0,
            "cycle_watchdog_timeout": 0,
        }
    )


def format_network_counters(counters):
    if counters is None:
        counters = empty_network_counter()

    return "\n".join(
        f"{name}: {counters.get(name, 0)}"
        for name in empty_network_counter()
    )
