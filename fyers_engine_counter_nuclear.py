import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
    logger = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    e = Dhan._build_engine(
        cfg, ins, clock, logger, metrics,
        live=True,
        use_nse_chain=True
    )

    e.use_nse_chain = True
    e.health.use_nse_chain = True

    print("ENGINE_BUILD=PASS", flush=True)

    await e.nse_chain.start()
    print("NSE_CHAIN_START=PASS", flush=True)

    task = asyncio.create_task(e.run())

    await asyncio.sleep(45)

    snap = metrics.snapshot()

    print("\n=== NUCLEAR COUNTERS ===", flush=True)
    for k in sorted(snap["counters"]):
        print(f"{k} = {snap['counters'][k]}", flush=True)

    hs = e.health.status()

    print("\n=== FINAL HEALTH ===", flush=True)
    print("feed_ok =", hs.feed_ok, flush=True)
    print("chain_ok =", hs.chain_ok, flush=True)
    print("tick_age =", hs.last_tick_age_s, flush=True)
    print("chain_age =", hs.last_chain_age_s, flush=True)
    print("health_degraded =", e.health.degraded, flush=True)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await e.shutdown()

    print("\nCOUNTER_SMOKE=DONE", flush=True)

asyncio.run(main())
