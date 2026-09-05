import asyncio
import Dhan

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml(r"config\config.yaml"))
    instruments = Dhan.Instruments.load(Dhan._load_yaml(r"config\instruments.yaml"))
    logger = Dhan.setup_logging(cfg.logging.level, cfg.logging.json, cfg.logging.dir)
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    engine = Dhan._build_engine(
        cfg, instruments, clock, logger, metrics,
        live=True,
        use_nse_chain=True
    )

    await engine.nse_chain.start()

    print("LIVE_ENGINE_START=PASS")

    task = asyncio.create_task(engine.run())

    await asyncio.sleep(15)

    st = engine.store.get("NIFTY")
    print("LIVE_CHAIN_PRESENT=", st.last_chain is not None)
    print("LIVE_CHAIN_SPOT=", getattr(st.last_chain, "spot", None))
    print("LIVE_CHAIN_STRIKES=", len(st.last_chain.strikes) if st.last_chain else 0)
    print("LIVE_WS=", engine.ws)

    await engine.shutdown()
    await asyncio.gather(task, return_exceptions=True)

asyncio.run(main())
