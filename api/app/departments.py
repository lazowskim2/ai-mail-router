"""
Loads the list of departments the router can forward messages to.

Departments live in a YAML file (see departments.yaml in the repo root) so that
each company can describe its own structure without touching the code.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import settings

logger = logging.getLogger("departments")


@dataclass(frozen=True)
class Department:
    email: str
    name: str
    description: str


@dataclass(frozen=True)
class DepartmentConfig:
    departments: list[Department]
    fallback: str

    @property
    def emails(self) -> list[str]:
        return [d.email for d in self.departments]


def load_departments(path: str | Path) -> DepartmentConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    departments = [
        Department(
            email=str(item["email"]).strip(),
            name=str(item.get("name") or item["email"]).strip(),
            description=" ".join(str(item.get("description", "")).split()),
        )
        for item in data.get("departments") or []
    ]
    if not departments:
        raise ValueError(f"{path}: at least one department is required")

    emails = [d.email for d in departments]
    if len(set(emails)) != len(emails):
        raise ValueError(f"{path}: department emails must be unique")

    fallback = str(data.get("fallback") or departments[-1].email).strip()
    if fallback not in emails:
        raise ValueError(f"{path}: fallback {fallback!r} is not one of the departments")

    logger.info("Loaded %d departments from %s (fallback: %s)", len(departments), path, fallback)
    return DepartmentConfig(departments=departments, fallback=fallback)


config = load_departments(settings.departments_file)
