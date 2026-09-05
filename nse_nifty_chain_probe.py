import asyncio
import aiohttp
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
}

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:

        # Establish NSE session/cookies
        async with session.get(
            "https://www.nseindia.com/option-chain",
            timeout=20
        ) as r:
            print("NSE_STATUS=", r.status)

        expiry_url = (
            "https://www.nseindia.com/"
            "api/option-chain-contract-info?symbol=NIFTY"
        )

        async with session.get(expiry_url, timeout=20) as r:
            contract = await r.json(content_type=None)

        expiry = contract["expiryDates"][0]

        print("SELECTED_EXPIRY=", expiry)

        chain_url = (
            "https://www.nseindia.com/"
            "api/option-chain-v3"
            "?type=Indices"
            "&symbol=NIFTY"
            "&expiry=" + expiry
        )

        print("CHAIN_URL=", chain_url)

        async with session.get(chain_url, timeout=20) as r:
            text = await r.text()

            print("CHAIN_STATUS=", r.status)
            print("CONTENT_TYPE=", r.headers.get("Content-Type"))
            print("LENGTH=", len(text))
            print("PREVIEW=", text[:3000])

            if r.status == 200:
                try:
                    data = json.loads(text)

                    print("\nTOP_LEVEL_KEYS=", list(data.keys()))

                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                print(f"{k}_COUNT=", len(v))
                            elif isinstance(v, dict):
                                print(f"{k}_KEYS=", list(v.keys())[:20])
                            else:
                                print(f"{k}=", v)

                    print("\nNIFTY_CHAIN_OK=YES")

                except Exception as e:
                    print("JSON_ERROR=", repr(e))

asyncio.run(main())
