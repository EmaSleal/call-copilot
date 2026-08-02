"""
Persiste la sesión completa en un archivo de texto plano.
Cada sesión genera un ID basado en timestamp y escribe en whisper-text/<id>.txt.
El archivo interleava transcripts y respuestas para poder revisar
la conversación completa con las sugerencias del copiloto identificadas.
"""

from datetime import datetime
from pathlib import Path


class SessionLogger:
    def __init__(self, base_dir: str = "whisper-text", initial_context: str = ""):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(base_dir)
        out_dir.mkdir(exist_ok=True)

        self._file = open(out_dir / f"{self.session_id}.txt", "w", encoding="utf-8")
        self._write(f"=== Sesión {self.session_id} ===\n")
        if initial_context:
            self._write(f"Contexto inicial: {initial_context}\n")
        self._write("\n")

    def log_transcript(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._write(f"[{ts}] {text}\n")

    def log_response(self, context: str, response: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._write(
            f"\n[{ts}] CONTEXTO:\n{context}\n\n"
            f"[{ts}] RESPUESTA:\n{response}\n\n"
            f"{'─' * 40}\n\n"
        )

    def close(self) -> None:
        self._file.close()

    def _write(self, text: str) -> None:
        self._file.write(text)
        self._file.flush()
