import asyncio
import Dhan

async def main():
    config_path = "config\config.yaml"
    instruments_path = "config\instruments.yaml"

    cfg = Dhan.load_config(Dhan._load_yaml(config_path))
    instruments = Dhan.Instruments.load(Dhan._load_yaml(instruments_path))

    logger = Dhan.setup_logging(
        cfg.logging.level,
        cfg.logging.json,
        cfg.logging.dir
    )

    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    engine = Dhan._build_engine(
        cfg,
        instruments,
        clock,
        logger,
        metrics,
        live=True,
        use_nse_chain=True
    )

    engine.nse_chain.start_result = None
    await engine.nse_chain.start()

    print("ENGINE_START=PASS")

    task = asyncio.create_task(engine.run())

    await asyncio.sleep(30)

    snap = metrics.snapshot()

    print("\n=== RUNTIME METRICS ===")
    print("cycles =", snap["counters"].get("cycles", 0))
    print("bars_5m =", snap["counters"].get("bars_5m", 0))
    print("signals =", snap["counters"].get("signals", 0))
    print("candidates =", snap["counters"].get("candidates", 0))
    print("skip_window =", snap["counters"].get("skip_window", 0))
    print("skip_warmup =", snap["counters"].get("skip_warmup", 0))
    print("skip_degraded =", snap["counters"].get("skip_degraded", 0))
    print("skip_stale =", snap["counters"].get("skip_stale", 0))
    print("chain_poll_errors =", snap["counters"].get("chain_poll_errors", 0))
    print("cycle_exceptions =", snap["counters"].get("cycle_exceptions", 0))
    print("cycle_failclosed =", snap["counters"].get("cycle_failclosed", 0))
    print("task_restarts =", snap["counters"].get("task_restarts", 0))

    hs = engine.health.status()

    print("\n=== FINAL HEALTH ===")
    print("feed_ok =", hs.feed_ok)
    print("chain_ok =", hs.chain_ok)
    print("tick_age =", hs.last_tick_age_s)
    print("chain_age =", hs.last_chain_age_s)
    print("health_degraded =", engine.health.degraded)

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    await engine.shutdown()

    print("\nRUNTIME_SMOKE=DONE")

asyncio.run(main())
