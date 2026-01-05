# Comprehensive Markdown Test Document

This document tests the markdown parser across various content types and edge cases.

## 1. Realistic Academic Content

### Abstract

Recent advances in neural text-to-speech (TTS) systems have enabled high-quality voice synthesis from written text. This paper presents **Yapit**, an open-source platform that combines browser-side inference using Kokoro.js with optional server-side processing for premium voices. Our approach achieves a mean opinion score (MOS) of 4.2 while maintaining sub-100ms latency for streaming applications.

### Introduction

The field of speech synthesis has evolved significantly since the early days of concatenative TTS. Modern approaches leverage deep learning architectures including:

1. Tacotron-style encoder-decoder models
2. Transformer-based architectures with attention mechanisms
3. Diffusion models for high-fidelity audio generation

We build upon prior work by Smith et al. (2023) and the FastSpeech2 architecture proposed by Ren et al. The key contributions of this paper are threefold. First, we introduce a novel streaming inference approach. Second, we demonstrate efficient browser-side model execution. Third, we provide comprehensive benchmarks across multiple languages.

### Methodology

Our system processes documents through a structured pipeline. The input text is first normalized and split into prosodic units. Each unit is then encoded using a pretrained language model, specifically a 12-layer transformer with 768-dimensional hidden states.

The acoustic model generates mel-spectrograms at 22.05 kHz with 80 mel channels. We employ a HiFi-GAN vocoder for waveform synthesis, achieving real-time factors exceeding 100x on consumer hardware.

> **Note:** All experiments were conducted on a single NVIDIA RTX 3090 GPU with 24GB VRAM. Results may vary on different hardware configurations.

### Results

Performance metrics across different model configurations:

| Model | Parameters | RTF | MOS |
|-------|------------|-----|-----|
| Small | 25M | 150x | 3.8 |
| Medium | 82M | 95x | 4.1 |
| Large | 200M | 45x | 4.3 |

The relationship between model size and quality follows $MOS = 3.2 + 0.5 \cdot \log(P)$ where $P$ is the parameter count in millions.

---

## 2. Code Documentation Style

### Installation

To install Yapit, ensure you have Python 3.11+ and run:

```bash
pip install yapit
# or with uv
uv add yapit
```

### Quick Start

Here's a minimal example to synthesize speech:

```python
from yapit import TextToSpeech

tts = TextToSpeech(model="kokoro-v1")
audio = tts.synthesize("Hello, world!")
audio.save("output.wav")
```

For streaming applications, use the async API:

```python
async def stream_synthesis(text: str):
    async for chunk in tts.stream(text):
        yield chunk.audio_bytes
```

### Configuration

The `TextToSpeech` class accepts several parameters:

- `model` — Model identifier (default: `"kokoro-v1"`)
- `voice` — Voice preset name
- `speed` — Playback speed multiplier (0.5-2.0)
- `sample_rate` — Output sample rate in Hz

---

## 3. Edge Cases & Stress Tests

### Empty and Whitespace

The parser should handle paragraphs with varying whitespace gracefully.

### Very Long Paragraph Without Breaks

This is a deliberately long paragraph designed to test the sentence-boundary splitting logic. The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. How vexingly quick daft zebras jump! The five boxing wizards jump quickly. Sphinx of black quartz, judge my vow. Two driven jocks help fax my big quiz. The jay, pig, fox, zebra and my wolves quack! Blowzy red vixens fight for a quick jump. Joaquin Phoenix was gazed by MTV for luck. A wizard's job is to vex chumps quickly in fog. Watch Jeopardy, Alex Trebek's fun TV quiz game. By Jove, my quick study of lexicography won a prize! Waxy and quivering, jocks fumble the pizza.

### Nested Formatting

This has **bold with *nested italic* inside** and *italic with **nested bold** inside* and even ***bold italic*** combined.

### Special Characters & Unicode

Quotes: "double" and 'single' and "smart quotes"
Dashes: hyphen-word, en–dash, em—dash
Ellipsis: Wait for it...
Arrows: → ← ↑ ↓ ⇒ ⇐
Math symbols: ± × ÷ ≠ ≤ ≥ ∞ ∑ ∏ √
Emoji: 🎤 🔊 📄 ✨

### Inline Code in Various Contexts

Use `const x = 42` for constants. The function `calculateDuration()` returns milliseconds. Don't confuse `null` with `undefined` or `None`.

### Complex List Nesting

- Top level item
- Another top level
  - Nested item one
  - Nested item two
- Back to top level

1. First ordered
2. Second ordered
3. Third with sub-items:
   - Unordered under ordered
   - Another one

### Multiple Blockquotes

> Simple single-line quote.

> Multi-line blockquote that spans
> across several lines of text
> to test paragraph handling.

> Quote with **formatting** and `code` inside.

### Adjacent Code Blocks

```javascript
console.log("First block");
```

```python
print("Second block")
```

### Display Math

The loss function is defined as:

$$
\mathcal{L} = -\sum_{i=1}^{N} y_i \log(\hat{y}_i) + (1-y_i)\log(1-\hat{y}_i)
$$

And the attention weights:

$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$

### Links and References

Check out [the documentation](https://docs.example.com) for more details. You can also visit [GitHub](https://github.com/yapit-tts/yapit "Yapit Repository") or read the [FAQ](/faq).

### Horizontal Rules

Content above the rule.

---

Content between rules.

***

Content below the second rule.

### Table with Various Content

| Feature | Status | Notes |
|---------|--------|-------|
| Basic TTS | ✅ Done | Production ready |
| Streaming | ✅ Done | Sub-100ms latency |
| Multi-voice | 🚧 WIP | 3 voices available |
| SSML | ❌ Planned | Q2 2025 |

---

## 4. Final Section

This concludes our comprehensive test document. The parser should correctly identify and transform all elements above into structured blocks, with appropriate `audio_block_idx` values for prose content and `null` for code, math, and tables.

**Summary statistics expected:**
- Multiple heading levels (h1, h2, h3)
- ~15+ paragraphs
- Several code blocks (bash, python, javascript)
- 2 tables
- Multiple lists (ordered and unordered)
- Blockquotes
- Display math blocks
- Horizontal rules
- Inline formatting throughout
