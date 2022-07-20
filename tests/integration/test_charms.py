import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

TC_METADATA = yaml.safe_load(Path("charms/tensorboard-controller/metadata.yaml").read_text())
TWA_METADATA = yaml.safe_load(Path("charms/tensorboards-web-app/metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest):
    tensorboard_controller = await ops_test.build_charm("charms/tensorboard-controller")
    tensorboards_web_app = await ops_test.build_charm("charms/tensorboards-web-app")

    image_path = TC_METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=tensorboard_controller,
        resources=resources,
    )

    istio_gateway = "istio-ingressgateway"
    istio_pilot = "istio-pilot"
    tc_app_name = TC_METADATA["name"]

    await ops_test.model.deploy(
        entity_url="istio-gateway",
        application_name=istio_gateway,
        channel="latest/edge",
        config={"kind": "ingress"},
        trust=True,
    )
    await ops_test.model.deploy(
        istio_pilot,
        channel="latest/edge",
        config={"default-gateway": "test-gateway"},
        trust=True,
    )

    await ops_test.model.add_relation(
        istio_pilot,
        istio_gateway,
    )
    await ops_test.model.add_relation(f"{istio_pilot}:gateway", f"{tc_app_name}:gateway")

    image_path = TWA_METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=tensorboards_web_app,
        resources=resources,
    )

    await ops_test.model.wait_for_idle(timeout=60 * 10)
