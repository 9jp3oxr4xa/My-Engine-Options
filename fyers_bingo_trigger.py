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

    candidate = e._scan_trigger(u, st)

    print("\n=== BINGO TRIGGER RESULT ===")
    print("CANDIDATE =", candidate)
    print("REGIME =", st.regime.state)
    print("BIAS =", st.structure.bias)
    print("SWINGS =", len(st.structure.swings))
    print("EVENTS =", len(st.structure.events))
    print("BARS_5M =", len(st.bars_5m))
    print("ADX =", st.adx.value)
    print("AVWAP =", st.avwap.value)
    print("RVOL =", st.last_rvol)

    await e.shutdown()

asyncio.run(main())
