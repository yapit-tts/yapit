# Comprehensive Markdown Test Document

This document tests the markdown parser across various content types and edge cases.

<yap-show>You can see me but not hear me!</yap-show>

<yap-show>
You should see me too.
</yap-show>

<yap-speak>You can hear me but not see me!</yap-speak>

## 1. Realistic Academic Content

### Abstract

Recent advances in neural text-to-speech (TTS) systems have enabled high-quality voice synthesis from written text. This paper presents **Yapit**, an open-source platform that combines browser-side inference using Kokoro.js with optional server-side processing for premium voices. ~~Our approach achieves a mean opinion score (MOS) of 4.2[^mos] while maintaining sub-100ms latency for streaming applications.~~

### Introduction

The field of speech synthesis has evolved significantly since the early days of concatenative TTS[^history]. Modern approaches leverage deep learning architectures including:

1. Tacotron-style encoder-decoder models
2. Transformer-based architectures with attention mechanisms
3. Diffusion models for high-fidelity audio generation

We build upon prior work by Smith et al. (2023) and the FastSpeech2 architecture proposed by Ren et al. The key contributions of this paper are threefold. First, we introduce a novel streaming inference approach. Second, we demonstrate efficient browser-side model execution. Third, we provide comprehensive benchmarks across multiple languages.

### Methodology

Our system processes documents through a structured pipeline. The input text is first normalized and split into prosodic units. Each unit is then encoded using a pretrained language model, specifically a 12-layer transformer with 768-dimensional hidden states.

The acoustic model generates mel-spectrograms at 22.05 kHz with 80 mel channels. We employ a HiFi-GAN vocoder for waveform synthesis, achieving real-time factors exceeding 100x on consumer hardware.

> [!PURPLE] Note
> All experiments were conducted on a single NVIDIA RTX 3090 GPU with 24GB VRAM. ~~Results may vary on different hardware configurations.~~

### Results

Performance metrics across different model configurations:

| Model | Parameters | RTF | MOS |
|-------|------------|-----|-----|
| Small | 25M | 150x | 3.8 |
| Medium | 82M | 95x | 4.1 |
| Large | 200M | 45x | 4.3 |

The relationship between model size and quality follows $MOS = 3.2 + 0.5 \cdot \log(P)$ where $P$ is the parameter count in millions.

---

## 2. Callout Showcase

All six callout colors with example use cases:

> [!BLUE] Definition 1.1 — Group
> A **group** is a set $G$ together with a binary operation that satisfies closure, associativity, identity, and invertibility.

> [!GREEN] Example
> The integers $\mathbb{Z}$ under addition form a group. The identity element is $0$, and the inverse of $n$ is $-n$.

> [!PURPLE] Remark
> This definition generalizes to non-abelian groups where $a \cdot b \neq b \cdot a$.

> [!RED] Warning
> Do not confuse groups with rings! Rings have two operations and may lack multiplicative inverses.

> [!YELLOW] Key Takeaway
> Groups are the fundamental building blocks of abstract algebra and appear throughout mathematics and physics.
>
> > [!GREEN] Nested Example

> [!TEAL] Exercise 1.1
> Prove that the set of $2 \times 2$ invertible matrices forms a group under matrix multiplication.
>
>> - Hint: Verify the group axioms one by one.
>>   - Bonus: Determine if this group is abelian or non-abelian.

> [!GRAY] Historical Note
> The concept of groups was first formalized by Évariste Galois in the 1830s, though the axiomatic definition came later with Weber and von Dyck.
>
> $$ G = \{ g_1, g_2, \ldots, g_n \} \quad \text{with operation } \cdot $$
> 
> The group axioms can be expressed as:
> - Closure: $\forall a, b \in G, a \cdot b \in G$
>   - etc
> - pp

---

## 3. Images and Captions

![Fourier Transform visualization](https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Fourier_transform_time_and_frequency_domains_%28small%29.gif/220px-Fourier_transform_time_and_frequency_domains_%28small%29.gif)

![Fourier Transform visualization](https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Fourier_transform_time_and_frequency_domains_%28small%29.gif/220px-Fourier_transform_time_and_frequency_domains_%28small%29.gif)<yap-cap>**Figure 1:** The Fourier transform decomposes a signal into its frequency components: $x(t) \leftrightarrow X(f)$ <yap-show>This is a yap show</yap-show><yap-speak>You're hearing a yap speak</yap-speak></yap-cap>

![Fourier Transform visualization](https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Fourier_transform_time_and_frequency_domains_%28small%29.gif/220px-Fourier_transform_time_and_frequency_domains_%28small%29.gif)<yap-cap>**Figure 1:** The Fourier transform decomposes a signal into its frequency components: $x(t) \leftrightarrow X(f)$ <yap-show>This is a yap show</yap-show><yap-speak>You're hearing a yap speak</yap-speak>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</yap-cap>

---

## 4. Code Documentation Style

Here's a minimal example to synthesize speech:

```python
from yapit import TextToSpeech

tts = TextToSpeech(model="kokoro-v1")
audio = tts.synthesize("Hello, world!")
audio.save("output.wav")
```

### Configuration

The `TextToSpeech` class accepts several parameters:

- `model` — Model identifier (default: `"kokoro-v1"`)
- `voice` — Voice preset name
- `speed` — Playback speed multiplier (0.5-2.0)
- `sample_rate` — Output sample rate in Hz

---

## 5. Edge Cases & Stress Tests

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

- Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
  - Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
- Lo

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

## 6. Footnotes Section

This section tests footnote rendering. The references appear at document end.

The Transformer architecture[^transformer] changed everything. Subsequent work on BERT[^bert] and GPT[^gpt] built upon these foundations.

Multiple footnotes in one sentence: Models use attention[^attention], layer normalization[^layernorm], and residual connections[^residual].

---

## 7. Final Section

This concludes our comprehensive test document. The parser should correctly identify and transform all elements above into structured blocks, with appropriate `audio_block_idx` values for prose content and silent blocks for code, math, and tables.

**Summary of features tested:**
- Heading levels (h1, h2, h3)
- Paragraphs with various formatting
- Code blocks (bash, python, javascript)
- Tables
- Ordered and unordered lists
- Regular blockquotes
- All 7 callout colors (BLUE, GREEN, PURPLE, RED, YELLOW, TEAL, GRAY)
- Display math
- Footnotes with various labels
- Horizontal rules
- Links with titles
- Images from external URLs
- Inline formatting (bold, italic, code)

[^mos]: Mean Opinion Score, a subjective measure of audio quality on a 1-5 scale.
[^history]: See Klatt (1987) for a comprehensive history of speech synthesis.
[^transformer]: Vaswani et al., "Attention Is All You Need", NeurIPS 2017.
[^bert]: Devlin et al., "BERT: Pre-training of Deep Bidirectional Transformers", 2019.
[^gpt]: Radford et al., "Language Models are Unsupervised Multitask Learners", 2019.
[^attention]: The attention mechanism allows the model to focus on relevant parts of the input.
[^layernorm]: Layer normalization stabilizes training by normalizing activations.
[^residual]: Residual connections help gradient flow in deep networks.
