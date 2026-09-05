import asyncio
import aiohttp
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any


NSE_BASE = "https://www.nseindia.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}


@dataclass
class NSEOptionLeg:
    ltp: Decimal
    bid: Decimal
    ask: Decimal
    oi: int
    oi_prev: int
    volume: int
    iv: Decimal
    bid_qty: int
    ask_qty: int
    security_id: str


@dataclass
class NSEChainStrike:
    strike: Decimal
    ce: NSEOptionLeg
    pe: NSEOptionLeg


@dataclass
class NSEChainSnapshot:
    underlying: str
    expiry: date
    spot: Decimal
    ts: datetime
    strikes: List[NSEChainStrike]
    atm_strike: Decimal


def dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def parse_expiry(value: str) -> date:
    return datetime.strptime(value, "%d-%b-%Y").date()


def make_leg(raw: Dict[str, Any]) -> NSEOptionLeg:
    oi = int(raw.get("openInterest", 0) or 0)
    change = int(raw.get("changeinOpenInterest", 0) or 0)

    return NSEOptionLeg(
        ltp=dec(raw.get("lastPrice")),
        bid=dec(raw.get("buyPrice1")),
        ask=dec(raw.get("sellPrice1")),
        oi=oi,
        oi_prev=oi - change,
        volume=int(raw.get("totalTradedVolume", 0) or 0),
        iv=dec(raw.get("impliedVolatility")),
        bid_qty=int(raw.get("totalBuyQuantity", 0) or 0),
        ask_qty=int(raw.get("totalSellQuantity", 0) or 0),
        security_id=str(raw.get("identifier", "")),
    )


class NSEOptionChainProvider:

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self.session = aiohttp.ClientSession(headers=HEADERS)

        async with self.session.get(
            f"{NSE_BASE}/option-chain",
            timeout=20
        ) as r:
            if r.status != 200:
                raise RuntimeError(
                    f"NSE session failed: HTTP {r.status}"
                )

    async def close(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def get_expiries(self, symbol: str = "NIFTY") -> List[date]:
        if self.session is None:
            raise RuntimeError("Provider not started")

        url = (
            f"{NSE_BASE}/api/"
            f"option-chain-contract-info?symbol={symbol}"
        )

        async with self.session.get(url, timeout=20) as r:
            if r.status != 200:
                raise RuntimeError(
                    f"Expiry request failed: HTTP {r.status}"
                )

            data = await r.json(content_type=None)

        return [
            parse_expiry(x)
            for x in data.get("expiryDates", [])
        ]

    async def get_chain(
        self,
        symbol: str = "NIFTY",
        expiry: Optional[date] = None,
    ) -> NSEChainSnapshot:

        if self.session is None:
            raise RuntimeError("Provider not started")

        expiries = await self.get_expiries(symbol)

        if not expiries:
            raise RuntimeError(
                f"No NSE expiries available for {symbol}"
            )

        if expiry is None:
            expiry = expiries[0]

        expiry_text = expiry.strftime("%d-%b-%Y")

        url = (
            f"{NSE_BASE}/api/option-chain-v3"
            f"?type=Indices"
            f"&symbol={symbol}"
            f"&expiry={expiry_text}"
        )

        async with self.session.get(url, timeout=20) as r:
            if r.status != 200:
                raise RuntimeError(
                    f"Option chain failed: HTTP {r.status}"
                )

            data = await r.json(content_type=None)

        records = data.get("records", {})
        rows = records.get("data", [])

        if not rows:
            raise RuntimeError(
                f"Empty NSE option chain for {symbol} "
                f"{expiry_text}"
            )

        spot = dec(records.get("underlyingValue"))

        strikes: List[NSEChainStrike] = []

        for row in rows:
            strike = dec(row.get("strikePrice"))
            ce_raw = row.get("CE") or {}
            pe_raw = row.get("PE") or {}

            if not ce_raw or not pe_raw:
                continue

            strikes.append(
                NSEChainStrike(
                    strike=strike,
                    ce=make_leg(ce_raw),
                    pe=make_leg(pe_raw),
                )
            )

        if not strikes:
            raise RuntimeError(
                f"No complete CE/PE rows for {symbol}"
            )

        strikes.sort(key=lambda x: x.strike)

        atm = min(
            strikes,
            key=lambda x: abs(x.strike - spot)
        ).strike

        return NSEChainSnapshot(
            underlying=symbol,
            expiry=expiry,
            spot=spot,
            ts=datetime.now(),
            strikes=strikes,
            atm_strike=atm,
        )


async def main():
    provider = NSEOptionChainProvider()

    try:
        print("STEP 1: Starting NSE provider...")
        await provider.start()
        print("NSE_PROVIDER=OK")

        print("\nSTEP 2: Fetching expiries...")
        expiries = await provider.get_expiries("NIFTY")

        print("EXPIRY_COUNT=", len(expiries))
        print("NEAREST_EXPIRY=", expiries[0])

        print("\nSTEP 3: Fetching normalized chain...")
        snap = await provider.get_chain(
            "NIFTY",
            expiries[0],
        )

        print("UNDERLYING=", snap.underlying)
        print("EXPIRY=", snap.expiry)
        print("SPOT=", snap.spot)
        print("ATM=", snap.atm_strike)
        print("STRIKES=", len(snap.strikes))

        print("\nSTEP 4: ATM ± 2")

        ordered = sorted(
            snap.strikes,
            key=lambda x: abs(x.strike - snap.atm_strike)
        )[:5]

        for st in sorted(ordered, key=lambda x: x.strike):
            print(
                f"STRIKE={st.strike} "
                f"CE={st.ce.ltp} "
                f"PE={st.pe.ltp} "
                f"CE_OI={st.ce.oi} "
                f"PE_OI={st.pe.oi} "
                f"CE_VOL={st.ce.volume} "
                f"PE_VOL={st.pe.volume}"
            )

        print("\nNSE_PROVIDER_SMOKE=PASS")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
