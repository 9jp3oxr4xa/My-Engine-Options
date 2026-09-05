import asyncio
import aiohttp
from decimal import Decimal
from datetime import date, datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}

NSE_PAGE = "https://www.nseindia.com/option-chain"
NSE_CONTRACT = "https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY"

def D(x, default="0"):
    try:
        return Decimal(str(x if x is not None else default))
    except Exception:
        return Decimal(default)

def parse_leg(leg):
    if not isinstance(leg, dict):
        return None

    return {
        "ltp": D(leg.get("lastPrice")),
        "bid": D(leg.get("buyPrice1")),
        "ask": D(leg.get("sellPrice1")),
        "oi": int(leg.get("openInterest", 0) or 0),
        "oi_change": int(leg.get("changeinOpenInterest", 0) or 0),
        "volume": int(leg.get("totalTradedVolume", 0) or 0),
        "iv": D(leg.get("impliedVolatility")),
        "bid_qty": int(leg.get("totalBuyQuantity", 0) or 0),
        "ask_qty": int(leg.get("totalSellQuantity", 0) or 0),
        "identifier": str(leg.get("identifier", "")),
    }

async def main():
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        print("STEP 1: Establishing NSE session...")
        async with session.get(NSE_PAGE, timeout=timeout) as r:
            page_status = r.status
            await r.read()

        print("NSE_PAGE_STATUS=", page_status)

        if page_status != 200:
            raise RuntimeError("NSE option-chain page failed")

        print("\nSTEP 2: Discovering NIFTY expiries...")

        async with session.get(NSE_CONTRACT, timeout=timeout) as r:
            contract = await r.json(content_type=None)

        expiries = contract.get("expiryDates", [])

        if not expiries:
            raise RuntimeError("No NIFTY expiries returned")

        expiry_text = expiries[0]
        expiry = datetime.strptime(expiry_text, "%d-%b-%Y").date()

        print("EXPIRY_COUNT=", len(expiries))
        print("SELECTED_EXPIRY=", expiry)

        print("\nSTEP 3: Downloading NIFTY option chain...")

        chain_url = (
            "https://www.nseindia.com/api/option-chain-v3"
            "?type=Indices"
            "&symbol=NIFTY"
            "&expiry=" + expiry_text
        )

        async with session.get(chain_url, timeout=timeout) as r:
            status = r.status
            chain = await r.json(content_type=None)

        print("CHAIN_STATUS=", status)

        if status != 200:
            raise RuntimeError(f"Chain request failed: {status}")

        records = chain.get("records", {})
        rows = records.get("data", [])

        spot = D(records.get("underlyingValue"))

        print("UNDERLYING=", spot)
        print("ROWS=", len(rows))

        if not rows:
            raise RuntimeError("NSE returned zero option-chain rows")

        print("\nSTEP 4: Building internal normalized chain...")

        normalized = []

        for row in rows:
            strike = D(row.get("strikePrice"))

            ce = parse_leg(row.get("CE"))
            pe = parse_leg(row.get("PE"))

            normalized.append({
                "strike": strike,
                "ce": ce,
                "pe": pe,
            })

        normalized.sort(key=lambda x: x["strike"])

        atm = min(
            normalized,
            key=lambda x: abs(x["strike"] - spot)
        )

        atm_strike = atm["strike"]

        print("ATM_STRIKE=", atm_strike)
        print("NORMALIZED_ROWS=", len(normalized))

        print("\nSTEP 5: ATM ± 2 strikes")

        nearby = sorted(
            normalized,
            key=lambda x: abs(x["strike"] - atm_strike)
        )[:5]

        nearby.sort(key=lambda x: x["strike"])

        for row in nearby:
            print("\nSTRIKE=", row["strike"])

            for name in ("ce", "pe"):
                leg = row[name]

                if leg is None:
                    print(name.upper(), "= MISSING")
                    continue

                print(
                    name.upper(),
                    "LTP=", leg["ltp"],
                    "BID=", leg["bid"],
                    "ASK=", leg["ask"],
                    "OI=", leg["oi"],
                    "OI_CHANGE=", leg["oi_change"],
                    "VOL=", leg["volume"],
                    "IV=", leg["iv"],
                    "BID_QTY=", leg["bid_qty"],
                    "ASK_QTY=", leg["ask_qty"],
                    "IDENTIFIER=", leg["identifier"],
                )

        print("\nSTEP 6: Compatibility checks")

        assert spot > 0, "Underlying value invalid"
        assert len(normalized) > 0, "Normalized chain empty"
        assert atm_strike > 0, "ATM strike invalid"

        ce_count = sum(
            1 for x in normalized
            if x["ce"] is not None
        )

        pe_count = sum(
            1 for x in normalized
            if x["pe"] is not None
        )

        identifier_count = sum(
            1
            for x in normalized
            for side in ("ce", "pe")
            if x[side] is not None and x[side]["identifier"]
        )

        print("CE_ROWS=", ce_count)
        print("PE_ROWS=", pe_count)
        print("IDENTIFIERS=", identifier_count)

        assert ce_count > 0, "No CE legs"
        assert pe_count > 0, "No PE legs"
        assert identifier_count > 0, "No option identifiers"

        print("\nNSE_TO_INTERNAL_CHAIN_OK=YES")
        print("Dhan.py CHANGED=NO")
        print("TRADING_LOGIC_CHANGED=NO")

asyncio.run(main())
