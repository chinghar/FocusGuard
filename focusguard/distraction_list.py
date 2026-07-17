"""DistractionListManager: the editable list of distracting apps/domains.

Wraps the `distractions.apps` / `distractions.domains` config sections.
Every mutation persists immediately via config.save_config, so the
menu-bar UI and config.json on disk never drift apart.
"""

from __future__ import annotations

from typing import Any

from focusguard.config import save_config


def normalize_domain(domain: str) -> str:
    domain = domain.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    domain = domain.removeprefix("www.")
    return domain


def normalize_app(app_name: str) -> str:
    return app_name.strip()


class DistractionListManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        section = config["distractions"]
        self._apps: set[str] = {normalize_app(a) for a in section["apps"]}
        self._domains: set[str] = {normalize_domain(d) for d in section["domains"]}

    @property
    def apps(self) -> list[str]:
        return sorted(self._apps)

    @property
    def domains(self) -> list[str]:
        return sorted(self._domains)

    def is_distraction_app(self, app_name: str) -> bool:
        return app_name in self._apps

    def is_distraction_domain(self, url: str) -> bool:
        domain = normalize_domain(url)
        return any(domain == d or domain.endswith("." + d) for d in self._domains)

    def add_app(self, app_name: str) -> None:
        name = normalize_app(app_name)
        if not name:
            return
        self._apps.add(name)
        self._persist()

    def remove_app(self, app_name: str) -> None:
        self._apps.discard(app_name)
        self._persist()

    def add_domain(self, domain: str) -> None:
        normalized = normalize_domain(domain)
        if not normalized:
            return
        self._domains.add(normalized)
        self._persist()

    def remove_domain(self, domain: str) -> None:
        self._domains.discard(domain)
        self._persist()

    def _persist(self) -> None:
        self._config["distractions"]["apps"] = sorted(self._apps)
        self._config["distractions"]["domains"] = sorted(self._domains)
        save_config(self._config)
