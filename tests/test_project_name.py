"""``local()`` picks a stable project name that keeps sibling compose files apart -- no docker."""

from dokker import local
from dokker.builders import derive_project_name


def test_default_file_names_keep_composes_own_project_name():
    """What a hand-typed `docker compose up` in that directory would use."""
    assert derive_project_name(["tests/configs/battle/../battle/../../configs/docker-compose.yaml"]) == "configs"
    assert derive_project_name(["/srv/kraph/tests/integration/compose.yml"]) == "integration"


def test_other_file_names_get_directory_and_stem():
    assert derive_project_name(["tests/configs/battle/a-compose.yaml"]) == "battle-a-compose"
    assert derive_project_name(["tests/configs/battle/b-compose.yaml"]) == "battle-b-compose"


def test_first_file_decides_like_compose():
    assert derive_project_name(["tests/configs/battle/a-compose.yaml", "tests/configs/battle/b-compose.yaml"]) == "battle-a-compose"


def test_name_is_normalised_to_what_compose_accepts():
    assert derive_project_name(["/x/My Proj/Stack.V2.yml"]) == "my-proj-stack-v2"
    assert derive_project_name(["/x/---/-.yml"]) == "dokker"


def test_local_uses_the_derived_name_unless_given_one():
    assert local("tests/configs/battle/a-compose.yaml").project.project_name == "battle-a-compose"
    assert local("tests/configs/battle/a-compose.yaml", project_name="pinned").project.project_name == "pinned"
