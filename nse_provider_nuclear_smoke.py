import asyncio
from nse_option_provider import NSEOptionChainProvider

async def main():
    p = NSEOptionChainProvider()
    try:
        await p.start()
        print("NSE_START=PASS")

        e = await p.get_expiries("NIFTY")
        print("EXPIRIES=", e[:5])

        s = await p.get_chain("NIFTY", e[0])
        print("CHAIN=PASS")
        print("SPOT=", s.spot)
        print("EXPIRY=", s.expiry)
        print("STRIKES=", len(s.strikes))
    finally:
        await p.close()

asyncio.run(main())
