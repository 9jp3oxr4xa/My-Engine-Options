import asyncio
import aiohttp
import re
from urllib.parse import urljoin

URL = "https://www.nseindia.com/option-chain"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

async def main():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(URL, timeout=20) as r:
            html = await r.text()

        scripts = re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\']',
            html,
            re.I
        )

        print("PAGE_STATUS=", r.status)
        print("SCRIPT_COUNT=", len(scripts))

        for src in scripts:
            full = urljoin(URL, src)

            if "option" in full.lower() or "main" in full.lower() or "chunk" in full.lower():
                print(full)

asyncio.run(main())
