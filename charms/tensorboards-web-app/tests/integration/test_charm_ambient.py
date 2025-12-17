# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_logging,
    assert_path_reachable_through_ingress,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    get_pod_names,
)
from lightkube import Client
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = "tensorboards-web-app"
PORT = 5000
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
HTTP_PATH = "/tensorboards/"
HEADERS = {"kubeflow-userid": "test"}
EXPECTED_RESPONSE_TEXT = "Tensorboards Manager UI"


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
        entity_url=entity_url,
        resources=resources,
        application_name=APP_NAME,
        trust=True,
    )

    await deploy_and_integrate_service_mesh_charms(app=APP_NAME, model=ops_test.model)

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=False, dashboard=False, logging=True
    )


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    await assert_logging(app)


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model_name,
        headers=HEADERS,
        expected_status=200,
        expected_content_type="text/html",
        expected_response_text=EXPECTED_RESPONSE_TEXT,
    )


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
async def test_container_security_context(
    ops_test: OpsTest,
    lightkube_client: Client,
    container_name: str,
):
    """Test container security context is correctly set.

    Verify that container spec defines the security context with correct
    user ID and group ID.
    """
    pod_name = get_pod_names(ops_test.model.name, APP_NAME)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        ops_test.model.name,
    )
