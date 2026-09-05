import asyncio
import aiohttp

URL = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}

async def main():
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        print("STEP 1: Opening NSE...")
        async with session.get(
            "https://www.nseindia.com/option-chain",
            timeout=timeout,
        ) as r:
            print("NSE_PAGE_STATUS=", r.status)

        print("STEP 2: Requesting NIFTY option chain...")
        async with session.get(
            URL,
            timeout=timeout,
        ) as r:
            print("OPTION_CHAIN_STATUS=", r.status)
            text = await r.text()

            print("RESPONSE_LENGTH=", len(text))
            print(text[:1000])

            if r.status == 200:
                try:
                    data = await r.json(content_type=None)
                    records = data.get("records", {})
                    print("UNDERLYING_VALUE=", records.get("underlyingValue"))
                    print("EXPIRIES=", records.get("expiryDates", [])[:5])
                    print("CONTRACT_ROWS=", len(records.get("data", [])))
                    print("NIFTY_DATA_OK=YES")
                except Exception as e:
                    print("JSON_PARSE_ERROR=", repr(e))

asyncio.run(main())
