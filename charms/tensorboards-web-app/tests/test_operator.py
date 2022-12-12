# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_not_leader(harness):
    harness.begin()
    assert type(harness.charm.model.unit.status) == MaintenanceStatus


def test_leader_elected(harness):
    harness.begin_with_initial_hooks()
    harness.set_leader(True)
    assert harness.charm.model.unit.status != WaitingStatus("Waiting for leadership")


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus("Missing resource: oci-image")


def test_no_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()

    assert harness.charm.model.unit.status == ActiveStatus()


def test_with_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("ingress", "app")

    harness.add_relation_unit(rel_id, "app/0")
    harness.update_relation_data(
        rel_id,
        "app",
        {"_supported_versions": "- v1"},
    )
    harness.begin_with_initial_hooks()

    harness.get_pod_spec()
    assert isinstance(harness.charm.model.unit.status, ActiveStatus)
