import os, sys

PATH = "Dhan.py"
with open(PATH, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()

if "chain_adapters" in src:
    print("ABORT_ALREADY_PATCHED")
    sys.exit(2)

eol = "\r\n" if "\r\n" in src else "\n"
def N(s):
    return s.replace("\r\n", "\n").replace("\n", eol)

EDITS = []

EDITS.append(("E1_ADAPTER_MAP_INIT",
'''        self._active_expiry: Dict[str, date] = {}
        self._last_subscriptions: List[Tuple[str, str]] = []''',
'''        self._active_expiry: Dict[str, date] = {}
        self._last_subscriptions: List[Tuple[str, str]] = []
        self.chain_adapters: Dict[str, Any] = {}''', 1))

EDITS.append(("E2_HELPER_AND_POLL_ENTRY",
'''    async def _poll_chain(self, underlying: str) -> None:
        scrip = self.scrip_map[underlying]''',
'''    def _chain_adapter_for(self, underlying: str) -> Any:
        adapter = self.chain_adapters.get(underlying)
        if adapter is None:
            raise FatalConfigError(
                f"no option-chain adapter configured for underlying "
                f"{underlying}; per-underlying routing forbids fallback")
        return adapter

    async def _poll_chain(self, underlying: str) -> None:
        adapter = self._chain_adapter_for(underlying)
        scrip = self.scrip_map[underlying]''', 1))

EDITS.append(("E3_POLL_CALL",
'''        snap = await self.nse_chain.option_chain(underlying, scrip, expiry, spot_hint)''',
'''        snap = await adapter.option_chain(underlying, scrip, expiry, spot_hint)''', 1))

EDITS.append(("E4_EXPIRY_ROUTING",
'''        for u in self.cfg.engine.underlyings:
            scrip = self.scrip_map[u]
            try:
                expiries = await self.rest.expiry_list(scrip, underlying=u)''',
'''        for u in self.cfg.engine.underlyings:
            scrip = self.scrip_map[u]
            adapter = self._chain_adapter_for(u)
            try:
                expiries = await adapter.expiry_list(scrip, underlying=u)''', 1))

EDITS.append(("E5_BUILD_WIRING",
'''    if nse_chain is not None:
        engine.nse_chain = nse_chain''',
'''    if nse_chain is not None:
        engine.nse_chain = nse_chain
        for _u in cfg.engine.underlyings:
            if _u == "NIFTY":
                engine.chain_adapters[_u] = nse_chain''', 1))

failed = False
for name, old, new, exp in EDITS:
    c = src.count(N(old))
    print(f"{name}: count={c} expected={exp}")
    if c != exp:
        failed = True
if failed:
    print("S3_PATCH=ANCHOR_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(2)

for name, old, new, exp in EDITS:
    src = src.replace(N(old), N(new))

p_map  = src.count("chain_adapters")
p_help = src.count("_chain_adapter_for")
p_old  = src.count("self.nse_chain.option_chain")
p_rest = src.count("self.rest.expiry_list")
p_nc   = src.count("self.nse_chain")
p_brdg = src.count("rest.expiry_list = nse_chain.expiry_list")
print(f"POST: MAP={p_map} (expect 3) HELPER={p_help} (expect 3) "
      f"OLD_CALL={p_old} (expect 0) REST_EXPIRY={p_rest} (expect 0) "
      f"NSE_CHAIN={p_nc} (expect 1) BRIDGE={p_brdg} (expect 1)")
if (p_map != 3 or p_help != 3 or p_old != 0 or p_rest != 0
        or p_nc != 1 or p_brdg != 1):
    print("S3_PATCH=POSTCHECK_ABORT_NO_CHANGES_WRITTEN")
    sys.exit(3)

tmp = PATH + ".s3tmp"
with open(tmp, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
os.replace(tmp, PATH)
print("S3_PATCH=APPLIED")
