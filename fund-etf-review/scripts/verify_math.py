#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_math.py -- fund-etf-review skill numeric verification.

Pure stdlib, ASCII-only output (safe on GBK consoles).

Subcommands:
  fee-drag <fee_high> <fee_low> [--years N] [--returns R1,R2,...]
      Terminal-value gap between two annual fee levels, swept across
      return assumptions. Prints gap% per return and the direction check.
  ac-breakeven <sub_fee> <service_fee_per_year> [--fees LIST]
      A/C share class breakeven holding period for each one-off
      subscription fee level (fee / annual service fee).
  all
      Run the canonical suite from the review checklist and print
      reference values to compare against document claims.
"""
import argparse
import sys


def cmd_fee_drag(args):
    years = args.years
    print("Fee drag: high=%.4f  low=%.4f  years=%d" % (args.fee_high, args.fee_low, years))
    print("%-12s %-22s %-22s %s" % ("return", "endvalue(high fee)", "endvalue(low fee)", "gap%"))
    gaps = []
    for r in args.returns:
        vh = (1.0 + r - args.fee_high) ** years
        vl = (1.0 + r - args.fee_low) ** years
        gap = (vl / vh - 1.0) * 100.0
        gaps.append((r, gap))
        print("%-12.2f %-22.4f %-22.4f %+.2f%%" % (r, vh, vl, gap))
    # direction check: lower return assumption -> larger gap
    mono = all(gaps[i][1] >= gaps[i + 1][1] - 1e-9 for i in range(len(gaps) - 1))
    lo, hi = min(g for _, g in gaps), max(g for _, g in gaps)
    print("range: %.1f%% ~ %.1f%%" % (lo, hi))
    print("direction 'lower return -> larger gap': %s" % ("OK" if mono else "VIOLATED"))


def cmd_ac_breakeven(args):
    print("A/C breakeven (years) = oneoff_sub_fee / annual_service_fee")
    print("service fee = %.4f/yr" % args.service_fee)
    for f in args.fees:
        print("  sub fee %.4f -> %.2f years" % (f, f / args.service_fee))


def cmd_all(_):
    print("=== canonical reference values (checklist.md) ===")
    # fee drag 1.5% vs 0.2%, 20y
    ref = []
    for r in (0.0, 0.08):
        vh = (1.0 + r - 0.015) ** 20
        vl = (1.0 + r - 0.002) ** 20
        ref.append((vl / vh - 1.0) * 100.0)
    print("fee-drag 0.015 vs 0.002, 20y: %.1f%% ~ %.1f%% (claim 'about 25%%' is LOW; use 27%%~30%%)"
          % (min(ref), max(ref)))
    # ac breakeven
    print("ac-breakeven 0.10%%/0.20%% = %.2f y ; 0.15%%/0.20%% = %.2f y" % (0.0010 / 0.0020, 0.0015 / 0.0020))
    print("bank channel: 1.5%% vs 0.15%% = %.1fx (must match 'save 90%%' wording)" % (0.015 / 0.0015))
    print("mainstream broad-index fee: 0.15 pct mgmt + 0.05 pct custody = 0.20 pct/yr")


def main():
    p = argparse.ArgumentParser(description="fund-etf-review numeric verification")
    sub = p.add_subparsers(dest="cmd", required=True)

    fd = sub.add_parser("fee-drag")
    fd.add_argument("fee_high", type=float)
    fd.add_argument("fee_low", type=float)
    fd.add_argument("--years", type=int, default=20)
    fd.add_argument("--returns", type=str, default="0,0.04,0.08")
    fd.set_defaults(func=cmd_fee_drag)

    ab = sub.add_parser("ac-breakeven")
    ab.add_argument("sub_fee", type=float)
    ab.add_argument("service_fee", type=float)
    ab.add_argument("--fees", type=str, default=None,
                    help="comma list of one-off sub fee levels (overrides sub_fee)")
    ab.set_defaults(func=None)

    sub.add_parser("all")

    args = p.parse_args()
    if args.cmd == "fee-drag":
        args.returns = [float(x) for x in args.returns.split(",") if x.strip()]
        args.func(args)
    elif args.cmd == "ac-breakeven":
        fees = [args.sub_fee] if not args.fees else [float(x) for x in args.fees.split(",") if x.strip()]
        args.fees = fees
        cmd_ac_breakeven(args)
    else:
        cmd_all(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
