from decimal import Decimal
from datetime import date
from zoneinfo import ZoneInfo

from nse_option_provider import NSEOptionChainProvider


def _aware_ist(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return ts.astimezone(ZoneInfo("Asia/Kolkata"))


class NSEChainAdapter:
    """
    NSE option-chain source using the existing Dhan REST interface.
    """

    def __init__(self, provider, logger=None):
        self.provider = provider
        self.logger = logger

    async def start(self):
        await self.provider.start()

    async def close(self):
        await self.provider.close()

    async def expiry_list(
        self,
        underlying_scrip: int,
        underlying_seg: str = "IDX_I",
        underlying: str = "NIFTY",
    ):
        return await self.provider.get_expiries(underlying)

    async def option_chain(
        self,
        underlying: str,
        underlying_scrip: int,
        expiry: date,
        spot_hint: Decimal,
        underlying_seg: str = "IDX_I",
    ):
        try:
            snap = await self.provider.get_chain(
                symbol=underlying,
                expiry=expiry,
            )
        except RuntimeError as exc:
            from Dhan import TransientInfraError
            raise TransientInfraError(str(exc)) from exc

        from Dhan import (
            ChainSnapshot,
            ChainStrike,
            OptionLeg,
            _d,
        )

        def convert_leg(leg):
            return OptionLeg(
                ltp=_d(leg.ltp),
                bid=_d(leg.bid),
                ask=_d(leg.ask),
                oi=int(leg.oi),
                oi_prev=int(leg.oi_prev),
                volume=int(leg.volume),
                iv=_d(leg.iv),
                bid_qty=int(leg.bid_qty),
                ask_qty=int(leg.ask_qty),
                security_id=str(leg.security_id),
                delta=None,
            )

        strikes = [
            ChainStrike(
                strike=_d(s.strike),
                ce=convert_leg(s.ce),
                pe=convert_leg(s.pe),
            )
            for s in snap.strikes
        ]

        return ChainSnapshot(
            underlying=snap.underlying,
            expiry=snap.expiry,
            spot=_d(snap.spot),
            ts=_aware_ist(snap.ts),
            strikes=strikes,
            atm_strike=_d(snap.atm_strike),
        )
