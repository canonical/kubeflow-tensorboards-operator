# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import aiohttp
import pytest
import yaml
from charmed_kubeflow_chisme.testing import assert_logging, deploy_and_assert_grafana_agent
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "tensorboards-web-app"
PORT = 5000

ISTIO_GATEWAY = "istio-ingressgateway"
ISTIO_PILOT = "istio-pilot"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request):
    """Build and deploy the charm under test.
    Assert on the unit status before ingress relation is set up.
    """
    # Build and deploy charm from local source folder or use
    # a charm artefact passed using --charm-path
    entity_url = (
        await ops_test.build_charm(".")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )
    image_path = METADATA["resources"][f"{APP_NAME}-image"]["upstream-source"]
    resources = {f"{APP_NAME}-image": image_path}

    await ops_test.model.deploy(
        entity_url=entity_url, resources=resources, application_name=APP_NAME, trust=True
    )

    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=60 * 5)

    unit = ops_test.model.applications[APP_NAME].units[0]
    assert unit.workload_status == "blocked"
    assert unit.workload_status_message == "Please relate to istio-pilot:ingress"

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=False, dashboard=False, logging=True
    )


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    await assert_logging(app)


@pytest.mark.abort_on_fail
async def test_ingress_relation(ops_test: OpsTest):
    """Setup Istio and relate it to the Tensoboards Web App(TWA)."""
    await setup_istio(ops_test, ISTIO_GATEWAY, ISTIO_PILOT)

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


async def setup_istio(ops_test: OpsTest, istio_gateway: str, istio_pilot: str):
    """Deploy Istio Ingress Gateway and Istio Pilot."""
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
    await ops_test.model.add_relation(istio_pilot, istio_gateway)

    await ops_test.model.wait_for_idle(
        apps=[istio_pilot, istio_gateway],
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
