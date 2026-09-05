import asyncio
import aiohttp

PAGE_URL = "https://www.nseindia.com/option-chain"
API_URL = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": PAGE_URL,
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

async def main():
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(
        headers=HEADERS,
        cookie_jar=aiohttp.CookieJar()
    ) as session:

        print("STEP 1: Opening NSE option-chain page...")

        async with session.get(
            PAGE_URL,
            timeout=timeout,
            allow_redirects=True,
        ) as r:
            page = await r.text()
            print("NSE_PAGE_STATUS=", r.status)
            print("NSE_FINAL_URL=", str(r.url))
            print("COOKIES=", session.cookie_jar.filter_cookies(r.url))
            print("PAGE_LENGTH=", len(page))

        print("\nSTEP 2: Requesting NIFTY option chain...")

        async with session.get(
            API_URL,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": PAGE_URL,
                "User-Agent": HEADERS["User-Agent"],
            },
            timeout=timeout,
            allow_redirects=True,
        ) as r:

            print("OPTION_CHAIN_STATUS=", r.status)
            print("OPTION_CHAIN_FINAL_URL=", str(r.url))

            text = await r.text()

            print("RESPONSE_LENGTH=", len(text))
            print("CONTENT_TYPE=", r.headers.get("Content-Type"))
            print("SERVER=", r.headers.get("Server"))
            print("RESPONSE_PREVIEW=")
            print(text[:1000])

            if r.status == 200:
                try:
                    data = await r.json(content_type=None)

                    records = data.get("records", {})

                    print("\nNIFTY_DATA_OK=YES")
                    print("UNDERLYING_VALUE=", records.get("underlyingValue"))
                    print("EXPIRIES=", records.get("expiryDates", [])[:5])
                    print("CONTRACT_ROWS=", len(records.get("data", [])))

                except Exception as e:
                    print("JSON_PARSE_ERROR=", repr(e))

asyncio.run(main())
