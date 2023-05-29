#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


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
