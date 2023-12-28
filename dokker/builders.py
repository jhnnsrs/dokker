from .setup import Setup, Project


def base_setup(docker_compose_file: str, ht_checks: list) -> Setup:
    project = Project(compose_files=[docker_compose_file])
    return Setup(project=project, ht_checks=ht_checks)
