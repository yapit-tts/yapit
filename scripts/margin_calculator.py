# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich"]
# ///
"""Yapit margin calculator — post-Inworld plan pricing.

Voice plan: Kokoro TTS only (self-hosted, zero variable API cost).
Basic plan: Kokoro TTS + Gemini AI transform.

Main question: how low can the Voice plan go?

Examples::

    uv run scripts/margin_calculator.py
    uv run scripts/margin_calculator.py --voice-price 2 --vat hungary
    uv run scripts/margin_calculator.py --voice-price 5 --basic-price 12
    uv run scripts/margin_calculator.py --plain
"""

from dataclasses import dataclass
from typing import Literal

import tyro
from rich import box
from rich.console import Console
from rich.table import Table

# ── Constants ──────────────────────────────────────────────────────────────────

VAT_RATES: dict[str, float] = {
    "none": 0.00,
    "usa": 0.05,
    "luxembourg": 0.17,
    "germany": 0.19,
    "austria": 0.20,
    "eu_avg": 0.218,
    "hungary": 0.27,
}

# Stripe MoR: ~3.25% processing + 3.5% managed payments ≈ 7%
STRIPE_PERCENT = 0.07
STRIPE_FIXED_EUR = 0.30

# Gemini 3 Flash (AI Transform / OCR)
# Token equivalents: input + output × multiplier (output costs 6× input)
GEMINI_INPUT_PRICE_PER_M_USD = 0.50
GEMINI_OUTPUT_PRICE_PER_M_USD = 3.00
GEMINI_INPUT_TOKENS_PER_PAGE = 4300  # 3100 prompt + 1200 image
GEMINI_OUTPUT_TOKENS_PER_PAGE = 1100  # conservative
OUTPUT_MULTIPLIER = int(GEMINI_OUTPUT_PRICE_PER_M_USD / GEMINI_INPUT_PRICE_PER_M_USD)
TOKENS_PER_PAGE = GEMINI_INPUT_TOKENS_PER_PAGE + GEMINI_OUTPUT_TOKENS_PER_PAGE * OUTPUT_MULTIPLIER

BASIC_OCR_TOKENS = 5_000_000  # monthly token-equivalent budget

# Fixed infrastructure
VPS_MONTHLY_EUR = 25.00
DOMAIN_MONTHLY_EUR = 2.10
FIXED_MONTHLY = VPS_MONTHLY_EUR + DOMAIN_MONTHLY_EUR

# Austrian taxes (on annual profit)
INCOME_TAX_RATE = 0.25
SVS_THRESHOLD_EUR = 6_000
SVS_RATE = 0.27


# ── CLI ────────────────────────────────────────────────────────────────────────


@dataclass
class Args:
    voice_price: float = 3.0
    """Voice plan monthly price in EUR."""

    basic_price: float = 10.0
    """Basic plan monthly price in EUR."""

    yearly_discount: float = 0.25
    """Yearly discount (0.25 = 25% off monthly×12)."""

    utilization: float = 0.75
    """Average utilization of Basic plan OCR limits (0.0–1.0)."""

    vat: Literal["none", "usa", "luxembourg", "germany", "austria", "eu_avg", "hungary"] = "austria"
    """VAT jurisdiction for calculations."""

    eur_usd: float = 1.08
    """EUR/USD exchange rate (1 EUR = X USD)."""

    voice_share: float = 0.50
    """Share of paying users on Voice vs Basic (for scaling)."""

    plain: bool = False
    """Terse TSV output for piping."""


# ── Calculations ───────────────────────────────────────────────────────────────


def usd_to_eur(usd: float, rate: float) -> float:
    return usd / rate


def stripe_fee(gross: float) -> float:
    """Stripe fee on a single transaction (gross = price after VAT extraction)."""
    return gross * STRIPE_PERCENT + STRIPE_FIXED_EUR


def net_revenue(price: float, vat_rate: float) -> tuple[float, float, float, float]:
    """Returns (vat_amount, gross, stripe_fee, net)."""
    gross = price / (1 + vat_rate)
    vat = price - gross
    fee = stripe_fee(gross)
    return vat, gross, fee, gross - fee


def basic_api_cost(utilization: float, eur_usd: float) -> float:
    """Monthly Gemini OCR cost for one Basic user at given utilization."""
    cost_per_token_eur = usd_to_eur(GEMINI_INPUT_PRICE_PER_M_USD / 1_000_000, eur_usd)
    return BASIC_OCR_TOKENS * cost_per_token_eur * utilization


def annual_net(monthly_profit: float) -> float:
    """Annual take-home after Austrian income tax + SVS."""
    annual = monthly_profit * 12
    if annual <= 0:
        return annual
    tax = annual * INCOME_TAX_RATE
    svs = max(0, annual - SVS_THRESHOLD_EUR) * SVS_RATE
    return annual - tax - svs


# ── Rich output ────────────────────────────────────────────────────────────────


def run_rich(args: Args) -> None:
    vat_rate = VAT_RATES[args.vat]
    c = Console()

    c.print()
    c.print("[bold cyan]YAPIT MARGIN CALCULATOR[/bold cyan]")
    c.print(
        f"[dim]VAT: {args.vat} ({vat_rate:.0%})  "
        f"Util: {args.utilization:.0%}  "
        f"EUR/USD: {args.eur_usd}  "
        f"Fixed: €{FIXED_MONTHLY:.0f}/mo  "
        f"Stripe: {STRIPE_PERCENT:.0%} + €{STRIPE_FIXED_EUR:.2f}[/dim]"
    )

    # ── 1. Plan margins ──

    voice_yr = args.voice_price * 12 * (1 - args.yearly_discount)
    basic_yr = args.basic_price * 12 * (1 - args.yearly_discount)
    api = basic_api_cost(args.utilization, args.eur_usd)
    pages = int(BASIC_OCR_TOKENS / TOKENS_PER_PAGE)

    plans = [
        ("Voice /mo", args.voice_price, 1, 0.0),
        ("Voice /yr", voice_yr, 12, 0.0),
        ("Basic /mo", args.basic_price, 1, api),
        ("Basic /yr", basic_yr, 12, api * 12),
    ]

    t = Table(title="Plan Margins", box=box.ROUNDED, header_style="bold")
    for col, kw in [
        ("Plan", {"style": "cyan"}),
        ("Price", {"justify": "right"}),
        ("VAT", {"justify": "right"}),
        ("Stripe", {"justify": "right"}),
        ("API", {"justify": "right"}),
        ("Profit", {"justify": "right", "style": "bold"}),
        ("Margin", {"justify": "right"}),
        ("Profit/mo", {"justify": "right"}),
    ]:
        t.add_column(col, **kw)

    for label, price, months, var in plans:
        vat_amt, _, fee, n = net_revenue(price, vat_rate)
        profit = n - var
        margin = profit / price * 100
        monthly = profit / months
        ps = "green" if profit >= 0 else "red"
        t.add_row(
            label,
            f"€{price:.2f}",
            f"€{vat_amt:.2f}",
            f"€{fee:.2f}",
            f"€{var:.2f}" if var > 0 else "—",
            f"[{ps}]€{profit:.2f}[/{ps}]",
            f"{margin:.1f}%",
            f"€{monthly:.2f}",
        )

    c.print(t)
    c.print(
        f"[dim]Basic: ~{pages} pages/mo ({BASIC_OCR_TOKENS / 1e6:.0f}M token equiv) "
        f"at {args.utilization:.0%} util → €{api:.2f}/mo Gemini cost[/dim]"
    )

    # Yearly vs monthly comparison
    _, _, _, voice_net_mo = net_revenue(args.voice_price, vat_rate)
    _, _, _, voice_net_yr = net_revenue(voice_yr, vat_rate)
    stripe_savings = stripe_fee(args.voice_price / (1 + vat_rate)) * 12 - stripe_fee(voice_yr / (1 + vat_rate))
    c.print(
        f"[dim]Yearly Stripe savings: €{stripe_savings:.2f}/yr per user "
        f"(but yearly discount costs €{voice_net_mo * 12 - voice_net_yr:.2f}/yr in revenue)[/dim]"
    )

    # ── 2. Voice price sweep ──

    prices = sorted({1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, args.voice_price})

    t2 = Table(title="\nVoice Plan Price Sweep", box=box.ROUNDED, header_style="bold")
    for col, kw in [
        ("€/mo", {"justify": "right", "style": "cyan"}),
        ("Net/mo", {"justify": "right"}),
        ("Margin", {"justify": "right"}),
        ("€/yr", {"justify": "right"}),
        ("Net/yr", {"justify": "right"}),
        ("Yr Margin", {"justify": "right"}),
        ("Stripe %", {"justify": "right"}),
        ("BE Users", {"justify": "right"}),
    ]:
        t2.add_column(col, **kw)

    for p in prices:
        _, _, _, n_mo = net_revenue(p, vat_rate)
        yr = p * 12 * (1 - args.yearly_discount)
        _, _, _, n_yr = net_revenue(yr, vat_rate)

        gross_mo = p / (1 + vat_rate)
        stripe_pct = stripe_fee(gross_mo) / gross_mo * 100
        be = FIXED_MONTHLY / n_mo if n_mo > 0 else float("inf")

        current = p == args.voice_price
        style = "bold" if current else ""
        mark = " ←" if current else ""
        ps = "green" if n_mo >= 0 else "red"

        t2.add_row(
            f"€{p:.2f}{mark}",
            f"[{ps}]€{n_mo:.2f}[/{ps}]",
            f"{n_mo / p * 100:.1f}%",
            f"€{yr:.0f}",
            f"€{n_yr:.2f}",
            f"{n_yr / yr * 100:.1f}%",
            f"{stripe_pct:.1f}%",
            f"{be:.0f}" if be < 10_000 else "∞",
            style=style,
        )

    c.print(t2)
    c.print(
        f"[dim]BE Users = monthly Voice subscribers needed to cover "
        f"€{FIXED_MONTHLY:.0f}/mo fixed infra. "
        f"Stripe % = share of gross taken by Stripe (fixed fee dominates at low prices).[/dim]"
    )

    # ── 3. Money flow at selected price ──

    vat_v, gross_v, fee_v, net_v = net_revenue(args.voice_price, vat_rate)
    c.print(f"\n[bold]€{args.voice_price:.2f}/mo Voice — where the money goes:[/bold]")
    c.print(f"  VAT ({args.vat}):  €{vat_v:.2f}  ({vat_v / args.voice_price * 100:.0f}%)")
    c.print(f"  Stripe:       €{fee_v:.2f}  ({fee_v / args.voice_price * 100:.0f}%)")
    c.print(f"  [green]You keep:     €{net_v:.2f}  ({net_v / args.voice_price * 100:.0f}%)[/green]")

    # ── 4. VAT comparison ──

    best_net = max(net_revenue(args.voice_price, vr)[3] for vr in VAT_RATES.values())

    t3 = Table(
        title=f"\n€{args.voice_price:.2f} Voice Plan Across VAT Jurisdictions",
        box=box.ROUNDED,
        header_style="bold",
    )
    for col, kw in [
        ("Jurisdiction", {"style": "cyan"}),
        ("VAT %", {"justify": "right"}),
        ("Net/mo", {"justify": "right"}),
        ("Margin", {"justify": "right"}),
        ("vs best", {"justify": "right"}),
    ]:
        t3.add_column(col, **kw)

    for name, vr in VAT_RATES.items():
        _, _, _, n = net_revenue(args.voice_price, vr)
        delta = n - best_net
        current = name == args.vat
        style = "bold" if current else ""
        mark = " ←" if current else ""
        ps = "green" if n >= 0 else "red"

        t3.add_row(
            f"{name}{mark}",
            f"{vr:.0%}",
            f"[{ps}]€{n:.2f}[/{ps}]",
            f"{n / args.voice_price * 100:.1f}%",
            f"€{delta:.2f}" if delta < -0.005 else "—",
            style=style,
        )

    c.print(t3)

    # ── 5. Scaling ──

    vf = args.voice_share
    _, _, _, v_net = net_revenue(args.voice_price, vat_rate)
    _, _, _, b_net = net_revenue(args.basic_price, vat_rate)

    t4 = Table(
        title=f"\nScaling ({vf:.0%} Voice / {1 - vf:.0%} Basic, monthly billing)",
        box=box.ROUNDED,
        header_style="bold",
    )
    for col, kw in [
        ("Users", {"justify": "right", "style": "cyan"}),
        ("Rev/mo", {"justify": "right"}),
        ("Costs/mo", {"justify": "right"}),
        ("Profit/mo", {"justify": "right", "style": "bold"}),
        ("Net/yr*", {"justify": "right"}),
    ]:
        t4.add_column(col, **kw)

    for n in [5, 10, 25, 50, 100, 250, 500, 1000]:
        nv, nb = n * vf, n * (1 - vf)
        rev = nv * args.voice_price + nb * args.basic_price
        total_net = nv * v_net + nb * b_net
        api_cost = nb * api
        profit = total_net - api_cost - FIXED_MONTHLY
        net_yr = annual_net(profit)

        ps = "green" if profit >= 0 else "red"
        t4.add_row(
            str(n),
            f"€{rev:.0f}",
            f"€{api_cost + FIXED_MONTHLY:.0f}",
            f"[{ps}]€{profit:.0f}[/{ps}]",
            f"€{net_yr:,.0f}",
        )

    c.print(t4)
    c.print("[dim]*After Austrian income tax (~25%) + SVS (~27% above €6k)[/dim]")
    c.print()


# ── Plain output ───────────────────────────────────────────────────────────────


def run_plain(args: Args) -> None:
    vat_rate = VAT_RATES[args.vat]
    api = basic_api_cost(args.utilization, args.eur_usd)

    print(
        f"# vat={args.vat} ({vat_rate:.0%}) "
        f"util={args.utilization:.0%} "
        f"eur_usd={args.eur_usd} "
        f"fixed=€{FIXED_MONTHLY:.0f}/mo"
    )

    # Plan margins
    voice_yr = args.voice_price * 12 * (1 - args.yearly_discount)
    basic_yr = args.basic_price * 12 * (1 - args.yearly_discount)

    print("\n# plan_margins")
    print("plan\tprice\tvat\tstripe\tapi\tprofit\tmargin\tprofit_mo")
    for label, price, months, var in [
        ("voice_mo", args.voice_price, 1, 0.0),
        ("voice_yr", voice_yr, 12, 0.0),
        ("basic_mo", args.basic_price, 1, api),
        ("basic_yr", basic_yr, 12, api * 12),
    ]:
        vat_amt, _, fee, n = net_revenue(price, vat_rate)
        profit = n - var
        print(
            f"{label}\t{price:.2f}\t{vat_amt:.2f}\t{fee:.2f}\t{var:.2f}\t"
            f"{profit:.2f}\t{profit / price * 100:.1f}%\t{profit / months:.2f}"
        )

    # Voice sweep
    print("\n# voice_sweep")
    print("price_mo\tnet_mo\tmargin\tprice_yr\tnet_yr\tyr_margin\tstripe_pct\tbe_users")
    for p in [1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10]:
        _, _, _, n_mo = net_revenue(p, vat_rate)
        yr = p * 12 * (1 - args.yearly_discount)
        _, _, _, n_yr = net_revenue(yr, vat_rate)
        gross = p / (1 + vat_rate)
        s_pct = stripe_fee(gross) / gross * 100
        be = FIXED_MONTHLY / n_mo if n_mo > 0 else -1
        print(
            f"{p:.2f}\t{n_mo:.2f}\t{n_mo / p * 100:.1f}%\t{yr:.0f}\t{n_yr:.2f}\t"
            f"{n_yr / yr * 100:.1f}%\t{s_pct:.1f}%\t{be:.0f}"
        )

    # Scaling
    vf = args.voice_share
    _, _, _, v_net = net_revenue(args.voice_price, vat_rate)
    _, _, _, b_net = net_revenue(args.basic_price, vat_rate)

    print(f"\n# scaling ({vf:.0%} voice / {1 - vf:.0%} basic)")
    print("users\trev_mo\tcosts_mo\tprofit_mo\tnet_yr")
    for n in [5, 10, 25, 50, 100, 250, 500, 1000]:
        nv, nb = n * vf, n * (1 - vf)
        rev = nv * args.voice_price + nb * args.basic_price
        total_net = nv * v_net + nb * b_net
        api_cost = nb * api
        profit = total_net - api_cost - FIXED_MONTHLY
        net_yr = annual_net(profit)
        print(f"{n}\t{rev:.0f}\t{api_cost + FIXED_MONTHLY:.0f}\t{profit:.0f}\t{net_yr:.0f}")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    args = tyro.cli(Args, description=__doc__)
    if args.plain:
        run_plain(args)
    else:
        run_rich(args)


if __name__ == "__main__":
    main()
