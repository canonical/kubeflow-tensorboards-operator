#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
    get_alert_rules,
)
from lightkube import ApiError, Client, codecs
from lightkube.generic_resource import (
    create_namespaced_resource,
    load_in_cluster_generic_resources,
)
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import PersistentVolumeClaim
from pytest_operator.plugin import OpsTest
from utils import assert_replicas, remove_application, setup_istio

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("tests") / "assets"
PVC_TEMPLATE_FILE = ASSETS_DIR / "dummy-pvc.yaml.j2"
TENSORBOARD_TEMPLATE_FILE = ASSETS_DIR / "dummy-tensorboard.yaml.j2"

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

PVC_NAME = "dummy-pvc"
TENSORBOARD_NAME = "dummy-tensorboard"
TENSORBOARD_RESOURCE = create_namespaced_resource(
    group="tensorboard.kubeflow.org",
    version="v1alpha1",
    kind="tensorboard",
    plural="tensorboards",
)

ISTIO_GATEWAY = "istio-ingressgateway"
ISTIO_PILOT = "istio-pilot"


@pytest.fixture(scope="module")
def create_tensorboard(ops_test: OpsTest):
    """Create Tensorboard with attached PVC and handle cleanup at the end of the module tests."""
    lightkube_client = Client()
    load_in_cluster_generic_resources(lightkube_client)

    # Create PVC for Tensorboard logs and Tensorboard
    resources = codecs.load_all_yaml(
        "\n---\n".join([PVC_TEMPLATE_FILE.read_text(), TENSORBOARD_TEMPLATE_FILE.read_text()]),
        context={"pvc_name": PVC_NAME, "tensorboard_name": TENSORBOARD_NAME},
    )

    for rsc in resources:
        lightkube_client.create(rsc, namespace=ops_test.model_name)

    yield

    # manually delete the PVC at the end of the module tests, since Juju is not aware of it
    lightkube_client.delete(PersistentVolumeClaim, name=PVC_NAME, namespace=ops_test.model_name)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test: OpsTest, request):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder or use
    # a charm artefact passed using --charm-path
    entity_url = (
        await ops_test.build_charm(".")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )
    tb_controller_image = METADATA["resources"]["tensorboard-controller-image"]["upstream-source"]
    resources = {"tensorboard-controller-image": tb_controller_image}

    await ops_test.model.deploy(
        entity_url=entity_url, resources=resources, application_name=APP_NAME, trust=True
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="waiting", raise_on_blocked=True, timeout=60 * 5
    )

    unit = ops_test.model.applications[APP_NAME].units[0]
    assert unit.workload_status == "waiting"
    assert unit.workload_status_message == "Waiting for gateway info relation"

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=True, dashboard=False, logging=True
    )


@pytest.mark.abort_on_fail
async def test_istio_gateway_info_relation(ops_test: OpsTest):
    """Setup Istio and relate it to the Tensorboard Controller."""
    # setup Istio
    await setup_istio(ops_test, ISTIO_GATEWAY, ISTIO_PILOT)

    # add Tensorboard-Controller/Istio relation
    await ops_test.model.integrate(f"{ISTIO_PILOT}:gateway-info", f"{APP_NAME}:gateway-info")

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=60 * 5
    )


async def test_create_tensorboard(ops_test: OpsTest, create_tensorboard):
    """Test Tensorboard creation.

    This test relies on the create_tensorboard fixture, which handles the Tensorboard creation and
    is responsible for cleaning up at the end.
    """
    lightkube_client = Client()

    try:
        tensorboard_created = lightkube_client.get(
            TENSORBOARD_RESOURCE,
            name=TENSORBOARD_NAME,
            namespace=ops_test.model_name,
        )
    except ApiError as e:
        if e.status == 404:
            tensorboard_created = False
        else:
            raise
    assert tensorboard_created, f"Tensorboard {ops_test.model_name}/{TENSORBOARD_NAME} not found!"

    assert_replicas(lightkube_client, TENSORBOARD_RESOURCE, TENSORBOARD_NAME, ops_test.model_name)


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    await assert_logging(app)


async def test_metrics_enpoint(ops_test):
    """Test metrics_endpoints are defined in relation data bag and their accessibility.

    This function gets all the metrics_endpoints from the relation data bag, checks if
    they are available from the grafana-agent-k8s charm and finally compares them with the
    ones provided to the function.
    """
    app = ops_test.model.applications[APP_NAME]
    await assert_metrics_endpoint(app, metrics_port=8080, metrics_path="/metrics")


async def test_alert_rules(ops_test):
    """Test check charm alert rules and rules defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    alert_rules = get_alert_rules()
    await assert_alert_rules(app, alert_rules)


@pytest.mark.abort_on_fail
async def test_remove_with_resources_present(ops_test: OpsTest):
    """Test remove with all resources deployed.

    Verify that all deployed resources that need to be removed are removed.
    """
    lightkube_client = Client()

    # remove deployed charm and verify that it is deleted
    await remove_application(ops_test, APP_NAME)

    # verify that all created CRDs are deleted
    crds = lightkube_client.list(
        CustomResourceDefinition,
        labels=[("app.juju.is/created-by", APP_NAME)],
        namespace=ops_test.model_name,
    )
    assert not list(crds), "Failed to remove the Tensorboard CustomResourceDefinition!"
