import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml("config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml("config\instruments.yaml"))
    log = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    m = Dhan.Metrics()
    c = Dhan.Clock()

    e = Dhan._build_engine(
        cfg, ins, c, log, m,
        live=True,
        use_nse_chain=True
    )

    e.use_nse_chain = True
    e.health.use_nse_chain = True

    await e.nse_chain.start()
    t = asyncio.create_task(e.run())

    await asyncio.sleep(330)

    s = m.snapshot()
    print("\n=== NUCLEAR BAR RESULT ===")
    print("cycles =", s["counters"].get("cycles", 0))
    print("bars_5m =", s["counters"].get("bars_5m", 0))
    print("chain_poll_errors =", s["counters"].get("chain_poll_errors", 0))
    print("cycle_exceptions =", s["counters"].get("cycle_exceptions", 0))
    print("cycle_failclosed =", s["counters"].get("cycle_failclosed", 0))
    print("task_restarts =", s["counters"].get("task_restarts", 0))
    print("candidates =", s["counters"].get("candidates", 0))
    print("signals =", s["counters"].get("signals", 0))

    for u in cfg.engine.underlyings:
        st = e.store.get(u)
        print(
            "STATE", u,
            "bars_1m=", len(st.bars_1m),
            "bars_5m=", len(st.bars_5m)
        )

    hs = e.health.status()
    print("chain_ok =", hs.chain_ok)
    print("feed_ok =", hs.feed_ok)
    print("health_degraded =", e.health.degraded)

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass

    await e.shutdown()
    print("NUCLEAR_BAR_TEST=DONE")

asyncio.run(main())
