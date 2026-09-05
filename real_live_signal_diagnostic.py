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

    await asyncio.sleep(90)

    u = cfg.engine.underlyings[0]
    st = e.store.get(u)
    counters = m.snapshot()["counters"]

    print("\n=== REAL LIVE SIGNAL DIAGNOSTIC ===")
    print("BARS_1M =", len(st.bars_1m))
    print("BARS_5M =", len(st.bars_5m))
    print("SWINGS =", len(st.structure.swings))
    print("EVENTS =", len(st.structure.events))
    print("REGIME =", st.regime.state.regime)
    print("REGIME_STRENGTH =", st.regime.state.strength_0_100)
    print("BIAS =", st.structure.bias)
    print("ADX =", st.adx.value)
    print("ADX_RISING =", st.adx.rising)
    print("AVWAP =", st.avwap.value)
    print("AVWAP_SLOPE =", st.avwap.slope_over(10))
    print("RVOL =", st.last_rvol)

    print("\n=== COUNTERS ===")
    for k in (
        "ticks_ingested",
        "bars_5m",
        "structure_events",
        "cycles",
        "skip_window",
        "skip_warmup",
        "skip_degraded",
        "skip_stale",
        "candidates",
        "signals",
        "rejections",
    ):
        print(k, "=", counters.get(k, 0))

    print("\n=== EVENTS ===")
    now = e.clock.now()

    for ev in list(st.structure.events)[-15:]:
        age = (now - ev.ts).total_seconds()
        try:
            direction = e._direction_for(
                ev,
                st.regime.state.regime,
                st.structure.bias,
            )
        except TypeError:
            direction = e._direction_for(
                ev,
                st.regime.state.regime,
            )

        print(
            ev.kind.value,
            "AGE_S=", round(age, 1),
            "LEVEL=", ev.level,
            "DIRECTION=", direction,
        )

    print("\n=== SCAN ===")
    try:
        candidate = e._scan_trigger(u, st)
        print("CANDIDATE =", candidate)
    except Exception as exc:
        print("SCAN_ERROR =", type(exc).__name__, str(exc))

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await e.shutdown()

asyncio.run(main())
