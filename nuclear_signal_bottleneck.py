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
    await e.bootstrap()

    u = cfg.engine.underlyings[0]
    st = e.store.get(u)

    print("\n=== NUCLEAR SIGNAL BOTTLENECK ===")
    print("UNDERLYING =", u)
    print("BARS_1M =", len(st.bars_1m))
    print("BARS_5M =", len(st.bars_5m))
    print("REGIME =", st.regime.state.regime)
    print("REGIME_STRENGTH =", st.regime.state.strength_0_100)
    print("BIAS =", st.structure.bias)
    print("ADX =", st.adx.value)
    print("ADX_RISING =", st.adx.rising)
    print("AVWAP =", st.avwap.value)
    print("AVWAP_SLOPE =", st.avwap.slope_over(10))
    print("RVOL =", st.last_rvol)
    print("SWINGS =", len(st.structure.swings))
    print("EVENTS =", len(st.structure.events))

    now = e.clock.now()

    print("\n=== EVENT AGE / DIRECTION ===")
    for ev in list(st.structure.events)[-15:]:
        age = (now - ev.ts).total_seconds()
        d = e._direction_for(ev, st.regime.state.regime, st.structure.bias)
        print(
            ev.kind.value,
            "TS=", ev.ts.isoformat(),
            "AGE_S=", round(age, 1),
            "LEVEL=", ev.level,
            "DIRECTION=", d,
        )

    print("\n=== PRECONDITION ===")
    phase = e.calendar.phase(now)
    print("PHASE =", phase)
    print("PRECONDITIONS_OK =", e._preconditions_ok(
        st, phase, now, st.regime.state
    ))

    print("\n=== SCAN RESULT ===")
    candidate = e._scan_trigger(u, st)
    print("CANDIDATE =", candidate)

    await e.shutdown()

asyncio.run(main())
