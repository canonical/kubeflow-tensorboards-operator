import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"oci-image": METADATA["resources"]["oci-image"]["upstream-source"]}
tc = SimpleNamespace(name="tensorboard-controller", resources=resources)

istio_gw = SimpleNamespace(
    charm="ch:istio-gateway",
    name="istio-ingressgateway",
    channel="latest/edge",
    config={"kind": "ingress"},
)
istio_pilot = SimpleNamespace(
    charm="ch:istio-pilot",
    name="istio-pilot",
    channel="latest/edge",
    config={"default-gateway": "test-gateway"},
)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, tc_charm):
    await asyncio.gather(
        ops_test.model.deploy(tc_charm, resources=tc.resources, application_name=tc.name),
        ops_test.model.deploy(
            istio_gw.charm,
            application_name=istio_gw.name,
            channel=istio_gw.channel,
            config=istio_gw.config,
            trust=True,
        ),
        ops_test.model.deploy(
            istio_pilot.charm,
            application_name=istio_pilot.name,
            channel=istio_pilot.channel,
            config=istio_pilot.config,
            trust=True,
        ),
    )

    await asyncio.gather(
        ops_test.model.add_relation(istio_pilot.name, istio_gw.name),
        ops_test.model.add_relation(f"{istio_pilot}:gateway-info", f"{tc.name}:gateway-info"),
    )

    await ops_test.model.wait_for_idle(timeout=60 * 10)
