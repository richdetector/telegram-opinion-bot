import asyncio
from datetime import datetime, timedelta

from config import CYCLE_TIMEOUT_SECONDS
from main import process_news
from runtime_guards import empty_network_counter, log_checkpoint


CHECK_EVERY = 300  # 5 minutos


async def run_one_cycle(process_func=process_news, cycle_timeout=CYCLE_TIMEOUT_SECONDS):
    cycle_id = datetime.now().strftime("%Y%m%d%H%M%S")
    start = datetime.now()

    log_checkpoint(f"CYCLE START id={cycle_id} timestamp={start.isoformat(timespec='seconds')}")
    print(f"[{start.strftime('%H:%M:%S')}] 🔎 Buscando noticias...", flush=True)

    status = "healthy"
    network_counters = empty_network_counter()

    try:
        await asyncio.wait_for(
            process_func(),
            timeout=cycle_timeout,
        )

    except asyncio.TimeoutError:
        status = "watchdog_timeout"
        network_counters["cycle_watchdog_timeout"] += 1
        log_checkpoint(
            f"⚠️ CYCLE WATCHDOG TIMEOUT id={cycle_id} timeout={cycle_timeout}s"
        )

    except Exception as e:
        status = "error"
        print(f"\n❌ ERROR: {type(e).__name__}: {e}\n", flush=True)

    end = datetime.now()
    elapsed = (end - start).total_seconds()

    print(
        f"[{end.strftime('%H:%M:%S')}] ✅ Revisión terminada "
        f"({elapsed:.1f}s) status={status}",
        flush=True,
    )

    return {
        "cycle_id": cycle_id,
        "status": status,
        "elapsed": elapsed,
        "network_counters": network_counters,
    }


async def runner(process_func=process_news, check_every=CHECK_EVERY, max_cycles=None):

    print("\n🚀 Radar Crítico iniciado.\n", flush=True)

    cycles = 0

    while True:

        result = await run_one_cycle(
            process_func=process_func,
            cycle_timeout=CYCLE_TIMEOUT_SECONDS,
        )

        next_run = datetime.now() + timedelta(seconds=check_every)
        log_checkpoint(
            "HEARTBEAT "
            f"timestamp={datetime.now().isoformat(timespec='seconds')} "
            f"status={result['status']} "
            f"next_run={next_run.isoformat(timespec='seconds')}"
        )

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return

        print(f"⏳ Esperando {check_every} segundos...\n", flush=True)

        await asyncio.sleep(check_every)


if __name__ == "__main__":

    asyncio.run(runner())
