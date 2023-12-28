from .setup import Setup, HealthCheck
from .project import Project
import os
from typing import List, Optional, Union, TYPE_CHECKING
from dokker.projects.copy import CopyPathProject
from dokker.projects.local import LocalProject

if TYPE_CHECKING:
    from dokker.projects.contrib.cookiecutter import CookieCutterProject


def local_project(
    docker_compose_file: str, health_checks: List[HealthCheck] = None
) -> LocalProject:
    return LocalProject(
        compose_files=[docker_compose_file], health_checks=health_checks
    )


def cookiecutter_project(repo_url: str) -> "CookieCutterProject":
    from dokker.projects.contrib.cookiecutter import CookieCutterProject

    return CookieCutterProject(repo_url=repo_url, project_name="test")


def copy_path_project(
    project_path: str, project_name: Optional[str] = None
) -> CopyPathProject:
    return CopyPathProject(project_path=project_path, project_name=project_name)


def easy(project: Project, health_checks: List[HealthCheck] = None) -> Setup:
    return Setup(project=project, health_checks=health_checks)


def local(docker_compose_file: str, health_checks: List[HealthCheck] = None) -> Setup:
    project = LocalProject(
        compose_files=[docker_compose_file],
    )
    return easy(project, health_checks=health_checks)
