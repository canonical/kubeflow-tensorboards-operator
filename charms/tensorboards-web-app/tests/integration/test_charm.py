# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import aiohttp
import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "tensorboards-web-app"
PORT = 5000

ISTIO_CHANNEL = "1.17/stable"
ISTIO_PILOT = "istio-pilot"
ISTIO_PILOT_TRUST = True
ISTIO_GATEWAY = "istio-gateway"
ISTIO_GATEWAY_APP_NAME = "istio-ingressgateway"
ISTIO_GATEWAY_TRUST = True


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build and deploy the charm under test.
    Assert on the unit status before ingress relation is set up.
    """
    charm = await ops_test.build_charm(".")
    image_path = METADATA["resources"][f"{APP_NAME}-image"]["upstream-source"]
    resources = {f"{APP_NAME}-image": image_path}

    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, trust=True)

    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=60 * 5)

    unit = ops_test.model.applications[APP_NAME].units[0]
    assert unit.workload_status == "blocked"
    assert unit.workload_status_message == "Please relate to istio-pilot:ingress"


@pytest.mark.abort_on_fail
async def test_ingress_relation(ops_test: OpsTest):
    """Setup Istio and relate it to the Tensoboards Web App(TWA)."""
    await setup_istio(ops_test)

    await ops_test.model.add_relation(f"{ISTIO_PILOT}:ingress", f"{APP_NAME}:ingress")

    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=60 * 5)


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that TWA's UI is accessible."""
    # This test also checks that Pebble checks pass since it uses the same URL.

    status = await ops_test.model.get_status()
    units = status["applications"][APP_NAME]["units"]
    url = units[f"{APP_NAME}/0"]["address"]
    headers = {"kubeflow-userid": "user"}

    # obtain status and response text from TWA URL
    result_status, result_text = await fetch_response(f"http://{url}:{PORT}", headers)

    # verify that UI is accessible
    assert result_status == 200
    assert len(result_text) > 0
    assert "Tensorboards Manager UI" in result_text


async def setup_istio(ops_test: OpsTest):
    """Deploy Istio Ingress Gateway and Istio Pilot."""
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
    await ops_test.model.add_relation(ISTIO_PILOT, ISTIO_GATEWAY_APP_NAME)

    await ops_test.model.wait_for_idle(
        apps=[ISTIO_PILOT, ISTIO_GATEWAY_APP_NAME],
        status="active",
        timeout=60 * 5,
    )


async def fetch_response(url, headers):
    """Fetch provided URL and return pair - status and text (int, string)."""
    result_status = 0
    result_text = ""
    async with aiohttp.ClientSession() as session:
        async with session.get(url=url, headers=headers) as response:
            result_status = response.status
            result_text = await response.text()
    return result_status, str(result_text)
