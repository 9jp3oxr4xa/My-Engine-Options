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
    se = st.structure

    b = st.bars_5m[-1]

    ok_adx = st.adx.value is not None and st.adx.value >= 22
    ok_rising = st.adx.rising
    ok_swings = len(se.swings) >= 4

    seq_bull = st.regime._check_sequence(se.swings, "BULLISH")
    seq_bear = st.regime._check_sequence(se.swings, "BEARISH")

    avwap_bull = st.regime._check_avwap_side(
        b, st.avwap.value, "BULLISH"
    )
    avwap_bear = st.regime._check_avwap_side(
        b, st.avwap.value, "BEARISH"
    )

    classified = st.regime._classify(
        b,
        Dhan.AnalyticsView(
            adx=st.adx.value,
            adx_rising=st.adx.rising,
            swings=se.swings,
            bias=se.bias,
            avwap=st.avwap.value,
            avwap_slope=st.avwap.slope_over(10),
            avwap_dist_sigma=st.avwap.distance_in_sigma(b.close),
            bb_pct=st.bb.percentile_rank(),
            bb_rising_3=st.bb.rising_3,
            impulse_present=st.last_1m_class == "impulse",
            phase=e.calendar.phase(b.ts_open),
            opening_range_broken=False,
            opening_extreme_swept=False,
            atr_5m=st.atr_5m.value,
        )
    )

    print("\n=== BINGO GATES ===")
    print("ADX_VALUE =", st.adx.value)
    print("ADX_GE_22 =", ok_adx)
    print("ADX_RISING =", ok_rising)
    print("SWINGS_GE_4 =", ok_swings)
    print("BIAS =", se.bias)
    print("BULL_SEQUENCE =", seq_bull)
    print("BEAR_SEQUENCE =", seq_bear)
    print("AVWAP_BULL =", avwap_bull)
    print("AVWAP_BEAR =", avwap_bear)
    print("CLASSIFIED_REGIME =", classified)

    await e.shutdown()

asyncio.run(main())
