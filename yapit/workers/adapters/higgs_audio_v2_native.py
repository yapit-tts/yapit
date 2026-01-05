"""Native PyTorch adapter for HIGGS Audio V2 with context accumulation support.

Uses low-level ChatMLDatasetSample approach (not HiggsAudioServeEngine) to enable
passing audio_ids_concat tensors for voice consistency across blocks.

See: ~/.claude/plans/higgs-audio-investigation.md for details on the two APIs.
"""

import base64
import copy
import io
import logging
import os
import pickle
from dataclasses import asdict
from pathlib import Path
from typing import Unpack

import numpy as np
import torch
from typing_extensions import TypedDict

from yapit.workers.adapters.base import SynthAdapter

log = logging.getLogger(__name__)


class VoiceConfig(TypedDict, total=False):
    seed: int
    temperature: float
    top_p: float
    top_k: int
    scene_description: str
    system_prompt: str
    ref_audio: str | None  # b64
    ref_audio_transcript: str | None  # text
    ref_preset: str | None  # voice preset name
    context_tokens: str | None  # base64 serialized list of audio token tensors


DEFAULT_VOICE_CONFIG: VoiceConfig = {
    "seed": 42,
    "temperature": 0.3,
    "top_p": 0.95,
    "top_k": 50,
    "scene_description": "Audio is recorded from a quiet room.",
    "system_prompt": "Generate audio following instruction.",
}


def serialize_audio_tokens(audio_ids: torch.Tensor) -> str:
    """Serialize audio token tensor to base64 string for caching/transport."""
    buffer = io.BytesIO()
    # Move to CPU and save as numpy for portability
    np.save(buffer, audio_ids.cpu().numpy(), allow_pickle=False)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def deserialize_audio_tokens(b64_data: str) -> torch.Tensor:
    """Deserialize base64 string back to audio token tensor."""
    buffer = io.BytesIO(base64.b64decode(b64_data))
    arr = np.load(buffer, allow_pickle=False)
    return torch.from_numpy(arr)


def deserialize_context_tokens(b64_data: str) -> list[tuple[str, torch.Tensor]]:
    """Deserialize base64 string containing list of (text, audio_tokens) tuples."""
    buffer = io.BytesIO(base64.b64decode(b64_data))
    data = pickle.load(buffer)
    return [(text, torch.from_numpy(arr) if isinstance(arr, np.ndarray) else arr) for text, arr in data]


def serialize_context_tokens(tensors: list[torch.Tensor]) -> str:
    """Serialize list of audio token tensors to base64 string."""
    buffer = io.BytesIO()
    # Convert to numpy arrays for portability
    data = [t.cpu().numpy() for t in tensors]
    pickle.dump(data, buffer)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class HiggsAudioV2NativeAdapter(SynthAdapter[VoiceConfig]):
    """HIGGS Audio V2 adapter using native PyTorch with context accumulation."""

    def __init__(self, voice_presets_dir: str | None = None) -> None:
        super().__init__()
        self._model = None
        self._audio_tokenizer = None
        self._tokenizer = None
        self._config = None
        self._collator = None
        self._kv_caches = None
        self._voice_presets_dir = Path(voice_presets_dir) if voice_presets_dir else None
        self._voice_presets: dict[str, tuple[torch.Tensor, str]] = {}  # name -> (audio_ids, transcript)
        # Last generated audio tokens (for returning to caller)
        self._last_audio_tokens: torch.Tensor | None = None

    async def initialize(self) -> None:
        from boson_multimodal.audio_processing.higgs_audio_tokenizer import load_higgs_audio_tokenizer
        from boson_multimodal.data_collator.higgs_audio_collator import HiggsAudioSampleCollator
        from boson_multimodal.model.higgs_audio import HiggsAudioModel
        from transformers import AutoConfig, AutoTokenizer
        from transformers.cache_utils import StaticCache

        model_path = os.getenv("HIGGS_MODEL_PATH", "bosonai/higgs-audio-v2-generation-3B-base")
        tokenizer_path = os.getenv("HIGGS_TOKENIZER_PATH", "bosonai/higgs-audio-v2-tokenizer")
        device = os.getenv("DEVICE", "cuda")

        log.info(f"Loading HIGGS native engine: model={model_path}, tokenizer={tokenizer_path}, device={device}")

        # Load audio tokenizer
        self._audio_tokenizer = load_higgs_audio_tokenizer(tokenizer_path, device=device)

        # Load model
        self._model = HiggsAudioModel.from_pretrained(model_path, device_map=device, torch_dtype=torch.bfloat16)
        self._model.eval()

        # Load text tokenizer and config
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._config = AutoConfig.from_pretrained(model_path)

        # Setup collator
        self._collator = HiggsAudioSampleCollator(
            whisper_processor=None,
            audio_in_token_id=self._config.audio_in_token_idx,
            audio_out_token_id=self._config.audio_out_token_idx,
            audio_stream_bos_id=self._config.audio_stream_bos_id,
            audio_stream_eos_id=self._config.audio_stream_eos_id,
            encode_whisper_embed=self._config.encode_whisper_embed,
            pad_token_id=self._config.pad_token_id,
            return_audio_in_tokens=self._config.encode_audio_in_tokens,
            use_delay_pattern=self._config.use_delay_pattern,
            round_to=1,
            audio_num_codebooks=self._config.audio_num_codebooks,
        )

        # Setup static KV caches
        cache_config = copy.deepcopy(self._model.config.text_config)
        cache_config.num_hidden_layers = self._model.config.text_config.num_hidden_layers
        if self._model.config.audio_dual_ffn_layers:
            cache_config.num_hidden_layers += len(self._model.config.audio_dual_ffn_layers)

        self._kv_caches = {
            length: StaticCache(
                config=cache_config,
                max_batch_size=1,
                max_cache_len=length,
                device=self._model.device,
                dtype=self._model.dtype,
            )
            for length in [1024, 4096, 8192]
        }

        # Load voice presets (pre-tokenize audio)
        if self._voice_presets_dir and self._voice_presets_dir.is_dir():
            for voice_dir in self._voice_presets_dir.iterdir():
                if voice_dir.is_dir():
                    audio_path = voice_dir / "audio.wav"
                    transcript_path = voice_dir / "transcript.txt"
                    if audio_path.exists() and transcript_path.exists():
                        audio_ids = self._audio_tokenizer.encode(str(audio_path))
                        transcript = transcript_path.read_text(encoding="utf-8").strip()
                        self._voice_presets[voice_dir.name] = (audio_ids, transcript)
            log.info(f"Loaded voice presets: {list(self._voice_presets.keys())}")

        log.info("HIGGS native engine loaded")

    async def synthesize(self, text: str, **kwargs: Unpack[VoiceConfig]) -> str:
        from boson_multimodal.data_types import AudioContent, ChatMLSample, Message
        from boson_multimodal.dataset.chatml_dataset import ChatMLDatasetSample, prepare_chatml_sample
        from boson_multimodal.model.higgs_audio.utils import revert_delay_pattern

        if self._model is None:
            raise RuntimeError("Adapter not initialized - call initialize() first")

        voice_config = DEFAULT_VOICE_CONFIG.copy()
        voice_config.update(kwargs)

        # Get context tokens if provided (list of (text, audio_tokens) tuples)
        context_tokens_b64 = kwargs.get("context_tokens")
        context_items: list[tuple[str, torch.Tensor]] = []
        if context_tokens_b64:
            context_items = deserialize_context_tokens(context_tokens_b64)
            log.debug(f"Received {len(context_items)} context items")

        # Build system message
        scene_desc = voice_config.get("scene_description", "")
        system_prompt = voice_config.get("system_prompt", "Generate audio following instruction.")
        if scene_desc:
            system_prompt = f"{system_prompt}\n\n<|scene_desc_start|>\n{scene_desc}\n<|scene_desc_end|>"

        # Get reference voice
        ref_preset = kwargs.get("ref_preset")
        if ref_preset and ref_preset in self._voice_presets:
            ref_audio_ids, ref_transcript = self._voice_presets[ref_preset]
        else:
            # Try to get from raw audio in kwargs
            ref_audio_b64 = kwargs.get("ref_audio")
            ref_transcript = kwargs.get("ref_audio_transcript")
            if ref_audio_b64 and ref_transcript:
                # Decode and tokenize reference audio
                import tempfile

                wav_bytes = base64.b64decode(ref_audio_b64)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(wav_bytes)
                    ref_audio_ids = self._audio_tokenizer.encode(f.name)
                os.unlink(f.name)
            else:
                raise ValueError("No reference voice provided (ref_preset or ref_audio+ref_audio_transcript required)")

        # Build messages for chat template
        base_messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=ref_transcript),
            Message(role="assistant", content=AudioContent(audio_url="placeholder")),
        ]

        # Add context messages with actual text (for proper chat templating)
        context_messages = []
        for ctx_text, _ in context_items:
            context_messages.append(Message(role="user", content=ctx_text))
            context_messages.append(Message(role="assistant", content=AudioContent(audio_url="")))

        # Add current text request
        all_messages = base_messages + context_messages + [Message(role="user", content=text)]

        # Prepare input tokens
        chatml_sample = ChatMLSample(messages=all_messages)
        input_tokens, _, _, _ = prepare_chatml_sample(chatml_sample, self._tokenizer)

        # Add assistant header
        postfix = self._tokenizer.encode("<|start_header_id|>assistant<|end_header_id|>\n\n", add_special_tokens=False)
        input_tokens.extend(postfix)

        # Combine reference audio + context audio IDs
        context_audio_ids = [tokens for _, tokens in context_items]
        all_audio_ids = [ref_audio_ids] + context_audio_ids

        # Build ChatMLDatasetSample with audio_ids tensors
        curr_sample = ChatMLDatasetSample(
            input_ids=torch.LongTensor(input_tokens),
            label_ids=None,
            audio_ids_concat=torch.concat([ele.cpu() for ele in all_audio_ids], dim=1) if all_audio_ids else None,
            audio_ids_start=torch.cumsum(
                torch.tensor([0] + [ele.shape[1] for ele in all_audio_ids], dtype=torch.long), dim=0
            )[:-1]  # slice off trailing total length - we need start indices only
            if all_audio_ids
            else None,
            audio_waveforms_concat=None,
            audio_waveforms_start=None,
            audio_sample_rate=None,
            audio_speaker_indices=None,
        )

        # Collate and move to device
        batch_data = self._collator([curr_sample])
        batch = asdict(batch_data)
        device = self._model.device
        for k, v in batch.items():
            if isinstance(v, torch.Tensor):
                batch[k] = v.contiguous().to(device)

        # Reset KV caches
        for kv_cache in self._kv_caches.values():
            kv_cache.reset()

        # Generate
        seed = voice_config.get("seed")
        with torch.inference_mode():
            outputs = self._model.generate(
                **batch,
                max_new_tokens=2048,
                use_cache=True,
                do_sample=True,
                temperature=voice_config.get("temperature", 0.3),
                top_k=voice_config.get("top_k", 50),
                top_p=voice_config.get("top_p", 0.95),
                past_key_values_buckets=self._kv_caches,
                ras_win_len=7,
                ras_win_max_num_repeat=2,
                stop_strings=["<|end_of_text|>", "<|eot_id|>"],
                tokenizer=self._tokenizer,
                seed=seed,
            )

        # Process output audio tokens
        step_audio_out_ids_l = []
        for ele in outputs[1]:
            audio_out_ids = ele
            if self._config.use_delay_pattern:
                audio_out_ids = revert_delay_pattern(audio_out_ids)
            step_audio_out_ids_l.append(audio_out_ids.clip(0, self._audio_tokenizer.codebook_size - 1)[:, 1:-1])

        audio_out_ids = torch.concat(step_audio_out_ids_l, dim=1)

        # Store for caller to retrieve
        self._last_audio_tokens = audio_out_ids

        # Free VRAM before decode
        torch.cuda.empty_cache()

        # Decode to waveform
        waveform = self._audio_tokenizer.decode(audio_out_ids.unsqueeze(0))[0, 0]

        # Convert float32 waveform to int16 PCM bytes
        audio_int16 = (waveform * 32767).clip(-32768, 32767).astype(np.int16)
        return base64.b64encode(audio_int16.tobytes()).decode("utf-8")

    def get_audio_tokens(self) -> str | None:
        """Get serialized audio tokens from last synthesis (for context accumulation)."""
        if self._last_audio_tokens is None:
            return None
        return serialize_audio_tokens(self._last_audio_tokens)

    def calculate_duration_ms(self, audio_bytes: bytes) -> int:
        # 24000 Hz, 1 channel, 2 bytes per sample (16-bit PCM)
        return int(len(audio_bytes) / (24_000 * 1 * 2) * 1000)
