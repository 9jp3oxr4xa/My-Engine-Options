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

    st = e.store.get(cfg.engine.underlyings[0])
    se = st.structure

    print("\n=== BINGO STRUCTURE RESULT ===")
    print("BARS_5M =", len(st.bars_5m))
    print("SWINGS =", len(se.swings))
    print("BIAS =", se.bias)
    print("EVENTS =", len(se.events))

    print("\nLAST_SWINGS:")
    for s in se.swings[-10:]:
        print(s)

    print("\nLAST_EVENTS:")
    for ev in se.events[-10:]:
        print(ev)

    print("\nREGIME =", st.regime.state)
    print("ADX =", st.adx.value)
    print("ADX_RISING =", st.adx.rising)
    print("AVWAP =", st.avwap.value)
    print("AVWAP_SLOPE =", st.avwap.slope_over(10))
    print("SWING_COUNT_OK_FOR_TREND =", len(se.swings) >= 4)

    await e.shutdown()

asyncio.run(main())
