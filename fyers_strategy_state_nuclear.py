import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
    log = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    e = Dhan._build_engine(
        cfg, ins, clock, log, metrics,
        live=True,
        use_nse_chain=True
    )

    e.use_nse_chain = True
    e.health.use_nse_chain = True

    await e.nse_chain.start()
    task = asyncio.create_task(e.run())

    await asyncio.sleep(45)

    st = e.store.get(cfg.engine.underlyings[0])
    s = metrics.snapshot()

    print("\n=== NUCLEAR STRATEGY STATE ===")
    print("bars_1m =", len(st.bars_1m))
    print("bars_5m =", len(st.bars_5m))
    print("last_bar_1m =", st.bars_1m[-1] if st.bars_1m else None)
    print("last_bar_5m =", st.bars_5m[-1] if st.bars_5m else None)
    print("regime =", st.regime.state)
    print("bias =", st.structure.bias)
    print("rvol =", st.last_rvol)
    print("bar_class =", st.last_1m_class)
    print("last_chain_present =", st.last_chain is not None)
    print("last_options_view_present =", st.last_options_view is not None)

    print("\n=== COUNTERS ===")
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
        "cycle_exceptions",
        "cycle_failclosed",
        "chain_poll_errors",
        "task_restarts",
    ]:
        print(k, "=", s["counters"].get(k, 0))

    hs = e.health.status()
    print("\n=== HEALTH ===")
    print("feed_ok =", hs.feed_ok)
    print("chain_ok =", hs.chain_ok)
    print("health_degraded =", e.health.degraded)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await e.shutdown()

asyncio.run(main())
