import asyncio
import Dhan

async def main():
    config_path = "config\config.yaml"
    instruments_path = "config\instruments.yaml"

    cfg = Dhan.load_config(Dhan._load_yaml(config_path))
    instruments = Dhan.Instruments.load(
        Dhan._load_yaml(instruments_path)
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

    for i in range(6):
        await asyncio.sleep(10)

        hs = engine.health.status()
        snap = metrics.snapshot()

        print({
            "sample": i + 1,
            "chain_ok": hs.chain_ok,
            "feed_ok": hs.feed_ok,
            "chain_age": round(hs.last_chain_age_s, 2),
            "cycles": snap["counters"].get("cycles", 0),
            "chain_poll_errors": snap["counters"].get("chain_poll_errors", 0),
            "cycle_exceptions": snap["counters"].get("cycle_exceptions", 0),
            "cycle_failclosed": snap["counters"].get("cycle_failclosed", 0),
            "task_restarts": snap["counters"].get("task_restarts", 0),
            "skip_degraded": snap["counters"].get("skip_degraded", 0),
            "skip_stale": snap["counters"].get("skip_stale", 0),
        })

    snap = metrics.snapshot()
    hs = engine.health.status()

    print("\n=== NUCLEAR DATAFLOW RESULT ===")
    print("chain_ok =", hs.chain_ok)
    print("feed_ok =", hs.feed_ok)
    print("chain_age =", hs.last_chain_age_s)
    print("cycles =", snap["counters"].get("cycles", 0))
    print("chain_poll_errors =", snap["counters"].get("chain_poll_errors", 0))
    print("cycle_exceptions =", snap["counters"].get("cycle_exceptions", 0))
    print("cycle_failclosed =", snap["counters"].get("cycle_failclosed", 0))
    print("task_restarts =", snap["counters"].get("task_restarts", 0))

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    await engine.shutdown()

    print("\nNUCLEAR_DATAFLOW_SMOKE=DONE")

asyncio.run(main())
