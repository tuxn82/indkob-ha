#!/usr/bin/env python3
"""Testværktøj til at prøve nemlig-klienten af uden Home Assistant.

  pip install aiohttp
  python3 tools/cli.py search "letmælk"
  python3 tools/cli.py basket [--raw]
  python3 tools/cli.py add 701011 [--qty 1]
  python3 tools/cli.py scan 5700426101217 [--add]

Login: NEMLIG_USER / NEMLIG_PASS, ellers spørges der.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "indkob"))

import aiohttp  # noqa: E402

from nemlig_api import NemligClient, NemligError, line_product_id, line_quantity, lookup_ean  # noqa: E402
from matching import build_query, is_confident, rank  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser(description="nemlig.com testklient")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    b = sub.add_parser("basket")
    b.add_argument("--raw", action="store_true")
    a = sub.add_parser("add")
    a.add_argument("product_id")
    a.add_argument("--qty", type=int, default=1)
    sc = sub.add_parser("scan")
    sc.add_argument("ean")
    sc.add_argument("--add", action="store_true")
    args = ap.parse_args()

    user = os.environ.get("NEMLIG_USER") or input("E-mail: ")
    pw = os.environ.get("NEMLIG_PASS") or getpass.getpass("Password: ")

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        client = NemligClient(session, user, pw)
        await client.login()

        if args.cmd == "search":
            for p in await client.search(args.query):
                print(p)

        elif args.cmd == "basket":
            basket = await client.get_basket()
            lines = basket.get("Lines") or []
            print(f"{len(lines)} linjer, total {basket.get('TotalPrice')}, "
                  f"{basket.get('NumberOfProducts')} varer "
                  f"(timeslot {client.timeslot_utc}, zone {client.delivery_zone_id})")
            if args.raw and lines:
                print(json.dumps(lines[0], ensure_ascii=False, indent=2))
            for line in lines:
                print(f"  {line_quantity(line):>3} × {line_product_id(line):>8}  {line.get('Name', '')}")

        elif args.cmd == "add":
            before, after = await client.add_to_basket(args.product_id, args.qty)
            print(f"{args.product_id}: {before} → {after} stk.")

        elif args.cmd == "scan":
            off = await lookup_ean(session, args.ean)
            if not off:
                print("Open Food Facts kender ikke stregkoden.")
                return
            query = build_query(off)
            print(f"OFF: {off.get('brands')} – {off.get('product_name')} ({off.get('quantity')})")
            print(f"Søger: {query!r}")
            ranked = rank(off, await client.search(query))[:5]
            for i, (score, p) in enumerate(ranked, 1):
                print(f"  {i}. [{score:5.1f}] {p}")
            print("Sikkert match." if is_confident(ranked) else "Usikkert match.")
            if args.add and ranked:
                ans = input("Vælg 1-5 (Enter = spring over): ").strip()
                if ans.isdigit() and 1 <= int(ans) <= len(ranked):
                    p = ranked[int(ans) - 1][1]
                    before, after = await client.add_to_basket(p.product_id)
                    print(f"Lagt i kurv: {p.name} ({before} → {after} stk.)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except NemligError as e:
        sys.exit(f"Fejl: {e}")
