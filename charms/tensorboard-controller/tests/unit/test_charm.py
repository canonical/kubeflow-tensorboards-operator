# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)


def test_leader_elected(harness):
    harness.begin_with_initial_hooks()
    harness.set_leader(True)
    assert not isinstance(harness.charm.model.unit.status, WaitingStatus)


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)


def test_no_gateway_info_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "image",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)


def test_main(harness):
    harness.set_model_name("test-model")
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "image",
            "username": "",
            "password": "",
        },
    )

    rel_id = harness.add_relation("gateway-info", "app")
    harness.update_relation_data(
        rel_id,
        "app",
        {"gateway_namespace": "test-model", "gateway_name": "test-gateway"},
    )
    harness.add_relation_unit(rel_id, "app/0")

    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    # confirm that we can serialize the pod spec
    yaml.safe_dump(pod_spec)

    assert isinstance(harness.charm.model.unit.status, ActiveStatus)
