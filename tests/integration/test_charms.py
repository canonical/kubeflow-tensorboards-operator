import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

TC_METADATA = yaml.safe_load(Path("charms/tensorboard-controller/metadata.yaml").read_text())
TWA_METADATA = yaml.safe_load(Path("charms/tensorboards-web-app/metadata.yaml").read_text())

ISTIO_CHANNEL = "1.17/stable"
ISTIO_PILOT = "istio-pilot"
ISTIO_PILOT_TRUST = True
ISTIO_GATEWAY = "istio-gateway"
ISTIO_GATEWAY_APP_NAME = "istio-ingressgateway"
ISTIO_GATEWAY_TRUST = True


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest):
    tensorboard_controller = await ops_test.build_charm("charms/tensorboard-controller")
    tensorboards_web_app = await ops_test.build_charm("charms/tensorboards-web-app")

    image_path = TC_METADATA["resources"]["tensorboard-controller-image"]["upstream-source"]
    resources = {"tensorboard-controller-image": image_path}

    await ops_test.model.deploy(
        entity_url=tensorboard_controller,
        resources=resources,
        trust=True,
    )

    tc_app_name = TC_METADATA["name"]
    twa_name = TWA_METADATA["name"]

    await ops_test.model.deploy(
        ISTIO_GATEWAY,
        application_name=ISTIO_GATEWAY_APP_NAME,
        channel=ISTIO_CHANNEL,
        config={"kind": "ingress"},
        trust=ISTIO_GATEWAY_TRUST,
    )
    await ops_test.model.deploy(
        ISTIO_PILOT,
        channel=ISTIO_CHANNEL,
        config={"default-gateway": "test-gateway"},
        trust=ISTIO_PILOT_TRUST,
    )
    await ops_test.model.add_relation(ISTIO_PILOT, ISTIO_GATEWAY)

    await ops_test.model.add_relation(f"{ISTIO_PILOT}:gateway-info", f"{tc_app_name}:gateway-info")

    image_path = TWA_METADATA["resources"]["tensorboards-web-app-image"]["upstream-source"]
    resources = {"tensorboards-web-app-image": image_path}

    await ops_test.model.deploy(
        entity_url=tensorboards_web_app,
        resources=resources,
        trust=True,
    )

    await ops_test.model.add_relation(f"{ISTIO_PILOT}:ingress", f"{twa_name}:ingress")

    # Wait for everything to deploy
    await ops_test.model.wait_for_idle(status="active", timeout=60 * 5)
