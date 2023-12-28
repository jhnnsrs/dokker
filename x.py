from dokker import base_setup, HealthCheck


with base_setup(
    "tests/configs/docker-compose.yaml",
    ht_checks=[HealthCheck(url="http://localhost:8456/graphql", service="mikro")],
):
    # do something with redis

    print("hello world")

    pass
