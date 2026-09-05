import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
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

    task = asyncio.create_task(e.run())

    await asyncio.sleep(55)

    s = m.snapshot()["counters"]

    print("\n=== REAL ENGINE NUCLEAR RESULT ===")
    for k in [
        "ticks_ingested",
        "bars_5m",
        "cycles",
        "skip_window",
        "skip_warmup",
        "skip_degraded",
        "skip_stale",
        "candidates",
        "signals",
        "rejections",
        "chain_poll_errors",
        "cycle_exceptions",
        "cycle_failclosed",
        "task_restarts",
        "fyers_reconnects",
        "fyers_parse_errors",
        "ws_resubscribes",
    ]:
        print(f"{k} =", s.get(k, 0))

    u = cfg.engine.underlyings[0]
    st = e.store.get(u)

    print("\n=== LIVE STATE ===")
    print("bars_1m =", len(st.bars_1m))
    print("bars_5m =", len(st.bars_5m))
    print("regime =", st.regime.state)
    print("bias =", st.structure.bias)
    print("swings =", len(st.structure.swings))
    print("events =", len(st.structure.events))
    print("rvol =", st.last_rvol)

    hs = e.health.status()

    print("\n=== HEALTH ===")
    print("feed_ok =", hs.feed_ok)
    print("chain_ok =", hs.chain_ok)
    print("tick_age =", hs.last_tick_age_s)
    print("chain_age =", hs.last_chain_age_s)
    print("health_degraded =", e.health.degraded)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await e.shutdown()

    print("\nREAL_ENGINE_NUCLEAR=DONE")

asyncio.run(main())
