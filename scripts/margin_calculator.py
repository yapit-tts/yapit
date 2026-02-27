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
# Pricing: $0.50/M input tokens, $3.00/M output tokens (thinking = output rate)
#
# Measured averages (N=208 pages):
#   Input: 2005 tokens/page (std ±226)
#   Output: 890 tokens/page (std ±702, high variance for math/tables)
# Using conservative estimates to not overpromise page counts:
GEMINI_INPUT_PRICE_PER_M_TOKENS_USD = 0.50
GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD = 3.00
GEMINI_INPUT_TOKENS = 4300  # 3100 prompt + 1200 image
GEMINI_OUTPUT_TOKENS = 1100  # conservative
GEMINI_THINKING_TOKENS = 0  # Thinking tokens (set 0 for minimal thinking mode)
#
# Token-based billing model:
# - Output tokens cost 6x input tokens, so we use "token equivalents"
# - token_equiv = input_tokens + (output_tokens * OUTPUT_MULTIPLIER)
# - Plans define limits in token equivalents, displayed as "~pages" to users
OUTPUT_TOKEN_MULTIPLIER = int(GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD / GEMINI_INPUT_PRICE_PER_M_TOKENS_USD)
#
# Average token equivalents per page (for display conversion):
# input=2500, output=1000 → 2500 + (1000 * 6) = 8500 token equiv/page
TOKENS_PER_PAGE = GEMINI_INPUT_TOKENS + (GEMINI_OUTPUT_TOKENS + GEMINI_THINKING_TOKENS) * OUTPUT_TOKEN_MULTIPLIER

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

# --- R2 Object Storage (for extracted images) ---
# Pricing: https://developers.cloudflare.com/r2/pricing/
R2_FREE_STORAGE_GB = 10
R2_COST_PER_GB_MONTH_USD = 0.015
R2_FREE_CLASS_A_OPS = 1_000_000  # writes (PUT, POST, LIST)
R2_COST_PER_M_CLASS_A_USD = 4.50
R2_FREE_CLASS_B_OPS = 10_000_000  # reads (GET)
R2_COST_PER_M_CLASS_B_USD = 0.36
# TODO update with prod data:
# Ratio of image storage to DB text storage (TODO: update with prod data)
# Initial estimate: 11-page paper = 92KB DB, 1.4MB images → 15:1 for image-heavy docs
# Adjusted for ~30% of docs using Gemini extraction: ~5:1 effective ratio
R2_IMAGES_PER_MB_DB_STORAGE = 5  # MB of images per MB of DB text
# Estimated image views per month (for read ops calculation)
# Low because: users rarely revisit docs, browser caching reduces requests
R2_IMAGE_VIEWS_PER_IMAGE_MONTH = 5

# --- Document Storage Limits (DB text only, images on R2) ---
# Limits check LENGTH(original_text) + LENGTH(structured_content) — uncompressed char count.
# Actual on-disk usage is LESS because TOAST compresses structured_content ~4.8x,
# which dominates total DB storage.
# Measured: 0.5x on prod (353 docs, 20MB total DB, Feb 2026).
# Conservative: 0.7x — allows for docs that compress less well, index growth, etc.
STORAGE_LIMIT_GUEST_MB = 10
STORAGE_LIMIT_FREE_MB = 50
STORAGE_LIMIT_PAID_MB = 500
STORAGE_ACTUAL_MULTIPLIER = 0.7

# --- Fixed Infrastructure ---
VPS_MONTHLY_EUR = 25.00  # Hetzner + Backups
DOMAIN_MONTHLY_EUR = 2.10  # ~€26/year

# --- VPS Capacity (640GB VPS with images on R2) ---
# Conservative: 350GB after OS, Docker, caches, logs, TimescaleDB, headroom
VPS_AVAILABLE_DB_STORAGE_GB = 350

# --- Austrian Taxes (on profit) ---
# Kleinunternehmerregelung: No VAT filing under €55k revenue ... but that's irrelevant anyways with Stripe MoR
# Income tax: Progressive rates, simplified here
AUSTRIAN_INCOME_TAX_RATE = 0.25  # ~25% effective rate (simplified)
# SVS (social insurance): ~27% on profit above ~€6k threshold
SVS_THRESHOLD_EUR = 6000  # Annual profit threshold
SVS_RATE = 0.27  # Social insurance rate
SVS_UNFALL_MONTHLY = 13  # even below threshold... # TODO


# --- Plan Definitions ---
# Format: (price_eur, interval, ocr_token_equiv_per_month, premium_voice_chars_per_month)
# Token equivalents = input_tokens + (output_tokens * 6)
# Use TOKENS_PER_PAGE to convert to/from approximate pages
PLANS = {
    # Uniform 25% yearly discount, round token/char numbers
    "Basic Monthly": (10, "monthly", 5_000_000, 0),
    "Basic Yearly": (90, "yearly", 5_000_000, 0),  # 25% discount
    "Plus Monthly": (20, "monthly", 10_000_000, 1_000_000),
    "Plus Yearly": (180, "yearly", 10_000_000, 1_000_000),  # 25% discount
    "Max Monthly": (40, "monthly", 15_000_000, 3_000_000),
    "Max Yearly": (360, "yearly", 15_000_000, 3_000_000),  # 25% discount
}

# Voice character to hours conversion
CHARS_PER_SECOND = 14  # see script in experiments/
SECONDS_PER_HOUR = 3600

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


def get_gemini_cost_per_token_equiv_usd() -> float:
    """Calculate Gemini API cost per token equivalent.

    Since token_equiv = input + (output * 6) and cost = input * $0.50/M + output * $3.00/M,
    we can simplify: cost = $0.50/M * (input + output * 6) = $0.50/M * token_equiv
    So cost per token equiv is just the input token price!
    """
    return GEMINI_INPUT_PRICE_PER_M_TOKENS_USD / 1_000_000


def get_gemini_cost_per_page_usd() -> float:
    """Calculate Gemini API cost per average page (for display)."""
    return get_gemini_cost_per_token_equiv_usd() * TOKENS_PER_PAGE


def get_inworld_cost_per_char_usd() -> float:
    """Get Inworld TTS cost per character."""
    return INWORLD_TTS1_PRICE_PER_M_CHARS_USD / 1_000_000


def get_runpod_max_monthly_usd() -> float:
    """Calculate max RunPod overflow cost (all workers 24/7)."""
    seconds_per_month = 60 * 60 * 24 * 30
    return RUNPOD_COST_PER_SECOND_USD * RUNPOD_MAX_WORKERS * seconds_per_month


def get_r2_monthly_cost_usd(total_db_storage_mb: float) -> dict:
    """Calculate R2 costs based on total DB storage across all users.

    Returns breakdown: {storage, class_a, class_b, total}
    """
    # Image storage = DB storage × ratio
    image_storage_mb = total_db_storage_mb * R2_IMAGES_PER_MB_DB_STORAGE
    image_storage_gb = image_storage_mb / 1024

    # Storage cost (after free tier)
    billable_storage_gb = max(0, image_storage_gb - R2_FREE_STORAGE_GB)
    storage_cost = billable_storage_gb * R2_COST_PER_GB_MONTH_USD

    # Estimate number of images (~120KB average per image from prod data)
    avg_image_kb = 120
    num_images = (image_storage_mb * 1024) / avg_image_kb

    # Class A ops (writes) - assume each image written once per month (new docs)
    # In reality much lower since images persist, but conservative estimate
    class_a_ops = num_images * 0.1  # ~10% of images are new per month
    billable_class_a = max(0, class_a_ops - R2_FREE_CLASS_A_OPS)
    class_a_cost = (billable_class_a / 1_000_000) * R2_COST_PER_M_CLASS_A_USD

    # Class B ops (reads) - each image viewed N times per month
    class_b_ops = num_images * R2_IMAGE_VIEWS_PER_IMAGE_MONTH
    billable_class_b = max(0, class_b_ops - R2_FREE_CLASS_B_OPS)
    class_b_cost = (billable_class_b / 1_000_000) * R2_COST_PER_M_CLASS_B_USD

    return {
        "storage_gb": image_storage_gb,
        "storage_cost": storage_cost,
        "class_a_ops": class_a_ops,
        "class_a_cost": class_a_cost,
        "class_b_ops": class_b_ops,
        "class_b_cost": class_b_cost,
        "total": storage_cost + class_a_cost + class_b_cost,
    }


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
    ocr_tokens: int  # Token equivalents (input + output*6)
    ocr_pages_approx: int  # Approximate pages for display
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
    ocr_tokens: int,
    voice_chars: int,
    utilization: float = 1.0,
) -> PlanMetrics:
    """Calculate all metrics for a plan."""
    months = 12 if interval == "yearly" else 1

    # Variable costs at given utilization
    gemini_per_token = usd_to_eur(get_gemini_cost_per_token_equiv_usd())
    inworld_per_char = usd_to_eur(get_inworld_cost_per_char_usd())

    ocr_cost = ocr_tokens * months * gemini_per_token * utilization
    voice_cost = voice_chars * months * inworld_per_char * utilization
    total_var = ocr_cost + voice_cost

    # Approximate pages for display
    ocr_pages_approx = int(ocr_tokens / TOKENS_PER_PAGE) if TOKENS_PER_PAGE > 0 else 0

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
        full_var = ocr_tokens * months * gemini_per_token + voice_chars * months * inworld_per_char
        if full_var > 0:
            breakeven_util[vat_name] = (net / full_var) * 100
        else:
            breakeven_util[vat_name] = float("inf")

    return PlanMetrics(
        name=name,
        price_eur=price_eur,
        interval=interval,
        months=months,
        ocr_tokens=ocr_tokens,
        ocr_pages_approx=ocr_pages_approx,
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

    # R2 storage costs (for extracted images)
    # Estimate actual DB usage from storage limit × utilization × overhead multiplier
    db_storage_per_user_mb = STORAGE_LIMIT_PAID_MB * utilization * STORAGE_ACTUAL_MULTIPLIER
    total_db_storage_mb = num_users * db_storage_per_user_mb
    r2_costs = get_r2_monthly_cost_usd(total_db_storage_mb)
    r2_monthly = usd_to_eur(r2_costs["total"])

    total_costs = total_variable_costs + total_stripe_fees + fixed_costs + runpod_overflow + r2_monthly
    gross_profit = (
        total_revenue
        - total_vat_paid
        - total_stripe_fees
        - total_variable_costs
        - fixed_costs
        - runpod_overflow
        - r2_monthly
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
        "monthly_r2": r2_monthly,
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
    gemini_token = get_gemini_cost_per_token_equiv_usd()
    gemini_page = get_gemini_cost_per_page_usd()
    runpod_max = get_runpod_max_monthly_usd()
    thinking_label = f" + {GEMINI_THINKING_TOKENS} thinking" if GEMINI_THINKING_TOKENS > 0 else ""

    if PLAIN_MODE:
        print("1. UNIT COSTS")
        print("Component\tUSD\tEUR\tNotes")
        print(
            f"Gemini OCR/M tokens\t${gemini_token * 1_000_000:.2f}\t€{usd_to_eur(gemini_token * 1_000_000):.2f}\tToken equiv = in + out×{OUTPUT_TOKEN_MULTIPLIER}"
        )
        print(
            f"Gemini OCR/page (~{TOKENS_PER_PAGE} tok)\t${gemini_page:.4f}\t€{usd_to_eur(gemini_page):.4f}\t{GEMINI_INPUT_TOKENS} in + {GEMINI_OUTPUT_TOKENS} out{thinking_label}"
        )
        print(
            f"Inworld TTS-1/M chars\t${INWORLD_TTS1_PRICE_PER_M_CHARS_USD:.2f}\t€{usd_to_eur(INWORLD_TTS1_PRICE_PER_M_CHARS_USD):.2f}\tTTS-1-Max $10/M but 2x credits"
        )
        print(
            f"RunPod Overflow max/mo\t${runpod_max:.2f}\t€{usd_to_eur(runpod_max):.2f}\t{RUNPOD_MAX_WORKERS} workers 24/7"
        )
        print(
            f"R2 Storage/GB-month\t${R2_COST_PER_GB_MONTH_USD:.3f}\t€{usd_to_eur(R2_COST_PER_GB_MONTH_USD):.3f}\t{R2_FREE_STORAGE_GB}GB free"
        )
        print(
            f"R2 Class B (reads)/M\t${R2_COST_PER_M_CLASS_B_USD:.2f}\t€{usd_to_eur(R2_COST_PER_M_CLASS_B_USD):.2f}\t{R2_FREE_CLASS_B_OPS / 1_000_000:.0f}M free"
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
        "Gemini OCR (per M tokens)",
        f"${gemini_token * 1_000_000:.2f}",
        f"€{usd_to_eur(gemini_token * 1_000_000):.2f}",
        f"Token equiv = in + out×{OUTPUT_TOKEN_MULTIPLIER}",
    )
    table.add_row(
        f"Gemini OCR (per page, ~{TOKENS_PER_PAGE} tok)",
        f"${gemini_page:.4f}",
        f"€{usd_to_eur(gemini_page):.4f}",
        f"{GEMINI_INPUT_TOKENS} in + {GEMINI_OUTPUT_TOKENS} out{thinking_label}",
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
        "R2 Storage (per GB-month)",
        f"${R2_COST_PER_GB_MONTH_USD:.3f}",
        f"€{usd_to_eur(R2_COST_PER_GB_MONTH_USD):.3f}",
        f"{R2_FREE_STORAGE_GB}GB free tier",
    )

    table.add_row(
        "R2 Class B reads (per M)",
        f"${R2_COST_PER_M_CLASS_B_USD:.2f}",
        f"€{usd_to_eur(R2_COST_PER_M_CLASS_B_USD):.2f}",
        f"{R2_FREE_CLASS_B_OPS / 1_000_000:.0f}M free tier",
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
        print("Plan\tPrice\tOCR tokens\t~Pages\tVoice/mo\tOCR Cost\tVoice Cost\tTotal Var\tOCR%\tVoice%")
        for name, (price, interval, ocr_tokens, voice) in PLANS.items():
            metrics = calculate_plan_metrics(name, price, interval, ocr_tokens, voice, 1.0)
            voice_display = f"{voice / 1_000_000:.1f}M" if voice > 0 else "0"
            ocr_display = f"{ocr_tokens / 1_000_000:.1f}M"
            period = "/yr" if interval == "yearly" else "/mo"
            total = metrics.total_variable_cost
            ocr_pct = (metrics.ocr_cost / total * 100) if total > 0 else 0
            voice_pct = (metrics.voice_cost / total * 100) if total > 0 else 0
            print(
                f"{name}\t€{price}{period}\t{ocr_display}\t~{metrics.ocr_pages_approx}\t{voice_display}\t€{metrics.ocr_cost:.2f}\t€{metrics.voice_cost:.2f}\t€{metrics.total_variable_cost:.2f}\t{ocr_pct:.0f}%\t{voice_pct:.0f}%"
            )
        print()
        return

    console.print("\n[bold yellow]2. PLAN LIMITS & VARIABLE COSTS (100% utilization)[/bold yellow]")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("OCR tokens", justify="right")
    table.add_column("~Pages", justify="right")
    table.add_column("Voice/mo", justify="right")
    table.add_column("OCR Cost", justify="right")
    table.add_column("Voice Cost", justify="right")
    table.add_column("Total Var", justify="right", style="bold")
    table.add_column("OCR%", justify="right")
    table.add_column("Voice%", justify="right")

    for name, (price, interval, ocr_tokens, voice) in PLANS.items():
        metrics = calculate_plan_metrics(name, price, interval, ocr_tokens, voice, 1.0)

        voice_display = f"{voice / 1_000_000:.1f}M" if voice > 0 else "0"
        ocr_display = f"{ocr_tokens / 1_000_000:.1f}M"
        period = "/yr" if interval == "yearly" else "/mo"
        total = metrics.total_variable_cost
        ocr_pct = (metrics.ocr_cost / total * 100) if total > 0 else 0
        voice_pct = (metrics.voice_cost / total * 100) if total > 0 else 0

        table.add_row(
            name,
            f"€{price}{period}",
            ocr_display,
            f"~{metrics.ocr_pages_approx}",
            voice_display,
            f"€{metrics.ocr_cost:.2f}",
            f"€{metrics.voice_cost:.2f}",
            f"€{metrics.total_variable_cost:.2f}",
            f"{ocr_pct:.0f}%",
            f"{voice_pct:.0f}%",
        )

    console.print(table)


def print_value_analysis():
    """Print value per euro analysis - what users get for their money."""
    if PLAIN_MODE:
        print("2b. VALUE PER EURO")
        print("Plan\tPrice\tTokens/€\tChars/€\t~Hours\tPages/€")
        for name, (price, interval, ocr_tokens, voice_chars) in PLANS.items():
            months = 12 if interval == "yearly" else 1
            monthly_price = price / months
            tokens_per_eur = ocr_tokens / monthly_price if monthly_price > 0 else 0
            chars_per_eur = voice_chars / monthly_price if monthly_price > 0 and voice_chars > 0 else 0
            hours = voice_chars / CHARS_PER_SECOND / SECONDS_PER_HOUR if voice_chars > 0 else 0
            pages_per_eur = (ocr_tokens / TOKENS_PER_PAGE) / monthly_price if monthly_price > 0 else 0
            hours_str = f"~{hours:.0f}h" if hours > 0 else "—"
            chars_str = f"{chars_per_eur / 1000:.0f}K" if chars_per_eur > 0 else "—"
            period = "/yr" if interval == "yearly" else "/mo"
            print(
                f"{name}\t€{price}{period}\t{tokens_per_eur / 1000:.0f}K\t{chars_str}\t{hours_str}\t{pages_per_eur:.0f}"
            )
        print()
        return

    console.print("\n[bold yellow]2b. VALUE PER EURO[/bold yellow]")
    console.print("[dim]What users get for their money (yearly normalized to monthly)[/dim]\n")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Plan", style="cyan")
    table.add_column("Price", justify="right")
    table.add_column("€/mo eff.", justify="right")
    table.add_column("Tokens/€", justify="right")
    table.add_column("Chars/€", justify="right")
    table.add_column("~Hours", justify="right")
    table.add_column("Pages/€", justify="right")

    for name, (price, interval, ocr_tokens, voice_chars) in PLANS.items():
        months = 12 if interval == "yearly" else 1
        monthly_price = price / months
        tokens_per_eur = ocr_tokens / monthly_price if monthly_price > 0 else 0
        chars_per_eur = voice_chars / monthly_price if monthly_price > 0 and voice_chars > 0 else 0
        hours = voice_chars / CHARS_PER_SECOND / SECONDS_PER_HOUR if voice_chars > 0 else 0
        pages_per_eur = (ocr_tokens / TOKENS_PER_PAGE) / monthly_price if monthly_price > 0 else 0

        period = "/yr" if interval == "yearly" else "/mo"
        hours_str = f"~{hours:.0f}h" if hours > 0 else "—"
        chars_str = f"{chars_per_eur / 1000:.0f}K" if chars_per_eur > 0 else "—"

        table.add_row(
            name,
            f"€{price}{period}",
            f"€{monthly_price:.2f}",
            f"{tokens_per_eur / 1000:.0f}K",
            chars_str,
            hours_str,
            f"{pages_per_eur:.0f}",
        )

    console.print(table)
    console.print(f"[dim]Hours based on ~{CHARS_PER_SECOND} chars/second speech rate. TTS-1-Max uses 2x chars.[/dim]")


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
        print("Users\tRevenue\tVAT\tStripe\tVariable\tFixed\tRunPod+\tR2\tGross Profit\tNet/yr")
        for num_users in USER_COUNTS:
            biz = calculate_business_metrics(num_users, PLAN_DISTRIBUTION, DEFAULT_UTILIZATION, DEFAULT_VAT)
            print(
                f"{num_users}\t€{biz['monthly_revenue']:.0f}\t€{biz['monthly_vat']:.0f}\t€{biz['monthly_stripe']:.0f}\t€{biz['monthly_variable']:.0f}\t€{biz['monthly_fixed']:.0f}\t€{biz['monthly_runpod_overflow']:.0f}\t€{biz['monthly_r2']:.0f}\t€{biz['monthly_gross_profit']:.0f}\t€{biz['annual_net_profit']:.0f}"
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
    table.add_column("R2", justify="right")
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
            f"€{biz['monthly_r2']:,.0f}",
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
        print("9. SUMMARY")
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

    console.print("\n[bold yellow]9. SUMMARY[/bold yellow]")

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


def print_free_user_analysis():
    """Print analysis of free/guest user costs and VPS capacity."""
    # Per-user actual DB storage at 75% utilization with overhead multiplier
    guest_db_mb = STORAGE_LIMIT_GUEST_MB * DEFAULT_UTILIZATION * STORAGE_ACTUAL_MULTIPLIER
    free_db_mb = STORAGE_LIMIT_FREE_MB * DEFAULT_UTILIZATION * STORAGE_ACTUAL_MULTIPLIER
    paid_db_mb = STORAGE_LIMIT_PAID_MB * DEFAULT_UTILIZATION * STORAGE_ACTUAL_MULTIPLIER

    # Note: Free/guest users don't have Gemini extraction, so no R2 image costs
    # Paid users have images, but those are on R2 (not counted against VPS DB storage)

    # VPS capacity by user type
    vps_db_gb = VPS_AVAILABLE_DB_STORAGE_GB
    guest_capacity = int((vps_db_gb * 1024) / guest_db_mb)
    free_capacity = int((vps_db_gb * 1024) / free_db_mb)
    paid_capacity = int((vps_db_gb * 1024) / paid_db_mb)

    # Realistic mix: 30% guest (cleaned up periodically), 50% free, 20% paid
    mix_avg_mb = 0.30 * guest_db_mb + 0.50 * free_db_mb + 0.20 * paid_db_mb
    mix_capacity = int((vps_db_gb * 1024) / mix_avg_mb)

    # Cost analysis: Free/guest use browser TTS
    # The only real cost is DB storage (amortized VPS cost)
    vps_monthly = VPS_MONTHLY_EUR
    cost_per_gb_month = vps_monthly / vps_db_gb
    guest_monthly_cost = (guest_db_mb / 1024) * cost_per_gb_month
    free_monthly_cost = (free_db_mb / 1024) * cost_per_gb_month

    if PLAIN_MODE:
        print("8. FREE/GUEST USER ANALYSIS")
        print()
        print("DB Storage per User (75% util)")
        print("Tier\tLimit\tActual DB")
        print(f"Guest\t{STORAGE_LIMIT_GUEST_MB}MB\t{guest_db_mb:.0f}MB")
        print(f"Free\t{STORAGE_LIMIT_FREE_MB}MB\t{free_db_mb:.0f}MB")
        print(f"Paid\t{STORAGE_LIMIT_PAID_MB}MB\t{paid_db_mb:.0f}MB")
        print()
        print(f"VPS Capacity ({vps_db_gb}GB available for DB)")
        print("Scenario\tUsers\tNotes")
        print(f"All guests\t{guest_capacity:,}\tLower bound")
        print(f"All free\t{free_capacity:,}\t")
        print(f"All paid\t{paid_capacity:,}\tUpper bound")
        print(f"Realistic mix\t{mix_capacity:,}\t30/50/20% guest/free/paid")
        print()
        print("Free User Cost (amortized VPS)")
        print("Tier\tCost/mo\tNotes")
        print(f"Guest\t€{guest_monthly_cost:.4f}\tDB storage only")
        print(f"Free\t€{free_monthly_cost:.4f}\tDB storage only")
        print()
        print("Note: Free/guest use browser TTS (no API cost). No R2 costs (no extraction).")
        print()
        return

    console.print("\n[bold yellow]8. FREE/GUEST USER ANALYSIS[/bold yellow]")
    console.print("[dim]Impact of non-paying users on VPS capacity[/dim]\n")

    # Storage per user table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold", title="DB Storage per User (75% utilization)")
    table.add_column("Tier", style="cyan")
    table.add_column("Limit", justify="right")
    table.add_column("Actual DB*", justify="right")
    table.add_column("Has Images?", justify="center")

    table.add_row("Guest", f"{STORAGE_LIMIT_GUEST_MB}MB", f"{guest_db_mb:.0f}MB", "No")
    table.add_row("Free", f"{STORAGE_LIMIT_FREE_MB}MB", f"{free_db_mb:.0f}MB", "No")
    table.add_row("Paid", f"{STORAGE_LIMIT_PAID_MB}MB", f"{paid_db_mb:.0f}MB", "[dim]Yes (R2)[/dim]")

    console.print(table)
    console.print(
        f"[dim]*Actual DB = limit × {DEFAULT_UTILIZATION:.0%} util × {STORAGE_ACTUAL_MULTIPLIER}× TOAST ratio (measured 0.5x, conservative 0.7x)[/dim]\n"
    )

    # VPS capacity table
    table2 = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        title=f"VPS Capacity ({vps_db_gb}GB available for Postgres)",
    )
    table2.add_column("Scenario", style="cyan")
    table2.add_column("Max Users", justify="right")
    table2.add_column("Notes")

    table2.add_row("All guests", f"{guest_capacity:,}", "[dim]Lower bound[/dim]")
    table2.add_row("All free", f"{free_capacity:,}", "")
    table2.add_row("All paid", f"{paid_capacity:,}", "[dim]Upper bound (DB only)[/dim]")
    table2.add_row("[bold]Realistic mix[/bold]", f"[bold]{mix_capacity:,}[/bold]", "30/50/20% guest/free/paid")

    console.print(table2)

    # Cost per free user
    console.print("\n[bold]Amortized Cost per Non-Paying User:[/bold]")
    console.print(f"  Guest: [green]€{guest_monthly_cost:.4f}[/green]/month (DB storage)")
    console.print(f"  Free:  [green]€{free_monthly_cost:.4f}[/green]/month (DB storage)")
    console.print(
        "\n[dim]Note: Free/guest use self-hosted TTS (no API cost until overflow). No R2 costs (no extraction access).[/dim]"
    )


def print_config_summary():
    """Print current configuration."""
    if PLAIN_MODE:
        print("CONFIG")
        print(f"Currency: 1 EUR = {EUR_USD_RATE} USD")
        print(f"Default VAT: {DEFAULT_VAT} ({VAT_RATES[DEFAULT_VAT] * 100:.0f}%)")
        print(f"Default Utilization: {DEFAULT_UTILIZATION * 100:.0f}%")
        print(f"Stripe: {STRIPE_PERCENT * 100:.0f}% + €{STRIPE_FIXED_EUR}")
        thinking_str = f", {GEMINI_THINKING_TOKENS} thinking" if GEMINI_THINKING_TOKENS > 0 else ", no thinking"
        print(
            f"Gemini 3 Flash: ${GEMINI_INPUT_PRICE_PER_M_TOKENS_USD}/M in, ${GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD}/M out{thinking_str}"
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
[cyan]Gemini 3 Flash:[/cyan] ${GEMINI_INPUT_PRICE_PER_M_TOKENS_USD}/M in, ${GEMINI_OUTPUT_PRICE_PER_M_TOKENS_USD}/M out, {GEMINI_THINKING_TOKENS} thinking tokens
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
    print_value_analysis()
    print_breakeven_table()
    print_profit_by_utilization()
    print_margin_breakdown()
    print_vat_comparison()
    print_business_scaling()
    print_free_user_analysis()
    print_recommendations()

    if not PLAIN_MODE:
        console.print("\n[dim]Edit the CONFIGURATION section at the top of this script to explore scenarios.[/dim]\n")


if __name__ == "__main__":
    main()
