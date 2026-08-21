from __future__ import annotations

import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


# Format “audit-friendly” : inclut l’emplacement dans le code (filename:lineno:function)
DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d:%(funcName)s | %(message)s"


class SizedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Handler de logs avec rotation :
    - par temps (ex: quotidien à minuit)
    - et par taille (max_bytes)

    En plus, ce handler applique une rétention en jours (`retention_days`) :
    suppression des fichiers de logs plus anciens que N jours.
    """

    def __init__(
        self,
        filename: str | Path,
        *,
        when: str = "midnight",
        interval: int = 1,
        utc: bool = False,
        encoding: str = "utf-8",
        max_bytes: int = 10_000_000,  # < 10 Mo
        retention_days: int = 7,
    ) -> None:
        """Crée un handler avec rotation par temps + taille et rétention en jours."""
        self.max_bytes = int(max_bytes or 0)
        self.retention_days = int(retention_days or 0)

        # On gère nous-mêmes la rétention en jours, donc backupCount=0
        super().__init__(
            filename=str(filename),
            when=when,
            interval=interval,
            backupCount=0,
            utc=utc,
            encoding=encoding,
            delay=False,
        )

    def shouldRollover(self, record: logging.LogRecord) -> int:  # type: ignore[override]
        """Détermine si une rotation doit avoir lieu (taille ou temps)."""
        # 1) rotation par taille (comme RotatingFileHandler)
        if self.max_bytes > 0:
            if self.stream is None:
                self.stream = self._open()

            msg = f"{self.format(record)}\n"
            try:
                msg_len = len(msg.encode(self.encoding or "utf-8", errors="replace"))
            except Exception:
                msg_len = len(msg)

            if self.stream.tell() + msg_len >= self.max_bytes:
                return 1

        # 2) rotation par temps (comportement TimedRotatingFileHandler)
        return 1 if super().shouldRollover(record) else 0

    def _available_rollover_filename(self, dfn: str) -> str:
        """Évite d'écraser un fichier si plusieurs rotations ont lieu le même jour."""
        if not os.path.exists(dfn):
            return dfn

        i = 1
        while True:
            candidate = f"{dfn}.{i}"
            if not os.path.exists(candidate):
                return candidate
            i += 1

    def _cleanup_old_files(self) -> None:
        """Supprime les fichiers de logs plus anciens que `retention_days`."""
        if self.retention_days <= 0:
            return

        base = Path(self.baseFilename)
        cutoff = time.time() - (self.retention_days * 86400)

        for p in base.parent.glob(base.name + ".*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                # Ne jamais casser l'exécution si le nettoyage échoue
                pass

    def doRollover(self) -> None:  # type: ignore[override]
        """
        Rotation inspirée de TimedRotatingFileHandler, avec 2 adaptations :
        - ne pas écraser en cas de rotations multiples le même jour
        - nettoyage par rétention en jours après rollover
        """
        if self.stream:
            try:
                self.stream.close()
            finally:
                self.stream = None  # type: ignore[assignment]

        current_time = int(time.time())
        t = self.rolloverAt - self.interval
        time_tuple = time.gmtime(t) if self.utc else time.localtime(t)

        dfn_base = self.rotation_filename(
            self.baseFilename + "." + time.strftime(self.suffix, time_tuple)
        )
        dfn = self._available_rollover_filename(dfn_base)

        if os.path.exists(self.baseFilename):
            self.rotate(self.baseFilename, dfn)

        # Recalcule le prochain rollover
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at

        # Rouvre le fichier de log
        if not self.delay:
            self.stream = self._open()

        # Nettoyage (rétention)
        self._cleanup_old_files()


def _tune_third_party_loggers(root_level: int) -> None:
    """
    Réduit le bruit des librairies tierces au niveau INFO.

    Objectif :
      - Garder les traces HTTP uniquement en DEBUG
      - Éviter de polluer les logs INFO avec les lignes de requêtes httpx/httpcore
    """
    # Si l'utilisateur a demandé DEBUG, on autorise les traces HTTP.
    # Sinon, on les rend silencieuses (WARNING+).
    if root_level <= logging.DEBUG:
        http_level = logging.DEBUG
    else:
        http_level = logging.WARNING

    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(http_level)


class _MinLevelByLoggerPrefixFilter(logging.Filter):
    """Filtre les logs en dessous de `min_level` pour certains préfixes de loggers."""

    def __init__(self, prefixes: tuple[str, ...], min_level: int):
        """Construit un filtre qui impose un niveau minimal sur certains préfixes."""
        super().__init__()
        self.prefixes = prefixes
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        """Retourne True si le record doit être conservé, sinon False."""
        for p in self.prefixes:
            if record.name == p or record.name.startswith(p + "."):
                return record.levelno >= self.min_level
        return True


def configure_logging(
    *,
    level: str = "INFO",
    log_to_stdout: bool = True,
    log_file: Optional[str | Path] = None,
    fmt: str = DEFAULT_LOG_FORMAT,
    reset_handlers: bool = True,
) -> None:
    """
    Configure les handlers du logging root.

    Arguments :
        level: Nom du niveau de logs (ex. "DEBUG", "INFO", "WARNING", "ERROR").
        log_to_stdout: Si True, les logs sont écrits sur stdout.
        log_file: Si défini, les logs sont aussi écrits dans ce fichier.
        fmt: Format de log (formatter).
        reset_handlers: Si True, supprime d'abord les handlers existants du root (évite les doublons).

    Notes :
        - Utilise stdout (pas stderr) pour mieux coller à la sortie “normale” d'une CLI.
        - En notebook/app, vous pouvez préférer `reset_handlers=False` si votre environnement configure déjà le logging.
    """
    level_name = (level or "INFO").upper()
    level_value = getattr(logging, level_name, None)
    if not isinstance(level_value, int):
        raise ValueError(f"Niveau de log invalide : {level!r}")

    root = logging.getLogger()
    root.setLevel(level_value)

    # Réinitialise les handlers pour éviter les doublons sur exécutions répétées (comportement par défaut de la CLI)
    if reset_handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    formatter = logging.Formatter(fmt)

    if log_to_stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(level_value)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Rotation par temps + taille (par défaut : <10 Mo, rétention 7 jours)
        fh = SizedTimedRotatingFileHandler(
            path,
            when="midnight",
            interval=1,
            utc=False,
            max_bytes=10_000_000,  # < 10 Mo
            retention_days=7,
        )
        fh.setLevel(level_value)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _tune_third_party_loggers(level_value)

    # Garantie forte : hors DEBUG, empêcher les lignes INFO de httpx/httpcore de “fuiter” dans les handlers.
    if level_value > logging.DEBUG:
        noise_filter = _MinLevelByLoggerPrefixFilter(
            ("httpx", "httpcore"), logging.WARNING
        )
        for h in list(root.handlers):
            h.addFilter(noise_filter)


def parse_env_bool(value: Optional[str]) -> Optional[bool]:
    """
    Parse une variable d’environnement de type booléen.

    Retourne :
        - True / False si `value` est définie et reconnue
        - None si `value` est None ou vide
    """
    if value is None:
        return None
    v = value.strip().lower()
    if v == "":
        return None
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return None


def configure_logging_from_env(
    *,
    default_level: str = "INFO",
    default_log_to_stdout: bool = True,
    default_log_file: Optional[str | Path] = None,
    fmt: str = DEFAULT_LOG_FORMAT,
    reset_handlers: bool = True,
) -> bool:
    """
    Configure le logging à partir des variables d’environnement (opt-in).

    Variables d’environnement :
      - SME_LOG_LEVEL : ex. DEBUG/INFO/WARNING/ERROR
      - VSME_LOG_FILE : chemin vers un fichier de log (optionnel)
      - VSME_LOG_STDOUT : 1/0, true/false, yes/no, on/off

    Comportement :
      - Si aucune de ces variables n’est définie, ne fait rien et retourne False.
      - Si au moins une est définie, configure le logging et retourne True.
    """
    env_level = os.getenv("SME_LOG_LEVEL")
    env_file = os.getenv("VSME_LOG_FILE")
    env_stdout = parse_env_bool(os.getenv("VSME_LOG_STDOUT"))

    any_set = any(
        v is not None and str(v).strip() != ""
        for v in (env_level, env_file, os.getenv("VSME_LOG_STDOUT"))
    )
    if not any_set:
        return False

    configure_logging(
        level=(env_level or default_level),
        log_to_stdout=(env_stdout if env_stdout is not None else default_log_to_stdout),
        log_file=(env_file or default_log_file),
        fmt=fmt,
        reset_handlers=reset_handlers,
    )
    return True
