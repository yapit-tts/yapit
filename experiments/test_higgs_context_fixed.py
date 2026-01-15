#!/usr/bin/env python3
"""Fixed HIGGS context test - uses proper audio_ids tensor approach from official examples.

The previous script was WRONG - it passed context as chat messages, which confused the model.
The correct approach uses audio_ids_concat tensors for context, not AudioContent messages.

Run on GPU pod:
    python test_higgs_context_fixed.py --output-dir ./fixed_output --voice-dir higgs-audio/examples/voice_prompts
"""

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import click
import numpy as np
import soundfile as sf
import torch

# Test blocks - ~150 chars each, varied topics
BLOCKS = {
    "cooking": "The secret to perfect risotto lies in patience and constant stirring, gradually adding warm broth until the rice releases its starches and creates that signature creamy texture.",
    "space": "The James Webb Space Telescope has captured unprecedented images of distant galaxies, revealing structures that formed just hundreds of millions of years after the Big Bang itself.",
    "sports": "The championship game went into triple overtime before the underdog team finally scored the winning goal, sending their fans into an absolute frenzy of celebration.",
    "finance": "Global markets reacted swiftly to the central bank's unexpected interest rate decision, with major indices dropping sharply before recovering in late afternoon trading.",
    "nature": "The ancient redwood forest stretched endlessly before us, towering trees filtering sunlight into golden beams that danced across the fern-covered forest floor in mesmerizing patterns.",
}

# Edge case blocks - testing various failure modes
EDGE_BLOCKS = {
    # Numbers, currency, percentages
    "numbers": "According to the 2024 fiscal report, total assets increased from $892.3 million to $1.24 billion, representing a 39.1% growth rate, while operating expenses remained stable.",
    # Abbreviations, names with punctuation, times
    "abbrev": "Dr. Sarah O'Connor-Smith (CEO, TechCorp Inc.) announced the $2.5B acquisition at 9:00 AM EST, stating: 'This represents a 3x ROI for our Q4 2024 initiatives.'",
    # Technical content with special characters
    "technical": "The API endpoint /v2/users/{id}/settings accepts PUT requests with JSON payloads containing nested objects like {config: {theme: 'dark', lang: 'en-US'}}.",
    # LaTeX-like math notation (escaped markdown that slipped through parser)
    "latex": r"The quadratic formula \(x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}\) solves equations of the form \(ax^2 + bx + c = 0\) for any real coefficients.",
    # URLs and email addresses
    "urls": "For more information, visit https://docs.example.com/api/v2/reference or contact support@company.io. The documentation is also available at ftp://files.example.org/docs/.",
    # Mixed language / Unicode
    "unicode": "The café résumé included naïve assumptions about the piñata supplier's coöperation with the Zürich-based firm's façade renovation project.",
    # Repeated words and stuttering patterns (might cause RAS issues)
    "repetition": "The the quick brown fox jumps over the the lazy dog dog dog. Wait, that that that doesn't sound right at all all all.",
    # Very short sentence fragments
    "fragments": "Yes. No. Maybe. Probably not. Who knows? Time will tell. Perhaps. Indeed. Absolutely. Never. Always. Sometimes.",
    # Long compound words and technical jargon
    "jargon": "The telecommunications infrastructure's backward-compatibility requirements necessitated a comprehensive refactoring of the microservices-based containerization orchestration system.",
    # Quotes within quotes, nested punctuation
    "quotes": "She said, \"He told me 'I don't know what you mean by \"impossible\"—it's clearly achievable!' and walked away.\"",
    # Code-like content
    "code": "To fix the bug, change `if (x == null)` to `if (x === undefined || x === null)` in the validateInput() function on line 42.",
}


@dataclass
class TestResult:
    name: str
    text: str
    context_blocks: list[str]
    output_path: str


def save_audio(audio: np.ndarray, path: Path, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate)
    print(f"    Saved: {path.name}")


@click.command()
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("./fixed_output"))
@click.option("--voice-dir", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--seed", default=42)
@click.option("--temperature", default=0.3)
@click.option("--buffer-size", default=2, help="Max chunks to keep in context buffer")
def main(output_dir: Path, voice_dir: Path, seed: int, temperature: float, buffer_size: int):
    """Test HIGGS context using proper audio_ids tensor approach."""
    # Import higgs-audio components
    from boson_multimodal.audio_processing.higgs_audio_tokenizer import load_higgs_audio_tokenizer
    from boson_multimodal.data_collator.higgs_audio_collator import HiggsAudioSampleCollator
    from boson_multimodal.data_types import AudioContent, ChatMLSample, Message
    from boson_multimodal.dataset.chatml_dataset import ChatMLDatasetSample, prepare_chatml_sample
    from boson_multimodal.model.higgs_audio import HiggsAudioModel
    from boson_multimodal.model.higgs_audio.utils import revert_delay_pattern
    from transformers import AutoConfig, AutoTokenizer
    from transformers.cache_utils import StaticCache

    print("=" * 70)
    print("HIGGS Context Test (Fixed - using audio_ids tensors)")
    print("=" * 70)

    output_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Load models
    model_path = "bosonai/higgs-audio-v2-generation-3B-base"
    tokenizer_path = "bosonai/higgs-audio-v2-tokenizer"

    print("\nLoading audio tokenizer...")
    audio_tokenizer = load_higgs_audio_tokenizer(tokenizer_path, device=device)

    print(f"Loading model on {device}...")
    model = HiggsAudioModel.from_pretrained(model_path, device_map=device, torch_dtype=torch.bfloat16)
    model.eval()

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    config = AutoConfig.from_pretrained(model_path)

    collator = HiggsAudioSampleCollator(
        whisper_processor=None,
        audio_in_token_id=config.audio_in_token_idx,
        audio_out_token_id=config.audio_out_token_idx,
        audio_stream_bos_id=config.audio_stream_bos_id,
        audio_stream_eos_id=config.audio_stream_eos_id,
        encode_whisper_embed=config.encode_whisper_embed,
        pad_token_id=config.pad_token_id,
        return_audio_in_tokens=config.encode_audio_in_tokens,
        use_delay_pattern=config.use_delay_pattern,
        round_to=1,
        audio_num_codebooks=config.audio_num_codebooks,
    )

    # Setup static KV cache
    cache_config = copy.deepcopy(model.config.text_config)
    cache_config.num_hidden_layers = model.config.text_config.num_hidden_layers
    if model.config.audio_dual_ffn_layers:
        cache_config.num_hidden_layers += len(model.config.audio_dual_ffn_layers)

    kv_caches = {
        length: StaticCache(
            config=cache_config,
            max_batch_size=1,
            max_cache_len=length,
            device=model.device,
            dtype=model.dtype,
        )
        for length in [1024, 4096, 8192]
    }

    print("Model loaded!\n")

    # Load reference voice
    ref_voice = "en_man"
    ref_audio_path = voice_dir / f"{ref_voice}.wav"
    ref_transcript = (voice_dir / f"{ref_voice}.txt").read_text().strip()
    ref_audio_ids = audio_tokenizer.encode(str(ref_audio_path))
    print(f"Reference voice: {ref_voice}")
    print(f"Reference transcript: {ref_transcript[:50]}...")

    # Base messages (system + reference)
    base_messages = [
        Message(
            role="system",
            content="Generate audio following instruction.\n\n<|scene_desc_start|>\nAudio is recorded from a quiet room.\n<|scene_desc_end|>",
        ),
        Message(role="user", content=ref_transcript),
        Message(role="assistant", content=AudioContent(audio_url=str(ref_audio_path))),
    ]

    results = []

    def generate_chunk(
        text: str, context_audio_ids: list, generation_messages: list
    ) -> tuple[np.ndarray, torch.Tensor]:
        """Generate audio for a single chunk with proper context."""
        # Add current text as user message
        curr_gen_messages = generation_messages + [Message(role="user", content=text)]

        # Build full message list
        chatml_sample = ChatMLSample(messages=base_messages + curr_gen_messages)
        input_tokens, _, _, _ = prepare_chatml_sample(chatml_sample, tokenizer)

        # Add assistant header
        postfix = tokenizer.encode("<|start_header_id|>assistant<|end_header_id|>\n\n", add_special_tokens=False)
        input_tokens.extend(postfix)

        # Combine reference audio + context audio IDs
        all_audio_ids = [ref_audio_ids] + context_audio_ids

        # Prepare sample with audio_ids tensors
        curr_sample = ChatMLDatasetSample(
            input_ids=torch.LongTensor(input_tokens),
            label_ids=None,
            audio_ids_concat=torch.concat([ele.cpu() for ele in all_audio_ids], dim=1) if all_audio_ids else None,
            audio_ids_start=torch.cumsum(
                torch.tensor([0] + [ele.shape[1] for ele in all_audio_ids], dtype=torch.long), dim=0
            )
            if all_audio_ids
            else None,
            audio_waveforms_concat=None,
            audio_waveforms_start=None,
            audio_sample_rate=None,
            audio_speaker_indices=None,
        )

        batch_data = collator([curr_sample])
        batch = asdict(batch_data)
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                batch[k] = v.contiguous().to(device)

        # Reset KV caches
        for kv_cache in kv_caches.values():
            kv_cache.reset()

        # Generate
        with torch.inference_mode():
            outputs = model.generate(
                **batch,
                max_new_tokens=2048,
                use_cache=True,
                do_sample=True,
                temperature=temperature,
                top_k=50,
                top_p=0.95,
                past_key_values_buckets=kv_caches,
                ras_win_len=7,
                ras_win_max_num_repeat=2,
                stop_strings=["<|end_of_text|>", "<|eot_id|>"],
                tokenizer=tokenizer,
                seed=seed,
            )

        # Process output audio
        step_audio_out_ids_l = []
        for ele in outputs[1]:
            audio_out_ids = ele
            if config.use_delay_pattern:
                audio_out_ids = revert_delay_pattern(audio_out_ids)
            step_audio_out_ids_l.append(audio_out_ids.clip(0, audio_tokenizer.codebook_size - 1)[:, 1:-1])

        audio_out_ids = torch.concat(step_audio_out_ids_l, dim=1)
        token_count = audio_out_ids.shape[1]
        print(f"      Generated {token_count} audio tokens (~{token_count / 75:.1f}s audio)")

        # Safety check: skip decode if way too many tokens (likely model went haywire)
        # Normal: ~150 char text → ~5-10 sec audio → ~375-750 tokens
        # Suspicious: >1500 tokens (~20 sec) for a single paragraph
        if token_count > 1500:
            print("      WARNING: Abnormally high token count, skipping decode")
            return None, audio_out_ids

        # Free some VRAM before decode
        torch.cuda.empty_cache()

        # Decode to waveform (returns numpy array)
        waveform = audio_tokenizer.decode(audio_out_ids.unsqueeze(0))[0, 0]

        return waveform, audio_out_ids

    # ==========================================================================
    # TEST 1: Baseline - no context
    # ==========================================================================
    print("=" * 70)
    print("TEST 1: BASELINE (no context)")
    print("=" * 70)

    out_dir = output_dir / "1_baseline"
    for name, text in BLOCKS.items():
        print(f"  Generating {name}...")
        audio, _ = generate_chunk(text, [], [])
        path = out_dir / f"{name}.wav"
        save_audio(audio, path)
        results.append(TestResult(name=f"baseline_{name}", text=text, context_blocks=[], output_path=str(path)))

    # ==========================================================================
    # TEST 2: Sequential with proper context accumulation
    # ==========================================================================
    print("\n" + "=" * 70)
    print(f"TEST 2: SEQUENTIAL (buffer_size={buffer_size})")
    print("=" * 70)

    out_dir = output_dir / "2_sequential"
    block_names = list(BLOCKS.keys())

    generated_audio_ids = []
    generation_messages = []

    for i, name in enumerate(block_names):
        text = BLOCKS[name]
        ctx_names = block_names[:i]
        print(f"  Generating {name} (context: {ctx_names or 'none'})...")

        audio, audio_ids = generate_chunk(text, generated_audio_ids, generation_messages)
        path = out_dir / f"{i + 1:02d}_{name}.wav"
        save_audio(audio, path)
        results.append(TestResult(name=f"seq_{name}", text=text, context_blocks=ctx_names, output_path=str(path)))

        # Update context (with buffer limit)
        generated_audio_ids.append(audio_ids)
        generation_messages.append(Message(role="user", content=text))
        generation_messages.append(Message(role="assistant", content=AudioContent(audio_url="")))

        if len(generated_audio_ids) > buffer_size:
            generated_audio_ids = generated_audio_ids[-buffer_size:]
            generation_messages = generation_messages[(-2 * buffer_size) :]

    # ==========================================================================
    # TEST 3: Non-adjacent context
    # ==========================================================================
    print("\n" + "=" * 70)
    print("TEST 3: NON-ADJACENT (cooking context -> finance)")
    print("=" * 70)

    out_dir = output_dir / "3_non_adjacent"

    # Generate cooking block
    print("  Generating cooking (no context)...")
    cooking_audio, cooking_ids = generate_chunk(BLOCKS["cooking"], [], [])
    save_audio(cooking_audio, out_dir / "01_cooking_no_ctx.wav")

    # Generate finance with cooking context
    print("  Generating finance (context: cooking)...")
    finance_audio, _ = generate_chunk(
        BLOCKS["finance"],
        [cooking_ids],
        [
            Message(role="user", content=BLOCKS["cooking"]),
            Message(role="assistant", content=AudioContent(audio_url="")),
        ],
    )
    save_audio(finance_audio, out_dir / "02_finance_with_cooking_ctx.wav")

    # Generate finance without context for comparison
    print("  Generating finance (no context)...")
    finance_no_ctx, _ = generate_chunk(BLOCKS["finance"], [], [])
    save_audio(finance_no_ctx, out_dir / "03_finance_no_ctx.wav")

    # ==========================================================================
    # TEST 4: Edge cases - standalone generation
    # ==========================================================================
    print("\n" + "=" * 70)
    print("TEST 4: EDGE CASES (standalone)")
    print("=" * 70)

    out_dir = output_dir / "4_edge_cases"
    edge_audio_ids = {}
    for name, text in EDGE_BLOCKS.items():
        print(f"  Generating {name}...")
        try:
            audio, audio_ids = generate_chunk(text, [], [])
            if audio is not None:
                save_audio(audio, out_dir / f"{name}.wav")
                edge_audio_ids[name] = audio_ids
            else:
                print("    SKIPPED: Token limit exceeded")
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print("    SKIPPED: OOM error")
                torch.cuda.empty_cache()
            else:
                raise

    # ==========================================================================
    # TEST 5: Context corruption - does weird context corrupt normal output?
    # ==========================================================================
    print("\n" + "=" * 70)
    print("TEST 5: CONTEXT CORRUPTION")
    print("=" * 70)

    out_dir = output_dir / "5_context_corruption"

    # Generate baseline nature block (no context) for comparison
    print("  Generating nature (baseline, no context)...")
    nature_baseline, _ = generate_chunk(BLOCKS["nature"], [], [])
    if nature_baseline is not None:
        save_audio(nature_baseline, out_dir / "00_nature_baseline.wav")

    # Test each edge case as context for the same normal block
    corruption_tests = ["latex", "repetition", "code", "quotes", "fragments"]
    for edge_name in corruption_tests:
        if edge_name not in edge_audio_ids:
            print(f"  Skipping nature (context: {edge_name}) - edge case not available")
            continue
        print(f"  Generating nature (context: {edge_name})...")
        try:
            nature_after_edge, _ = generate_chunk(
                BLOCKS["nature"],
                [edge_audio_ids[edge_name]],
                [
                    Message(role="user", content=EDGE_BLOCKS[edge_name]),
                    Message(role="assistant", content=AudioContent(audio_url="")),
                ],
            )
            if nature_after_edge is not None:
                save_audio(nature_after_edge, out_dir / f"nature_after_{edge_name}.wav")
            else:
                print("    SKIPPED: Token limit exceeded")
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print("    SKIPPED: OOM error")
                torch.cuda.empty_cache()
            else:
                raise

    # ==========================================================================
    # TEST 6: Chained edge cases - multiple weird contexts
    # ==========================================================================
    print("\n" + "=" * 70)
    print("TEST 6: CHAINED EDGE CASES")
    print("=" * 70)

    out_dir = output_dir / "6_chained_edge"

    # Chain: latex -> repetition -> nature
    # Use pre-generated edge audio if available, otherwise generate fresh
    latex_ids = None
    rep_ids = None

    try:
        if "latex" in edge_audio_ids:
            latex_ids = edge_audio_ids["latex"]
            print("  Using pre-generated latex audio")
        else:
            print("  Generating latex (no context)...")
            latex_audio, latex_ids = generate_chunk(EDGE_BLOCKS["latex"], [], [])
            if latex_audio is not None:
                save_audio(latex_audio, out_dir / "01_latex.wav")

        if latex_ids is None:
            print("  SKIPPED TEST 6: No latex audio available")
        else:
            if "repetition" in edge_audio_ids:
                rep_ids = edge_audio_ids["repetition"]
                print("  Using pre-generated repetition audio")
            else:
                print("  Generating repetition (context: latex)...")
                rep_audio, rep_ids = generate_chunk(
                    EDGE_BLOCKS["repetition"],
                    [latex_ids],
                    [
                        Message(role="user", content=EDGE_BLOCKS["latex"]),
                        Message(role="assistant", content=AudioContent(audio_url="")),
                    ],
                )
                if rep_audio is not None:
                    save_audio(rep_audio, out_dir / "02_repetition_after_latex.wav")

            if rep_ids is None:
                print("  SKIPPED: No repetition audio for chaining")
            else:
                print("  Generating nature (context: latex + repetition)...")
                nature_chained, _ = generate_chunk(
                    BLOCKS["nature"],
                    [latex_ids, rep_ids],
                    [
                        Message(role="user", content=EDGE_BLOCKS["latex"]),
                        Message(role="assistant", content=AudioContent(audio_url="")),
                        Message(role="user", content=EDGE_BLOCKS["repetition"]),
                        Message(role="assistant", content=AudioContent(audio_url="")),
                    ],
                )
                if nature_chained is not None:
                    save_audio(nature_chained, out_dir / "03_nature_after_latex_repetition.wav")
                else:
                    print("    SKIPPED: Token limit exceeded")
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            print("    SKIPPED TEST 6: OOM error")
            torch.cuda.empty_cache()
        else:
            raise

    # ==========================================================================
    # Summary
    # ==========================================================================
    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"\nOutput: {output_dir.absolute()}")
    print("\nDirectories:")
    print("  1_baseline/           - Each block independently (no context)")
    print("  2_sequential/         - Blocks with accumulating context")
    print("  3_non_adjacent/       - Distant topic as context")
    print("  4_edge_cases/         - Edge case blocks standalone")
    print("  5_context_corruption/ - Normal block after weird context")
    print("  6_chained_edge/       - Multiple edge cases chained")
    print("\nKey comparisons:")
    print("  - 2_sequential: Should sound consistent across blocks")
    print("  - 3_non_adjacent: finance_with_cooking_ctx vs finance_no_ctx")
    print("  - 5_context_corruption: Compare nature_after_* to 00_nature_baseline")
    print("  - 6_chained_edge: Does stacking edge cases cause degradation?")

    # Save manifest
    with open(output_dir / "manifest.json", "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)


if __name__ == "__main__":
    main()
