# /// script
# requires-python = ">=3.11"
# dependencies = ["rich"]
# ///
"""Yapit TTS Margin Calculator

Comprehensive profitability analysis tool with all cost components.
Run with: uv run scripts/margin_calculator.py
         uv run scripts/margin_calculator.py --plain  # TSV output for LLMs

All monetary values in the CONFIGURATION section are in their native currency
(USD for APIs, EUR for Stripe/infrastructure). Conversion happens automatically.
"""

import argparse
from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
PLAIN_MODE = False  # Set by argparse

# =============================================================================
# CONFIGURATION - Edit these values to explore scenarios
# =============================================================================

# --- Currency ---
EUR_USD_RATE = 1.08  # 1 EUR = X USD (higher = stronger EUR)

# --- VAT Rates ---
# Hungary is highest globally at 27%. US varies by state (0-10% for SaaS).
VAT_RATES = {
    "No VAT": 0.00,
    "USA (avg)": 0.05,  # ~5% average for states that tax SaaS (many exempt)
    "Luxembourg": 0.17,
    "Germany": 0.19,
    "Austria": 0.20,
    "EU Average": 0.218,
    "Hungary": 0.27,  # Highest in the world
}
DEFAULT_VAT = "Austria"  # Your typical customer

# --- Stripe Fees (with Managed Payments / MoR) ---
# Base processing (from stripe.com/pricing):
#   - EEA cards: 1.5% + €0.25
#   - UK cards: 2.5% + €0.25
#   - International cards: 3.25% + €0.25
# Managed Payments (MoR): +3.5%
# Conservative: assume international users → 3.25% + 3.5% = 6.75%, round to 7%
STRIPE_PERCENT = 0.07
STRIPE_FIXED_EUR = 0.30

# --- Gemini 3 Flash API (for AI Transform / OCR) ---
# Model: gemini-3-flash-preview
# Pricing: $0.50/M input tokens, $3.00/M output tokens
GEMINI_INPUT_PRICE_PER_M_TOKENS_USD = 0.50
GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD = 3.00
# Resolution tiers (tokens per image): LOW=280, MEDIUM=560, HIGH=1120
GEMINI_TOKENS_PER_IMAGE = {
    "low": 280,
    "medium": 560,
    "high": 1120,
}
GEMINI_RESOLUTION = "high"  # Currently using high resolution
GEMINI_PROMPT_TOKENS = 2000  # System prompt + instructions (conservative)
GEMINI_OUTPUT_TOKENS_PER_PAGE = 1500  # Page content output (conservative)

# --- Inworld TTS API ---
INWORLD_TTS1_PRICE_PER_M_CHARS_USD = 5.00  # $5.00 per million characters
INWORLD_TTS1_MAX_PRICE_PER_M_CHARS_USD = 10.00  # $10.00 per million (but 2x credits)
# Note: TTS-1-Max costs 2x but consumes 2x usage limits, so effective cost ratio = same

# --- RunPod Overflow (Kokoro serverless workers) ---
RUNPOD_COST_PER_SECOND_USD = 0.00004  # $0.00004 per second per worker
RUNPOD_MAX_WORKERS = 5  # Maximum concurrent serverless workers
RUNPOD_SELF_HOSTED_CAPACITY = 8  # Number of self-hosted (VPS) Kokoro instances
# Overflow kicks in when concurrent requests exceed self-hosted capacity
# Estimate: ~10 concurrent TTS requests per 1000 MAU at peak

# --- Fixed Infrastructure ---
VPS_MONTHLY_EUR = 25.00  # Hetzner + Backups
DOMAIN_MONTHLY_EUR = 2.10  # ~€26/year

# --- Austrian Taxes (on profit) ---
# Kleinunternehmerregelung: No VAT filing under €55k revenue ... but that's irrelevant anyways with Stripe MoR
# Income tax: Progressive rates, simplified here
AUSTRIAN_INCOME_TAX_RATE = 0.25  # ~25% effective rate (simplified)
# SVS (social insurance): ~27% on profit above ~€6k threshold
SVS_THRESHOLD_EUR = 6000  # Annual profit threshold
SVS_RATE = 0.27  # Social insurance rate

# --- Plan Definitions ---
# Format: (price_eur, interval, ocr_pages_per_month, premium_voice_chars_per_month)
PLANS = {
    "Basic Monthly": (7, "monthly", 500, 0),
    "Basic Yearly": (75, "yearly", 500, 0),
    "Plus Monthly": (20, "monthly", 1500, 1_200_000),
    "Plus Yearly": (192, "yearly", 1500, 1_200_000),
    "Max Monthly": (40, "monthly", 3000, 3_000_000),
    "Max Yearly": (240, "yearly", 3000, 3_000_000),
}

# --- Scenario Settings ---
DEFAULT_UTILIZATION = 0.75  # 75% average utilization of limits
USER_COUNTS = [10, 50, 100, 500, 1000, 5000, 10000]

# Plan distribution (what % of paying users are on each plan)
# Must sum to 1.0
PLAN_DISTRIBUTION = {
    "Basic Monthly": 0.30,
    "Basic Yearly": 0.10,
    "Plus Monthly": 0.25,
    "Plus Yearly": 0.15,
    "Max Monthly": 0.12,
    "Max Yearly": 0.08,
}

# =============================================================================
# CALCULATIONS
# =============================================================================


def usd_to_eur(usd: float) -> float:
    """Convert USD to EUR."""
    return usd / EUR_USD_RATE


def eur_to_usd(eur: float) -> float:
    """Convert EUR to USD."""
    return eur * EUR_USD_RATE


def get_gemini_cost_per_page_usd() -> float:
    """Calculate Gemini API cost per OCR page."""
    image_tokens = GEMINI_TOKENS_PER_IMAGE[GEMINI_RESOLUTION]
    input_tokens = image_tokens + GEMINI_PROMPT_TOKENS
    input_cost = (input_tokens / 1_000_000) * GEMINI_INPUT_PRICE_PER_M_TOKENS_USD
    output_cost = (GEMINI_OUTPUT_TOKENS_PER_PAGE / 1_000_000) * GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD
    return input_cost + output_cost


def get_inworld_cost_per_char_usd() -> float:
    """Get Inworld TTS cost per character."""
    return INWORLD_TTS1_PRICE_PER_M_CHARS_USD / 1_000_000


def get_runpod_max_monthly_usd() -> float:
    """Calculate max RunPod overflow cost (all workers 24/7)."""
    seconds_per_month = 60 * 60 * 24 * 30
    return RUNPOD_COST_PER_SECOND_USD * RUNPOD_MAX_WORKERS * seconds_per_month


def get_fixed_costs_eur() -> float:
    """Get monthly fixed infrastructure costs."""
    return VPS_MONTHLY_EUR + DOMAIN_MONTHLY_EUR


def get_stripe_fee(gross_eur: float) -> float:
    """Calculate Stripe fees on a transaction."""
    return gross_eur * STRIPE_PERCENT + STRIPE_FIXED_EUR


def get_revenue_after_vat(price_eur: float, vat_rate: float) -> float:
    """Calculate gross revenue after VAT extraction (VAT-inclusive pricing)."""
    return price_eur / (1 + vat_rate)


@dataclass
class PlanMetrics:
    """Calculated metrics for a single plan."""

    name: str
    price_eur: float
    interval: str
    months: int
    ocr_pages: int
    voice_chars: int

    # Costs (EUR)
    ocr_cost: float
    voice_cost: float
    total_variable_cost: float

    # Revenue at different VAT rates (EUR)
    gross_after_vat: dict[str, float]
    stripe_fee: dict[str, float]
    net_revenue: dict[str, float]

    # Profit (EUR)
    profit: dict[str, float]
    margin_percent: dict[str, float]

    # Break-even
    breakeven_utilization: dict[str, float]


def calculate_plan_metrics(
    name: str,
    price_eur: float,
    interval: str,
    ocr_pages: int,
    voice_chars: int,
    utilization: float = 1.0,
) -> PlanMetrics:
    """Calculate all metrics for a plan."""
    months = 12 if interval == "yearly" else 1

    # Variable costs at given utilization
    gemini_per_page = usd_to_eur(get_gemini_cost_per_page_usd())
    inworld_per_char = usd_to_eur(get_inworld_cost_per_char_usd())

    ocr_cost = ocr_pages * months * gemini_per_page * utilization
    voice_cost = voice_chars * months * inworld_per_char * utilization
    total_var = ocr_cost + voice_cost

    # Revenue and profit at each VAT rate
    gross_after_vat = {}
    stripe_fee = {}
    net_revenue = {}
    profit = {}
    margin_percent = {}
    breakeven_util = {}

    for vat_name, vat_rate in VAT_RATES.items():
        gross = get_revenue_after_vat(price_eur, vat_rate)
        stripe = get_stripe_fee(gross)
        net = gross - stripe
        prof = net - total_var
        margin = (prof / price_eur) * 100 if price_eur > 0 else 0

        gross_after_vat[vat_name] = gross
        stripe_fee[vat_name] = stripe
        net_revenue[vat_name] = net
        profit[vat_name] = prof
        margin_percent[vat_name] = margin

        # Break-even utilization (at 100% variable cost)
        full_var = ocr_pages * months * gemini_per_page + voice_chars * months * inworld_per_char
        if full_var > 0:
            breakeven_util[vat_name] = (net / full_var) * 100
        else:
            breakeven_util[vat_name] = float("inf")

    return PlanMetrics(
        name=name,
        price_eur=price_eur,
        interval=interval,
        months=months,
        ocr_pages=ocr_pages,
        voice_chars=voice_chars,
        ocr_cost=ocr_cost,
        voice_cost=voice_cost,
        total_variable_cost=total_var,
        gross_after_vat=gross_after_vat,
        stripe_fee=stripe_fee,
        net_revenue=net_revenue,
        profit=profit,
        margin_percent=margin_percent,
        breakeven_utilization=breakeven_util,
    )


def calculate_business_metrics(
    num_users: int,
    plan_distribution: dict[str, float],
    utilization: float,
    vat_name: str,
) -> dict:
    """Calculate overall business metrics for a given user count."""
    total_revenue = 0.0
    total_variable_costs = 0.0
    total_stripe_fees = 0.0
    total_vat_paid = 0.0

    for plan_name, fraction in plan_distribution.items():
        plan_users = num_users * fraction
        price, interval, ocr, voice = PLANS[plan_name]

        metrics = calculate_plan_metrics(plan_name, price, interval, ocr, voice, utilization)

        # Monthly-normalized values
        monthly_factor = 1 if interval == "monthly" else 1 / 12

        total_revenue += plan_users * price * monthly_factor
        total_variable_costs += plan_users * metrics.total_variable_cost * monthly_factor
        total_stripe_fees += plan_users * metrics.stripe_fee[vat_name] * monthly_factor

        gross = metrics.gross_after_vat[vat_name]
        vat_amount = price - gross
        total_vat_paid += plan_users * vat_amount * monthly_factor

    # Fixed costs
    fixed_costs = get_fixed_costs_eur()

    # RunPod overflow estimate (rough: kicks in above ~500 concurrent requests)
    # Assume peak concurrency = MAU / 100 (1% concurrent at peak)
    peak_concurrent = num_users / 100
    runpod_overflow = 0.0
    if peak_concurrent > RUNPOD_SELF_HOSTED_CAPACITY:
        overflow_workers = min(peak_concurrent - RUNPOD_SELF_HOSTED_CAPACITY, RUNPOD_MAX_WORKERS)
        # Assume overflow runs ~10% of the month during peaks
        runpod_overflow = usd_to_eur(RUNPOD_COST_PER_SECOND_USD * overflow_workers * 60 * 60 * 24 * 30 * 0.1)

    total_costs = total_variable_costs + total_stripe_fees + fixed_costs + runpod_overflow
    gross_profit = (
        total_revenue - total_vat_paid - total_stripe_fees - total_variable_costs - fixed_costs - runpod_overflow
    )

    # Austrian taxes on annual profit
    annual_profit = gross_profit * 12
    income_tax = annual_profit * AUSTRIAN_INCOME_TAX_RATE if annual_profit > 0 else 0
    svs = max(0, annual_profit - SVS_THRESHOLD_EUR) * SVS_RATE if annual_profit > SVS_THRESHOLD_EUR else 0
    net_profit_after_tax = annual_profit - income_tax - svs

    return {
        "num_users": num_users,
        "monthly_revenue": total_revenue,
        "monthly_vat": total_vat_paid,
        "monthly_stripe": total_stripe_fees,
        "monthly_variable": total_variable_costs,
        "monthly_fixed": fixed_costs,
        "monthly_runpod_overflow": runpod_overflow,
        "monthly_total_costs": total_costs,
        "monthly_gross_profit": gross_profit,
        "annual_gross_profit": annual_profit,
        "annual_income_tax": income_tax,
        "annual_svs": svs,
        "annual_net_profit": net_profit_after_tax,
        "monthly_net_profit": net_profit_after_tax / 12,
    }


# =============================================================================
# DISPLAY
# =============================================================================


def print_header():
    """Print report header."""
    if PLAIN_MODE:
        print("YAPIT TTS MARGIN CALCULATOR\n")
        return
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]YAPIT TTS MARGIN CALCULATOR[/bold cyan]\n[dim]Comprehensive profitability analysis[/dim]",
            border_style="cyan",
        )
    )


def print_unit_costs():
    """Print unit cost breakdown."""
    gemini_page = get_gemini_cost_per_page_usd()
    image_tokens = GEMINI_TOKENS_PER_IMAGE[GEMINI_RESOLUTION]
    total_input = image_tokens + GEMINI_PROMPT_TOKENS
    runpod_max = get_runpod_max_monthly_usd()

    if PLAIN_MODE:
        print("1. UNIT COSTS")
        print("Component\tUSD\tEUR\tNotes")
        print(
            f"Gemini OCR/page ({GEMINI_RESOLUTION})\t${gemini_page:.6f}\t€{usd_to_eur(gemini_page):.6f}\t{total_input} in + {GEMINI_OUTPUT_TOKENS_PER_PAGE} out tokens"
        )
        print(f"Gemini OCR/1000 pages\t${gemini_page * 1000:.2f}\t€{usd_to_eur(gemini_page * 1000):.2f}\t")
        print(
            f"Inworld TTS-1/M chars\t${INWORLD_TTS1_PRICE_PER_M_CHARS_USD:.2f}\t€{usd_to_eur(INWORLD_TTS1_PRICE_PER_M_CHARS_USD):.2f}\tTTS-1-Max $10/M but 2x credits"
        )
        print(
            f"RunPod Overflow max/mo\t${runpod_max:.2f}\t€{usd_to_eur(runpod_max):.2f}\t{RUNPOD_MAX_WORKERS} workers 24/7"
        )
        print(
            f"Fixed Infrastructure\t${eur_to_usd(get_fixed_costs_eur()):.2f}\t€{get_fixed_costs_eur():.2f}\tVPS €{VPS_MONTHLY_EUR} + Domain €{DOMAIN_MONTHLY_EUR}"
        )
        print()
        return

    console.print("\n[bold yellow]1. UNIT COSTS[/bold yellow]")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Component", style="cyan")
    table.add_column("Cost (USD)", justify="right")
    table.add_column("Cost (EUR)", justify="right")
    table.add_column("Notes")

    table.add_row(
        f"Gemini OCR (per page, {GEMINI_RESOLUTION})",
        f"${gemini_page:.6f}",
        f"€{usd_to_eur(gemini_page):.6f}",
        f"{total_input} in + {GEMINI_OUTPUT_TOKENS_PER_PAGE} out tokens",
    )
    table.add_row(
        "Gemini OCR (per 1000 pages)", f"${gemini_page * 1000:.2f}", f"€{usd_to_eur(gemini_page * 1000):.2f}", ""
    )

    table.add_row(
        "Inworld TTS-1 (per M chars)",
        f"${INWORLD_TTS1_PRICE_PER_M_CHARS_USD:.2f}",
        f"€{usd_to_eur(INWORLD_TTS1_PRICE_PER_M_CHARS_USD):.2f}",
        "TTS-1-Max is $10/M but 2× credits",
    )

    table.add_row(
        "RunPod Overflow (max/month)",
        f"${runpod_max:.2f}",
        f"€{usd_to_eur(runpod_max):.2f}",
        f"{RUNPOD_MAX_WORKERS} workers × 24/7",
    )

    table.add_row(
        "Fixed Infrastructure",
        f"${eur_to_usd(get_fixed_costs_eur()):.2f}",
        f"€{get_fixed_costs_eur():.2f}",
        f"VPS €{VPS_MONTHLY_EUR} + Domain €{DOMAIN_MONTHLY_EUR}",
    )

    console.print(table)


def print_plan_limits():
    """Print current plan limits and costs at 100% utilization."""
    if PLAIN_MODE:
        print("2. PLAN LIMITS & VARIABLE COSTS (100% util)")
        print("Plan\tPrice\tOCR/mo\tVoice/mo\tOCR Cost\tVoice Cost\tTotal Var")
        for name, (price, interval, ocr, voice) in PLANS.items():
            metrics = calculate_plan_metrics(name, price, interval, ocr, voice, 1.0)
            voice_display = f"{voice / 1_000_000:.1f}M" if voice > 0 else "0"
            period = "/yr" if interval == "yearly" else "/mo"
            print(
                f"{name}\t€{price}{period}\t{ocr}\t{voice_display}\t€{metrics.ocr_cost:.2f}\t€{metrics.voice_cost:.2f}\t€{metrics.total_variable_cost:.2f}"
            )
        print()
        return

    console.print("\n[bold yellow]2. PLAN LIMITS & VARIABLE COSTS (100% utilization)[/bold yellow]")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("OCR/mo", justify="right")
    table.add_column("Voice/mo", justify="right")
    table.add_column("OCR Cost", justify="right")
    table.add_column("Voice Cost", justify="right")
    table.add_column("Total Var", justify="right", style="bold")

    for name, (price, interval, ocr, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr, voice, 1.0)

        voice_display = f"{voice / 1_000_000:.1f}M" if voice > 0 else "0"
        period = "/yr" if interval == "yearly" else "/mo"

        table.add_row(
            name,
            f"€{price}{period}",
            str(ocr),
            voice_display,
            f"€{metrics.ocr_cost:.2f}",
            f"€{metrics.voice_cost:.2f}",
            f"€{metrics.total_variable_cost:.2f}",
        )

    console.print(table)


def print_breakeven_table():
    """Print break-even utilization by VAT rate."""
    if PLAIN_MODE:
        print("3. BREAK-EVEN UTILIZATION BY VAT RATE")
        vat_names = list(VAT_RATES.keys())
        print("Plan\t" + "\t".join(vat_names))
        for name, (price, interval, ocr, voice) in PLANS.items():
            metrics = calculate_plan_metrics(name, price, interval, ocr, voice, 1.0)
            vals = []
            for vat_name in vat_names:
                be = metrics.breakeven_utilization[vat_name]
                vals.append("∞" if be == float("inf") else f"{be:.0f}%")
            print(f"{name}\t" + "\t".join(vals))
        print()
        return

    console.print("\n[bold yellow]3. BREAK-EVEN UTILIZATION BY VAT RATE[/bold yellow]")
    console.print("[dim]What % of limits can users consume before you lose money?[/dim]\n")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")

    for vat_name in VAT_RATES.keys():
        table.add_column(vat_name, justify="center")

    for name, (price, interval, ocr, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr, voice, 1.0)

        row = [name]
        for vat_name in VAT_RATES.keys():
            be = metrics.breakeven_utilization[vat_name]
            if be == float("inf"):
                row.append("[green]∞[/green]")
            elif be >= 100:
                row.append(f"[green]{be:.0f}%[/green]")
            elif be >= 90:
                row.append(f"[yellow]{be:.0f}%[/yellow]")
            else:
                row.append(f"[red]{be:.0f}%[/red]")

        table.add_row(*row)

    console.print(table)


def print_profit_by_utilization():
    """Print profit at various utilization levels."""
    utilizations = [0.25, 0.50, 0.75, 1.00]

    if PLAIN_MODE:
        print("4. NET PROFIT BY UTILIZATION (Hungary 27% VAT)")
        print("Plan\t" + "\t".join(f"{u * 100:.0f}%" for u in utilizations))
        for name, (price, interval, ocr, voice) in PLANS.items():
            vals = []
            for util in utilizations:
                metrics = calculate_plan_metrics(name, price, interval, ocr, voice, util)
                vals.append(f"€{metrics.profit['Hungary']:.2f}")
            print(f"{name}\t" + "\t".join(vals))
        print()
        return

    console.print("\n[bold yellow]4. NET PROFIT BY UTILIZATION (Hungary 27% VAT - Worst Case)[/bold yellow]")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")

    for util in utilizations:
        table.add_column(f"{util * 100:.0f}%", justify="right")

    for name, (price, interval, ocr, voice) in PLANS.items():
        row = [name]
        for util in utilizations:
            metrics = calculate_plan_metrics(name, price, interval, ocr, voice, util)
            profit = metrics.profit["Hungary"]
            if profit >= 0:
                row.append(f"[green]€{profit:.2f}[/green]")
            else:
                row.append(f"[red]€{profit:.2f}[/red]")
        table.add_row(*row)

    console.print(table)


def print_margin_breakdown():
    """Print detailed margin breakdown."""
    if PLAIN_MODE:
        print(f"5. MARGIN BREAKDOWN ({DEFAULT_VAT} VAT, {DEFAULT_UTILIZATION * 100:.0f}% util)")
        print("Plan\tPrice\tGross\tStripe\tVar Cost\tProfit\tMargin")
        for name, (price, interval, ocr, voice) in PLANS.items():
            metrics = calculate_plan_metrics(name, price, interval, ocr, voice, DEFAULT_UTILIZATION)
            profit = metrics.profit[DEFAULT_VAT]
            margin = metrics.margin_percent[DEFAULT_VAT]
            print(
                f"{name}\t€{price:.0f}\t€{metrics.gross_after_vat[DEFAULT_VAT]:.2f}\t€{metrics.stripe_fee[DEFAULT_VAT]:.2f}\t€{metrics.total_variable_cost:.2f}\t€{profit:.2f}\t{margin:.1f}%"
            )
        print()
        return

    console.print(
        f"\n[bold yellow]5. MARGIN BREAKDOWN ({DEFAULT_VAT} VAT, {DEFAULT_UTILIZATION * 100:.0f}% utilization)[/bold yellow]"
    )

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("Gross", justify="right")
    table.add_column("Stripe", justify="right")
    table.add_column("Var Cost", justify="right")
    table.add_column("Profit", justify="right", style="bold")
    table.add_column("Margin", justify="right")

    for name, (price, interval, ocr, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr, voice, DEFAULT_UTILIZATION)

        profit = metrics.profit[DEFAULT_VAT]
        margin = metrics.margin_percent[DEFAULT_VAT]

        profit_style = "green" if profit >= 0 else "red"

        table.add_row(
            name,
            f"€{price:.0f}",
            f"€{metrics.gross_after_vat[DEFAULT_VAT]:.2f}",
            f"€{metrics.stripe_fee[DEFAULT_VAT]:.2f}",
            f"€{metrics.total_variable_cost:.2f}",
            f"[{profit_style}]€{profit:.2f}[/{profit_style}]",
            f"{margin:.1f}%",
        )

    console.print(table)


def print_business_scaling():
    """Print business metrics at different user counts."""
    if PLAIN_MODE:
        print(f"6. BUSINESS SCALING ({DEFAULT_VAT} VAT, {DEFAULT_UTILIZATION * 100:.0f}% util)")
        print("Users\tRevenue\tVAT\tStripe\tVariable\tFixed\tRunPod+\tGross Profit\tNet/yr")
        for num_users in USER_COUNTS:
            biz = calculate_business_metrics(num_users, PLAN_DISTRIBUTION, DEFAULT_UTILIZATION, DEFAULT_VAT)
            print(
                f"{num_users}\t€{biz['monthly_revenue']:.0f}\t€{biz['monthly_vat']:.0f}\t€{biz['monthly_stripe']:.0f}\t€{biz['monthly_variable']:.0f}\t€{biz['monthly_fixed']:.0f}\t€{biz['monthly_runpod_overflow']:.0f}\t€{biz['monthly_gross_profit']:.0f}\t€{biz['annual_net_profit']:.0f}"
            )
        print()
        return

    console.print(
        f"\n[bold yellow]6. BUSINESS SCALING ({DEFAULT_VAT} VAT, {DEFAULT_UTILIZATION * 100:.0f}% util)[/bold yellow]"
    )
    console.print("[dim]Monthly figures with plan distribution applied[/dim]\n")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Users", justify="right", style="cyan")
    table.add_column("Revenue", justify="right")
    table.add_column("VAT", justify="right")
    table.add_column("Stripe", justify="right")
    table.add_column("Variable", justify="right")
    table.add_column("Fixed", justify="right")
    table.add_column("RunPod+", justify="right")
    table.add_column("Gross Profit", justify="right", style="bold")
    table.add_column("Net/yr*", justify="right")

    for num_users in USER_COUNTS:
        biz = calculate_business_metrics(num_users, PLAN_DISTRIBUTION, DEFAULT_UTILIZATION, DEFAULT_VAT)

        profit_style = "green" if biz["monthly_gross_profit"] >= 0 else "red"

        table.add_row(
            f"{num_users:,}",
            f"€{biz['monthly_revenue']:,.0f}",
            f"€{biz['monthly_vat']:,.0f}",
            f"€{biz['monthly_stripe']:,.0f}",
            f"€{biz['monthly_variable']:,.0f}",
            f"€{biz['monthly_fixed']:,.0f}",
            f"€{biz['monthly_runpod_overflow']:,.0f}",
            f"[{profit_style}]€{biz['monthly_gross_profit']:,.0f}[/{profit_style}]",
            f"€{biz['annual_net_profit']:,.0f}",
        )

    console.print(table)
    console.print("[dim]*Net after Austrian income tax (~25%) and SVS (~27% above €6k)[/dim]")


def print_vat_comparison():
    """Print profit comparison across VAT rates."""
    if PLAIN_MODE:
        print(f"7. VAT IMPACT COMPARISON ({DEFAULT_UTILIZATION * 100:.0f}% util)")
        print("Plan\tNo VAT\tGermany 19%\tAustria 20%\tHungary 27%\tΔ (HU vs 0)")
        for name, (price, interval, ocr, voice) in PLANS.items():
            metrics = calculate_plan_metrics(name, price, interval, ocr, voice, DEFAULT_UTILIZATION)
            no_vat = metrics.profit["No VAT"]
            hungary = metrics.profit["Hungary"]
            delta = hungary - no_vat
            print(
                f"{name}\t€{no_vat:.2f}\t€{metrics.profit['Germany']:.2f}\t€{metrics.profit['Austria']:.2f}\t€{hungary:.2f}\t€{delta:.2f}"
            )
        print()
        return

    console.print(
        f"\n[bold yellow]7. VAT IMPACT COMPARISON ({DEFAULT_UTILIZATION * 100:.0f}% utilization)[/bold yellow]"
    )

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")
    table.add_column("No VAT", justify="right")
    table.add_column("Germany 19%", justify="right")
    table.add_column("Austria 20%", justify="right")
    table.add_column("Hungary 27%", justify="right")
    table.add_column("Δ (HU vs 0)", justify="right")

    for name, (price, interval, ocr, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr, voice, DEFAULT_UTILIZATION)

        no_vat = metrics.profit["No VAT"]
        hungary = metrics.profit["Hungary"]
        delta = hungary - no_vat

        def fmt(v):
            return f"[green]€{v:.2f}[/green]" if v >= 0 else f"[red]€{v:.2f}[/red]"

        table.add_row(
            name,
            fmt(no_vat),
            fmt(metrics.profit["Germany"]),
            fmt(metrics.profit["Austria"]),
            fmt(hungary),
            f"[red]€{delta:.2f}[/red]",
        )

    console.print(table)


def print_recommendations():
    """Print analysis and recommendations."""
    problems = []
    for name, (price, interval, ocr, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr, voice, 1.0)
        if metrics.breakeven_utilization["Hungary"] < 100:
            problems.append((name, metrics.breakeven_utilization["Hungary"]))

    if PLAIN_MODE:
        print("8. SUMMARY")
        if problems:
            print("Plans at risk (break-even < 100% at Hungary VAT):")
            for name, be in problems:
                print(f"  {name}: {be:.0f}% break-even")
        else:
            print("All plans profitable at 100% util (Hungary VAT)")
        print()
        print("Yearly Discounts")
        print("Tier\tMonthly×12\tYearly\tDiscount")
        for tier in ["Basic", "Plus", "Max"]:
            monthly_price = PLANS[f"{tier} Monthly"][0]
            yearly_price = PLANS[f"{tier} Yearly"][0]
            discount = 1 - (yearly_price / (monthly_price * 12))
            print(f"{tier}\t€{monthly_price * 12}\t€{yearly_price}\t{discount * 100:.0f}%")
        print()
        return

    console.print("\n[bold yellow]8. SUMMARY[/bold yellow]")

    if problems:
        console.print("\n[bold red]⚠️  Plans at risk (break-even < 100% at Hungary VAT):[/bold red]")
        for name, be in problems:
            console.print(f"   • {name}: {be:.0f}% break-even")
    else:
        console.print("\n[bold green]✅ All plans are profitable even at 100% utilization (Hungary VAT)[/bold green]")

    console.print("\n[bold]Yearly Discounts:[/bold]")
    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Tier")
    table.add_column("Monthly×12")
    table.add_column("Yearly")
    table.add_column("Discount")

    for tier in ["Basic", "Plus", "Max"]:
        monthly_price = PLANS[f"{tier} Monthly"][0]
        yearly_price = PLANS[f"{tier} Yearly"][0]
        discount = 1 - (yearly_price / (monthly_price * 12))
        table.add_row(
            tier,
            f"€{monthly_price * 12}",
            f"€{yearly_price}",
            f"{discount * 100:.0f}%",
        )

    console.print(table)


def print_config_summary():
    """Print current configuration."""
    if PLAIN_MODE:
        print("CONFIG")
        print(f"Currency: 1 EUR = {EUR_USD_RATE} USD")
        print(f"Default VAT: {DEFAULT_VAT} ({VAT_RATES[DEFAULT_VAT] * 100:.0f}%)")
        print(f"Default Utilization: {DEFAULT_UTILIZATION * 100:.0f}%")
        print(f"Stripe: {STRIPE_PERCENT * 100:.0f}% + €{STRIPE_FIXED_EUR}")
        print(
            f"Gemini 3 Flash: ${GEMINI_INPUT_PRICE_PER_M_TOKENS_USD}/M in, ${GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD}/M out ({GEMINI_RESOLUTION} res)"
        )
        print(f"Inworld TTS-1: ${INWORLD_TTS1_PRICE_PER_M_CHARS_USD}/M chars")
        print(f"RunPod: ${RUNPOD_COST_PER_SECOND_USD}/s × {RUNPOD_MAX_WORKERS} workers max")
        print(f"Fixed: €{get_fixed_costs_eur()}/month")
        print(
            f"Austrian Tax: ~{AUSTRIAN_INCOME_TAX_RATE * 100:.0f}% income + {SVS_RATE * 100:.0f}% SVS above €{SVS_THRESHOLD_EUR}"
        )
        print()
        return

    console.print("\n[bold yellow]CURRENT CONFIGURATION[/bold yellow]")

    config_text = f"""
[cyan]Currency:[/cyan] 1 EUR = {EUR_USD_RATE} USD
[cyan]Default VAT:[/cyan] {DEFAULT_VAT} ({VAT_RATES[DEFAULT_VAT] * 100:.0f}%)
[cyan]Default Utilization:[/cyan] {DEFAULT_UTILIZATION * 100:.0f}%
[cyan]Stripe Fees:[/cyan] {STRIPE_PERCENT * 100:.0f}% + €{STRIPE_FIXED_EUR}
[cyan]Gemini 3 Flash:[/cyan] ${GEMINI_INPUT_PRICE_PER_M_TOKENS_USD}/M in, ${GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD}/M out ({GEMINI_RESOLUTION} res)
[cyan]Inworld TTS-1:[/cyan] ${INWORLD_TTS1_PRICE_PER_M_CHARS_USD}/M chars
[cyan]RunPod:[/cyan] ${RUNPOD_COST_PER_SECOND_USD}/s × {RUNPOD_MAX_WORKERS} workers max
[cyan]Fixed:[/cyan] €{get_fixed_costs_eur()}/month
[cyan]Austrian Tax:[/cyan] ~{AUSTRIAN_INCOME_TAX_RATE * 100:.0f}% income + {SVS_RATE * 100:.0f}% SVS above €{SVS_THRESHOLD_EUR}
"""
    console.print(Panel(config_text.strip(), title="Settings", border_style="dim"))


# =============================================================================
# MAIN
# =============================================================================


def main():
    global PLAIN_MODE
    parser = argparse.ArgumentParser(description="Yapit TTS Margin Calculator")
    parser.add_argument("--plain", action="store_true", help="TSV output for LLMs")
    args = parser.parse_args()
    PLAIN_MODE = args.plain

    print_header()
    print_config_summary()
    print_unit_costs()
    print_plan_limits()
    print_breakeven_table()
    print_profit_by_utilization()
    print_margin_breakdown()
    print_vat_comparison()
    print_business_scaling()
    print_recommendations()

    if not PLAIN_MODE:
        console.print("\n[dim]Edit the CONFIGURATION section at the top of this script to explore scenarios.[/dim]\n")


if __name__ == "__main__":
    main()
