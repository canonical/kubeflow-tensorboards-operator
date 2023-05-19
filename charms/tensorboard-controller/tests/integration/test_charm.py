#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import tenacity
import yaml
from httpx import HTTPStatusError
from lightkube import ApiError, Client, codecs
from lightkube.generic_resource import (
    create_namespaced_resource,
    load_in_cluster_generic_resources,
)
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import PersistentVolumeClaim, Pod, Service
from pytest_operator.plugin import OpsTest

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


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")
    tb_controller_image = METADATA["resources"]["tensorboard-controller-image"]["upstream-source"]
    resources = {"tensorboard-controller-image": tb_controller_image}

    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, trust=True)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="waiting", raise_on_blocked=True, timeout=1000
    )

    unit = ops_test.model.applications[APP_NAME].units[0]
    assert unit.workload_status == "waiting"
    assert unit.workload_status_message == "Waiting for gateway info relation"


async def _setup_istio(ops_test: OpsTest, istio_gateway: str, istio_pilot: str):
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
        raise_on_blocked=False,
        timeout=60 * 20,
    )


async def test_istio_gateway_info_relation(ops_test: OpsTest):
    """Setup Istio and relate it to the Tensorboard Controller."""
    # setup Istio
    istio_gateway = "istio-ingressgateway"
    istio_pilot = "istio-pilot"
    await _setup_istio(ops_test, istio_gateway, istio_pilot)

    # add Tensorboard-Controller/Istio relation
    await ops_test.model.add_relation(f"{istio_pilot}:gateway-info", f"{APP_NAME}:gateway-info")

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=1000
    )


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=10),
    stop=tenacity.stop_after_attempt(30),
    reraise=True,
)
def assert_replicas(client, resource_class, resource_name, namespace):
    """Test for replicas.

    Retries multiple times to allow for tensorboard to be created (i.e. readyReplicas == 1).
    """
    tensorboard = client.get(resource_class, resource_name, namespace=namespace)
    replicas = tensorboard.get("status", {}).get("readyReplicas")

    resource_class_kind = resource_class.__name__
    if replicas == 1:
        logger.info(f"{resource_class_kind}/{resource_name} readyReplicas == {replicas}")
    else:
        logger.info(
            f"{resource_class_kind}/{resource_name} readyReplicas == {replicas} (waiting for '1')"
        )

    assert replicas == 1, f"Waited too long for {resource_class_kind}/{resource_name}!"


async def test_create_tensorboard(ops_test: OpsTest):
    """Test Tensorboard creation."""
    lightkube_client = Client()
    load_in_cluster_generic_resources(lightkube_client)

    # Create PVC for Tensorboard logs and Tensorboard
    resources = codecs.load_all_yaml(
        "\n---\n".join([PVC_TEMPLATE_FILE.read_text(), TENSORBOARD_TEMPLATE_FILE.read_text()]),
        context={"pvc_name": PVC_NAME, "tensorboard_name": TENSORBOARD_NAME},
    )
    for rsc in resources:
        lightkube_client.create(rsc, namespace=ops_test.model_name)

    try:
        tensorboard_ready = lightkube_client.get(
            TENSORBOARD_RESOURCE,
            name=TENSORBOARD_NAME,
            namespace=ops_test.model_name,
        )
    except ApiError:
        assert False
    assert tensorboard_ready, f"Tensorboard {ops_test.model_name}/{TENSORBOARD_NAME} not found!"

    assert_replicas(lightkube_client, TENSORBOARD_RESOURCE, TENSORBOARD_NAME, ops_test.model_name)


@pytest.mark.abort_on_fail
async def test_remove_with_resources_present(ops_test: OpsTest):
    """Test remove with all resources deployed.

    Verify that all deployed resources that need to be removed are removed.
    """
    # remove deployed charm and verify that it is deleted
    await ops_test.model.remove_application(app_name=APP_NAME, block_until_done=True)
    assert APP_NAME not in ops_test.model.applications

    # verify that all resources that were deployed are deleted
    lightkube_client = Client()

    # verify that all created CRDs and Services in namespace are deleted
    for rsc in [
        CustomResourceDefinition,
        Service,
    ]:
        rsc_list = lightkube_client.list(
            rsc,
            labels=[("app.juju.is/created-by", APP_NAME)],
            namespace=ops_test.model_name,
        )
        assert not list(rsc_list)

    # verify that all created Pods in namespace are deleted
    for rsc in [
        Pod,
    ]:
        rsc_list = lightkube_client.list(
            rsc,
            labels=[("app", TENSORBOARD_NAME)],
            namespace=ops_test.model_name,
        )
        assert not list(rsc_list)

    # verify that the PVC and Tensorboard are deleted
    try:
        for rsc, name in [
            (PersistentVolumeClaim, PVC_NAME),
            (TENSORBOARD_RESOURCE, TENSORBOARD_NAME),
        ]:
            _ = lightkube_client.get(rsc, name=name, namespace=ops_test.model_name)
    except HTTPStatusError:
        assert True
    except ApiError as error:
        if error.status.code != 404:
            # other error than Not Found
            assert False
