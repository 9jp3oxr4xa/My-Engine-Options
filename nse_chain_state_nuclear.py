import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(
        Dhan._load_yaml("config\config.yaml")
    )
    instruments = Dhan.Instruments.load(
        Dhan._load_yaml("config\instruments.yaml")
    )

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

    engine.use_nse_chain = True
    engine.health.use_nse_chain = True

    await engine.nse_chain.start()

    print("ENGINE_START=PASS")

    task = asyncio.create_task(engine.run())

    await asyncio.sleep(35)

    print("\n=== ENGINE STATE ===")

    print("LAST_CHAIN_TYPE =", type(st.last_chain).__name__)
    print("LAST_CHAIN =", repr(st.last_chain))
    print("LAST_CHAIN_ATTRS =", [x for x in dir(st.last_chain) if not x.startswith("_")][:100])
    snap = metrics.snapshot()

    print("\n=== METRICS ===")
    for k in [
        "cycles",
        "chain_poll_errors",
        "cycle_exceptions",
        "cycle_failclosed",
        "task_restarts",
        "bars_5m",
        "candidates",
        "signals",
        "skip_window",
        "skip_warmup",
        "skip_degraded",
        "skip_stale"
    ]:
        print(k, "=", snap["counters"].get(k, 0))

    hs = engine.health.status()

    print("\n=== HEALTH ===")
    print("feed_ok =", hs.feed_ok)
    print("chain_ok =", hs.chain_ok)
    print("chain_age =", hs.last_chain_age_s)
    print("health_degraded =", engine.health.degraded)

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    await engine.shutdown()

    print("\nCHAIN_STATE_CONSUMPTION_SMOKE=DONE")

asyncio.run(main())
