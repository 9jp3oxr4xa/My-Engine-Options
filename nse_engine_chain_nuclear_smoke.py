import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml("config\config.yaml"))
    instruments = Dhan.Instruments.load(Dhan._load_yaml("config\instruments.yaml"))
    logger = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    engine = Dhan._build_engine(
        cfg, instruments, clock, logger, metrics,
        live=True,
        use_nse_chain=True
    )

    print("ENGINE_BUILD=PASS")
    print("NSE_CHAIN=", type(engine.nse_chain).__name__)
    print("WS=", engine.ws)

    await engine.nse_chain.start()
    print("NSE_CHAIN_START=PASS")

    await engine._refresh_expiries(True)
    print("EXPIRIES=", engine.expiries)

    for u in cfg.engine.underlyings:
        print("POLLING=", u)
        await engine._poll_chain(u)
        st = engine.store.get(u)
        print(
            "CHAIN_RESULT=",
            u,
            "last_chain=",
            st.last_chain is not None,
            "spot=",
            getattr(st.last_chain, "spot", None),
            "strikes=",
            len(st.last_chain.strikes) if st.last_chain else 0
        )

    await engine.nse_chain.close()

asyncio.run(main())
