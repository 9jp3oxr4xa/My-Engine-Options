import asyncio
import aiohttp

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}

URLS = [
    "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY",
    "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiryDate=",
    "https://www.nseindia.com/api/live-analysis-variations?index=gainers&type=F&O",
]

async def main():
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        print("STEP 1: Opening NSE...")
        async with session.get(
            "https://www.nseindia.com/option-chain",
            timeout=timeout,
        ) as r:
            print("NSE_PAGE_STATUS=", r.status)
            print("NSE_PAGE_LENGTH=", len(await r.text()))

        for i, url in enumerate(URLS, 1):
            print(f"\nSTEP {i+1}: {url}")

            try:
                async with session.get(url, timeout=timeout) as r:
                    text = await r.text()

                    print("STATUS=", r.status)
                    print("FINAL_URL=", str(r.url))
                    print("CONTENT_TYPE=", r.headers.get("Content-Type"))
                    print("LENGTH=", len(text))
                    print("PREVIEW=", text[:500].replace("\n", " "))

                    if r.status == 200:
                        try:
                            data = await r.json(content_type=None)
                            print("JSON_OK=YES")
                            print("TOP_LEVEL_KEYS=", list(data.keys())[:20])

                            records = data.get("records", {})
                            if isinstance(records, dict):
                                print(
                                    "UNDERLYING_VALUE=",
                                    records.get("underlyingValue")
                                )
                                print(
                                    "EXPIRIES=",
                                    records.get("expiryDates", [])[:5]
                                )
                                print(
                                    "ROWS=",
                                    len(records.get("data", []))
                                )

                            data_section = data.get("data", {})
                            if isinstance(data_section, dict):
                                print(
                                    "DATA_KEYS=",
                                    list(data_section.keys())[:20]
                                )

                        except Exception as e:
                            print("JSON_PARSE_ERROR=", repr(e))

            except Exception as e:
                print("REQUEST_ERROR=", repr(e))

asyncio.run(main())
