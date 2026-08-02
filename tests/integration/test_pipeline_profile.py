"""
Integration tests for profile forwarding through CallCopilotPipeline._handle_trigger.

We test _handle_trigger directly with fake STT/LLM to verify:
- conservative_mode flows from profile heuristics to llm.respond()
- system_prompt_addon flows from profile to llm.respond()
- profile change mid-call applies to next block only
- create_call_session called with correct profile_id (via start() path)

The heavy dependencies (RAGStore, openai) are already stubbed by conftest.py.
"""

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import AsyncIterator

from src.core.interfaces import (
    TriggerEvent, TriggerReason, LLMResponse,
    AudioSource, STTProvider, VoiceActivityDetector, TriggerDetector, OutputSink,
    TranscriptSegment,
)
from src.core.pipeline import CallCopilotPipeline
from src.profiles.models import CallProfile, ProfileHeuristics, ResponseMode


# ── Profile fixtures ─────────────────────────────────────────────────────────

DISCOURSE_ONLY_PROFILE = CallProfile(
    id="presentacion",
    name="Presentación",
    description="",
    system_prompt_addon="Addon text for presentation.",
    heuristics=ProfileHeuristics(
        discourse_markers=["¿Listo?", "¿Sí?", "¿Verdad?", "¿Ok?"],
        require_real_question=True,
    ),
    response_mode=ResponseMode.copilot,
)

PERMISSIVE_PROFILE = CallProfile(
    id="entrevista",
    name="Entrevista",
    description="",
    system_prompt_addon="Addon for interview.",
    heuristics=ProfileHeuristics(
        discourse_markers=[],
        require_real_question=False,
    ),
    response_mode=ResponseMode.copilot,
)

NO_ADDON_PROFILE = CallProfile(
    id="reunion",
    name="Reunión",
    description="",
    system_prompt_addon="",
    heuristics=ProfileHeuristics(
        discourse_markers=["¿Sí?", "¿Ok?"],
        require_real_question=True,
    ),
    response_mode=ResponseMode.copilot,
)

SILENT_PROFILE = CallProfile(
    id="presentacion_silent",
    name="Presentación Silent",
    description="",
    system_prompt_addon="",
    heuristics=ProfileHeuristics(
        discourse_markers=["¿Listo?", "¿Sí?", "¿Verdad?", "¿Ok?"],
        require_real_question=True,
    ),
    response_mode=ResponseMode.silent,
)

EXPLAIN_PROFILE = CallProfile(
    id="soporte_explain",
    name="Soporte Explain",
    description="",
    system_prompt_addon="",
    heuristics=ProfileHeuristics(
        discourse_markers=[],
        require_real_question=False,
    ),
    response_mode=ResponseMode.explain,
    model="gpt-5.4-mini",
)

MODEL_OVERRIDE_PROFILE = CallProfile(
    id="custom_model",
    name="Custom Model",
    description="",
    system_prompt_addon="",
    heuristics=ProfileHeuristics(discourse_markers=[], require_real_question=False),
    response_mode=ResponseMode.copilot,
    model="gpt-5.6-terra",
)


# ── Fake LLM that records respond() arguments ─────────────────────────────────

class FakeLLM:
    """Records every call to respond() for assertion."""

    def __init__(self):
        self.calls: list[dict] = []

    async def respond(
        self,
        context: str,
        trigger: TriggerEvent,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ) -> AsyncIterator[LLMResponse]:
        self.calls.append({
            "context": context,
            "trigger": trigger,
            "system_prompt_addon": system_prompt_addon,
            "conservative_mode": conservative_mode,
            "response_mode": response_mode,
            "model_override": model_override,
        })
        yield LLMResponse(text="fake response", is_partial=False)


# ── Configurable fake LLM for meta-response tests ─────────────────────────────

class ConfigurableFakeLLM:
    """FakeLLM that returns a caller-specified response text."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls: list[dict] = []

    async def respond(
        self,
        context: str,
        trigger: TriggerEvent,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ) -> "AsyncIterator[LLMResponse]":
        self.calls.append({
            "context": context,
            "response_mode": response_mode,
        })
        yield LLMResponse(text=self.response_text, is_partial=False)


# ── Fake output sink ──────────────────────────────────────────────────────────

class FakeOutput:
    def __init__(self):
        self.emissions: list[LLMResponse] = []

    async def emit(self, response: LLMResponse) -> None:
        self.emissions.append(response)


# ── Minimal pipeline builder ──────────────────────────────────────────────────

def _build_pipeline(profile: CallProfile, min_words: int = 5) -> tuple[CallCopilotPipeline, FakeLLM, FakeOutput]:
    fake_llm = FakeLLM()
    fake_output = FakeOutput()
    # Minimal stubs — we only call _handle_trigger directly
    pipeline = CallCopilotPipeline(
        audio_source=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        trigger=MagicMock(),
        llm=fake_llm,
        output=fake_output,
        llm_enabled=True,
        initial_context="",
        min_substantial_words=min_words,
        active_profile=profile,
    )
    return pipeline, fake_llm, fake_output


def _set_block(pipeline: CallCopilotPipeline, text: str) -> None:
    """Populate the current block so _handle_trigger has data to process."""
    pipeline._current_block = text.split()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPipelineProfileConservativeMode:
    def test_discourse_marker_block_sets_conservative_mode(self):
        """Discourse-only block + require_real_question=True → respond receives conservative_mode=True."""
        pipeline, fake_llm, _ = _build_pipeline(DISCOURSE_ONLY_PROFILE, min_words=1)
        # Block: only discourse markers
        _set_block(pipeline, "¿Listo? ¿Sí?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1
        assert fake_llm.calls[0]["conservative_mode"] is True

    def test_real_question_block_not_conservative(self):
        """Real question block → respond receives conservative_mode=False."""
        pipeline, fake_llm, _ = _build_pipeline(DISCOURSE_ONLY_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo implementarías la autenticación OAuth?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1
        assert fake_llm.calls[0]["conservative_mode"] is False

    def test_permissive_profile_never_conservative(self):
        """Profile with require_real_question=False → always conservative_mode=False."""
        pipeline, fake_llm, _ = _build_pipeline(PERMISSIVE_PROFILE, min_words=1)
        _set_block(pipeline, "¿Listo? ¿Sí?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1
        assert fake_llm.calls[0]["conservative_mode"] is False


class TestPipelineProfileAddon:
    def test_non_empty_addon_forwarded_to_llm(self):
        """Profile addon is passed to llm.respond() as system_prompt_addon."""
        pipeline, fake_llm, _ = _build_pipeline(DISCOURSE_ONLY_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo implementarías la autenticación OAuth?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["system_prompt_addon"] == "Addon text for presentation."

    def test_empty_addon_forwarded_as_empty_string(self):
        """Profile with no addon passes empty string to llm.respond()."""
        pipeline, fake_llm, _ = _build_pipeline(NO_ADDON_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo funciona el protocolo TCP?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["system_prompt_addon"] == ""

    def test_no_profile_passes_empty_addon(self):
        """Without an active profile, addon defaults to empty string."""
        fake_llm = FakeLLM()
        fake_output = FakeOutput()
        pipeline = CallCopilotPipeline(
            audio_source=MagicMock(),
            vad=MagicMock(),
            stt=MagicMock(),
            trigger=MagicMock(),
            llm=fake_llm,
            output=fake_output,
            llm_enabled=True,
            initial_context="",
            min_substantial_words=1,
            active_profile=None,
        )
        _set_block(pipeline, "¿Cómo funciona el protocolo TCP?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["system_prompt_addon"] == ""
        assert fake_llm.calls[0]["conservative_mode"] is False


class TestPipelineProfileMidCallChange:
    def test_profile_change_applies_on_next_block(self):
        """Profile is snapshotted at pipeline creation; changing _active_profile
        mid-call takes effect on the next _handle_trigger call."""
        pipeline, fake_llm, _ = _build_pipeline(PERMISSIVE_PROFILE, min_words=1)

        # First block with PERMISSIVE profile — addon = "Addon for interview."
        _set_block(pipeline, "¿Cómo funciona OAuth?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["system_prompt_addon"] == "Addon for interview."

        # Simulate profile change mid-call (as a TUI would do by swapping the ref)
        pipeline._active_profile = DISCOURSE_ONLY_PROFILE

        # Second block — must use the new profile addon
        _set_block(pipeline, "¿Cuál es la ventaja de usar microservicios aquí?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[1]["system_prompt_addon"] == "Addon text for presentation."

    def test_prior_block_not_reprocessed(self):
        """After a profile change, only the new block is processed with the new profile."""
        pipeline, fake_llm, _ = _build_pipeline(PERMISSIVE_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo funciona OAuth?")
        asyncio.run(pipeline._handle_trigger())
        # Change profile AFTER the block was processed
        pipeline._active_profile = DISCOURSE_ONLY_PROFILE
        # Total LLM calls must still be 1 (prior block was not reprocessed)
        assert len(fake_llm.calls) == 1


class TestPipelineProfileId:
    def test_create_call_session_called_with_profile_id(self, tmp_path, monkeypatch):
        """start() calls create_call_session with the active profile's id."""
        import src.db.database as db_module
        db_path = tmp_path / "test.db"
        monkeypatch.setattr(db_module, "DB_PATH", db_path)
        db_module.init_db()

        created_sessions: list[dict] = []
        original_create = db_module.create_call_session

        def tracking_create(**kwargs):
            created_sessions.append(kwargs)
            return original_create(**kwargs)

        monkeypatch.setattr(db_module, "create_call_session", tracking_create)

        # Build a pipeline that uses a real openai_client so start() calls create_call_session
        fake_llm = FakeLLM()
        fake_output = FakeOutput()

        # Fake audio/stt that immediately stop
        fake_audio = AsyncMock()
        fake_audio.start = AsyncMock()
        fake_audio.stop = AsyncMock()

        async def empty_stream():
            return
            yield

        fake_audio.stream = MagicMock(return_value=empty_stream())

        fake_stt = AsyncMock()
        fake_stt.connect = AsyncMock()
        fake_stt.close = AsyncMock()

        async def empty_transcripts():
            return
            yield

        fake_stt.transcripts = MagicMock(return_value=empty_transcripts())
        fake_stt.send_audio = AsyncMock()

        # Provide a fake openai_client so the DB path is exercised
        fake_openai_client = MagicMock()

        # Mock RAGStore so chromadb is not needed
        with patch("src.core.pipeline.RAGStore") as MockRAG:
            mock_rag_instance = MagicMock()
            mock_rag_instance.collection_name = "test_collection"
            mock_rag_instance.add_segment = AsyncMock()
            mock_rag_instance.search = AsyncMock(return_value=[])
            MockRAG.return_value = mock_rag_instance

            pipeline = CallCopilotPipeline(
                audio_source=fake_audio,
                vad=MagicMock(),
                stt=fake_stt,
                trigger=MagicMock(),
                llm=fake_llm,
                output=fake_output,
                llm_enabled=False,
                initial_context="ctx",
                min_substantial_words=5,
                openai_client=fake_openai_client,
                active_profile=DISCOURSE_ONLY_PROFILE,
            )

            asyncio.run(pipeline.start())

        assert len(created_sessions) == 1
        assert created_sessions[0]["profile_id"] == "presentacion"


class TestPipelineSilentMode:
    def test_silent_discourse_only_block_skips_llm(self):
        """Silent mode + discourse-only block (no ?) → LLM NOT called."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        # Block contains only discourse markers — no real question
        _set_block(pipeline, "¿Listo? ¿Sí? ¿Verdad? ¿Ok? ¿Sí? ¿Listo?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 0

    def test_silent_long_explanatory_block_no_question_mark_skips_llm(self):
        """Silent mode + long explanatory block (no ?) → LLM NOT called."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        long_block = (
            "Básicamente la arquitectura se divide en tres capas principales "
            "que permiten separar responsabilidades y facilitar el mantenimiento "
            "del código a largo plazo en equipos distribuidos de desarrollo."
        )
        _set_block(pipeline, long_block)
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 0

    def test_silent_long_block_with_question_mark_rhetorical_skips_llm(self):
        """Silent mode + long block with ? (>= 25 words, rhetorical) → LLM NOT called."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        long_block = (
            "¿Cómo funciona exactamente el sistema de autenticación que están usando "
            "en producción actualmente y cuáles son las ventajas principales de ese "
            "enfoque técnico comparado con las alternativas disponibles en el mercado?"
        )
        assert len(long_block.split()) >= 25
        _set_block(pipeline, long_block)
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 0

    def test_silent_short_question_with_question_word_calls_llm(self):
        """Silent mode + short block with ? AND question word (< 25 words) → LLM IS called."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo implementarías esto?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1

    def test_silent_real_question_calls_llm(self):
        """Silent mode + real question → LLM IS called."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo implementarías la autenticación OAuth?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1

    def test_silent_response_mode_forwarded_to_llm(self):
        """When LLM is called in silent mode, response_mode='silent' is passed."""
        pipeline, fake_llm, _ = _build_pipeline(SILENT_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cuál sería la mejor estrategia aquí?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["response_mode"] == "silent"

    def test_copilot_mode_long_block_still_calls_llm(self):
        """Copilot mode with a long block (no ?) — compute_conservative_mode still used, LLM called."""
        pipeline, fake_llm, _ = _build_pipeline(PERMISSIVE_PROFILE, min_words=1)
        long_block = (
            "Básicamente la arquitectura se divide en tres capas principales "
            "que permiten separar responsabilidades y facilitar el mantenimiento "
            "del código a largo plazo en equipos distribuidos de desarrollo."
        )
        _set_block(pipeline, long_block)
        asyncio.run(pipeline._handle_trigger())
        # copilot mode does NOT gate on is_silent_mode_question — LLM is called
        assert len(fake_llm.calls) == 1


class TestPipelineExplainMode:
    def test_explain_mode_always_calls_llm(self):
        """Explain mode does not gate — LLM is called for any substantial block."""
        pipeline, fake_llm, _ = _build_pipeline(EXPLAIN_PROFILE, min_words=1)
        _set_block(pipeline, "El protocolo TCP garantiza la entrega de paquetes mediante ACK")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.calls) == 1

    def test_explain_response_mode_forwarded_to_llm(self):
        """Explain profile passes response_mode='explain' to llm.respond()."""
        pipeline, fake_llm, _ = _build_pipeline(EXPLAIN_PROFILE, min_words=1)
        _set_block(pipeline, "El protocolo TCP garantiza la entrega de paquetes mediante ACK")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["response_mode"] == "explain"


class TestPipelineModelOverride:
    def test_model_override_forwarded_to_llm(self):
        """Profile.model is passed as model_override to llm.respond()."""
        pipeline, fake_llm, _ = _build_pipeline(MODEL_OVERRIDE_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cuáles son las ventajas de los microservicios en este caso?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["model_override"] == "gpt-5.6-terra"

    def test_empty_model_forwarded_as_empty_string(self):
        """Profile.model='' passes '' as model_override (use pipeline default)."""
        pipeline, fake_llm, _ = _build_pipeline(PERMISSIVE_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cómo funciona el patrón de repositorio?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["model_override"] == ""


def _build_pipeline_with_llm(
    profile: CallProfile, llm, min_words: int = 5
) -> tuple[CallCopilotPipeline, FakeOutput]:
    """Build a pipeline injecting an arbitrary LLM (used for meta-response tests)."""
    fake_output = FakeOutput()
    pipeline = CallCopilotPipeline(
        audio_source=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        trigger=MagicMock(),
        llm=llm,
        output=fake_output,
        llm_enabled=True,
        initial_context="",
        min_substantial_words=min_words,
        active_profile=profile,
    )
    return pipeline, fake_output


class FakeLLMWithProviderId(FakeLLM):
    """FakeLLM exposing a provider_id, so pipeline._handle_trigger's
    getattr(self.llm, "provider_id", None) resolves to a real value instead
    of the None it gets from the plain FakeLLM used elsewhere in this file."""

    def __init__(self, provider_id: str):
        super().__init__()
        self.provider_id = provider_id


class TestPipelineOverrideValidation:
    """Task 9.2: offline override validation wired into _handle_trigger."""

    def test_foreign_provider_override_dropped_with_warning(self, caplog):
        """Profile model is a gpt id, active backend is claude → override
        dropped (forwarded as ''), warning logged, call still emitted."""
        llm = FakeLLMWithProviderId(provider_id="claude")
        pipeline, fake_output = _build_pipeline_with_llm(MODEL_OVERRIDE_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cuáles son las ventajas de los microservicios en este caso?")
        with caplog.at_level(logging.WARNING):
            asyncio.run(pipeline._handle_trigger())
        assert len(llm.calls) == 1
        assert llm.calls[0]["model_override"] == ""
        assert any("gpt-5.6-terra" in r.message for r in caplog.records)
        assert len(fake_output.emissions) == 1  # call proceeds, response is emitted normally

    def test_matching_provider_override_kept(self):
        """Profile model is a gpt id, active backend is gpt → override forwarded unchanged."""
        llm = FakeLLMWithProviderId(provider_id="gpt")
        pipeline, fake_output = _build_pipeline_with_llm(MODEL_OVERRIDE_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cuáles son las ventajas de los microservicios en este caso?")
        asyncio.run(pipeline._handle_trigger())
        assert llm.calls[0]["model_override"] == "gpt-5.6-terra"

    def test_no_provider_id_attribute_forwards_unchanged(self):
        """Existing FakeLLM (no provider_id) — getattr-guarded None means no
        validation is attempted; override is forwarded unchanged (backward
        compatible with every other test double in this file)."""
        pipeline, fake_llm, _ = _build_pipeline(MODEL_OVERRIDE_PROFILE, min_words=1)
        _set_block(pipeline, "¿Cuáles son las ventajas de los microservicios en este caso?")
        asyncio.run(pipeline._handle_trigger())
        assert fake_llm.calls[0]["model_override"] == "gpt-5.6-terra"


class TestPipelineSilentModeMetaResponseFilter:
    """Fix 1: silent mode buffers LLM response and filters meta-instructions."""

    def test_silent_mode_meta_response_no_respondas_not_emitted(self):
        """Silent mode + LLM returns 'No respondas.' → output NOT emitted."""
        llm = ConfigurableFakeLLM("No respondas.")
        pipeline, fake_output = _build_pipeline_with_llm(SILENT_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cómo funciona?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_output.emissions) == 0

    def test_silent_mode_meta_response_skip_not_emitted(self):
        """Silent mode + LLM returns 'skip' (case-insensitive) → output NOT emitted."""
        llm = ConfigurableFakeLLM("SKIP")
        pipeline, fake_output = _build_pipeline_with_llm(SILENT_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Qué herramienta usan?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_output.emissions) == 0

    def test_silent_mode_meta_response_empty_not_emitted(self):
        """Silent mode + LLM returns '' → output NOT emitted."""
        llm = ConfigurableFakeLLM("")
        pipeline, fake_output = _build_pipeline_with_llm(SILENT_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cuál es la solución?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_output.emissions) == 0

    def test_silent_mode_actual_content_is_emitted(self):
        """Silent mode + LLM returns real content → output IS emitted."""
        llm = ConfigurableFakeLLM("Usa OAuth2 con PKCE para mayor seguridad.")
        pipeline, fake_output = _build_pipeline_with_llm(SILENT_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cómo implementas la autenticación?")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_output.emissions) == 1
        assert fake_output.emissions[0].text == "Usa OAuth2 con PKCE para mayor seguridad."

    def test_non_silent_mode_no_filtering_streams_normally(self):
        """Non-silent mode (copilot) + any LLM response → emitted without filtering."""
        llm = ConfigurableFakeLLM("No respondas.")
        pipeline, fake_output = _build_pipeline_with_llm(PERMISSIVE_PROFILE, llm, min_words=1)
        _set_block(pipeline, "¿Cómo funciona OAuth?")
        asyncio.run(pipeline._handle_trigger())
        # copilot mode streams directly — no meta-filter, so "No respondas." IS emitted
        assert len(fake_output.emissions) == 1
        assert fake_output.emissions[0].text == "No respondas."
