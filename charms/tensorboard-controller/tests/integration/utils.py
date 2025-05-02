# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import tenacity
from lightkube import Client
from lightkube.core.resource import Resource
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def setup_istio(ops_test: OpsTest, istio_gateway: str, istio_pilot: str):
    """Deploy Istio Ingress Gateway and Istio Pilot."""
    await ops_test.model.deploy(
        entity_url="istio-gateway",
        application_name=istio_gateway,
        channel="1.24/stable",
        config={"kind": "ingress"},
        trust=True,
    )
    await ops_test.model.deploy(
        istio_pilot,
        channel="1.24/stable",
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


async def cleanup_istio(ops_test: OpsTest, istio_gateway: str, istio_pilot: str):
    """Remove Istio Ingress Gateway and Istio Pilot applications."""
    for app in [istio_pilot, istio_gateway]:
        await remove_application(ops_test, app)


async def remove_application(ops_test: OpsTest, application_name: str, block: bool = True):
    """Remove application."""
    logger.info(f"Removing application {application_name}...")
    await ops_test.model.remove_application(app_name=application_name, block_until_done=block)
    assert application_name not in ops_test.model.applications


@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=2, min=1, max=10),
    stop=tenacity.stop_after_attempt(30),
    reraise=True,
)
def assert_replicas(
    client: Client,
    resource_class: Resource,
    resource_name: str,
    namespace: str,
    target_replicas: int = 1,
):
    """Test for replicas.

    Retries multiple times to allow for K8s resource to reach the target number of ready replicas.
    """
    rsc = client.get(resource_class, resource_name, namespace=namespace)
    replicas = rsc.get("status", {}).get("readyReplicas")

    resource = f"{namespace}/{resource_class.__name__}/{resource_name}"
    logger.info(
        f"Waiting for {resource} to reach {target_replicas} ready replicas:"
        f" readyReplicas == {replicas}"
    )

    assert replicas == target_replicas, f"Waited too long for {resource}!"
