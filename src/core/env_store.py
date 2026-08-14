"""
Único escritor de .env — la contraparte de escritura de
src/core/config_defaults.py, deliberadamente separada de él para que el hot
path del pipeline nunca arrastre dotenv ni I/O de archivos de forma
transitiva.

Responsabilidades:
- ensure_env_file(): crea .env a partir de example.env si no existe, con
  permisos 0600 (puede contener API keys).
- write_values(): persiste solo las claves que cambiaron, vía
  dotenv.set_key() (preserva comentarios y líneas ajenas), y refresca el
  entorno del proceso en memoria con load_dotenv(override=True).
"""

import shutil
import stat
from pathlib import Path

from src.core.paths import app_home

ENV_PATH = app_home() / ".env"
EXAMPLE_ENV_PATH = Path("example.env")  # shipped template — always repo-relative

_ENV_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600 — puede contener API keys


def ensure_env_file(env_path: Path | None = None, example_path: Path | None = None) -> None:
    """
    Crea env_path si no existe, seedeado desde example_path (o vacío si
    example_path tampoco existe). No-op si env_path ya existe — nunca
    pisa un .env real del usuario.
    """
    env_path = Path(env_path) if env_path is not None else ENV_PATH
    example_path = Path(example_path) if example_path is not None else EXAMPLE_ENV_PATH

    if env_path.exists():
        return

    if example_path.exists():
        shutil.copyfile(example_path, env_path)
    else:
        env_path.touch()

    env_path.chmod(_ENV_FILE_MODE)


def write_values(values: dict, env_path: Path | None = None) -> None:
    """
    Persiste cada (clave, valor) de `values` en env_path.

    - Crea env_path desde example.env si todavía no existe.
    - Solo reescribe la línea de una clave si su valor realmente cambió
      (dotenv.set_key reformatea la línea incluso con el mismo valor —
      p.ej. LLM_BACKEND=gpt → LLM_BACKEND='gpt' — así que comparamos contra
      el valor actual en disco antes de llamar a set_key).
    - Refresca el entorno del proceso en memoria al final, para que los
      cambios de scope NEXT_CALL/NEXT_VIDEO tomen efecto sin reiniciar.
    """
    env_path = Path(env_path) if env_path is not None else ENV_PATH

    import dotenv

    ensure_env_file(env_path)

    current = dotenv.dotenv_values(str(env_path))
    for key, value in values.items():
        if current.get(key) == value:
            continue
        dotenv.set_key(str(env_path), key, value)

    dotenv.load_dotenv(str(env_path), override=True)
