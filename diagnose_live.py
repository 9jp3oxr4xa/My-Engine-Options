import asyncio
import Dhan
from datetime import datetime

_ORIGINAL = Dhan.Engine._evaluate_inner

def diagnostic_evaluate_inner(self, underlying):
    st = self.store.get(underlying)
    now = self.clock.now()
    strength = st.regime.state.strength_0_100
    phase = self.calendar.phase(now)
    window = self.calendar.signal_window_open(now, strength)

    print(
        f"DIAG_EVAL "
        f"ts={now.isoformat()} "
        f"phase={phase.value} "
        f"strength={strength} "
        f"window={window} "
        f"feed_ok={self.health.status().feed_ok} "
        f"chain_ok={self.health.status().chain_ok}"
    )

    return _ORIGINAL(self, underlying)

Dhan.Engine._evaluate_inner = diagnostic_evaluate_inner

async def main():
    cfg = Dhan.load_config(Dhan._load_yaml("config/config.yaml"))
    instruments = Dhan.Instruments.load(
        Dhan._load_yaml("config/instruments.yaml")
    )

    logger = Dhan.setup_logging(
        cfg.logging.level,
        cfg.logging.json,
        cfg.logging.dir
    )
    metrics = Dhan.Metrics()
    clock = Dhan.Clock()

    engine = Dhan._build_engine(
        cfg,
        instruments,
        clock,
        logger,
        metrics,
        live=True,
        use_nse_chain=True,
    )

    await engine.nse_chain.start()

    print("DIAGNOSTIC ENGINE STARTED")
    print("CLOCK_NOW=", clock.now().isoformat())

    try:
        await asyncio.wait_for(engine.run(), timeout=120)
    except asyncio.TimeoutError:
        print("DIAGNOSTIC_TIMEOUT_120S")
    finally:
        await engine.shutdown()

asyncio.run(main())
