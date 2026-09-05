import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    ins = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
    log = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    m = Dhan.Metrics()
    c = Dhan.Clock()

    e = Dhan._build_engine(cfg, ins, c, log, m, live=True, use_nse_chain=True)
    e.use_nse_chain = True
    e.health.use_nse_chain = True

    await e.nse_chain.start()
    await e.bootstrap()

    u = cfg.engine.underlyings[0]
    st = e.store.get(u)
    now = e.clock.now()

    print("\n=== BINGO FINAL TRIGGER DIAGNOSTIC ===")
    print("NOW =", now)
    print("REGIME =", st.regime.state.regime)
    print("BIAS =", st.structure.bias)

    for ev in st.structure.events[-10:]:
        age = (now - ev.ts).total_seconds()
        direction = e._direction_for(ev, st.regime.state.regime, st.structure.bias)
        print(
            "EVENT=", ev.kind,
            "TS=", ev.ts,
            "AGE_S=", round(age,1),
            "DIRECTION=", direction
        )

    candidate = e._scan_trigger(u, st)
    print("CANDIDATE =", candidate)

    await e.shutdown()

asyncio.run(main())
