# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from charmed_kubeflow_chisme.testing import test_leadership_events as leadership_events
from charmed_kubeflow_chisme.testing import test_missing_image as missing_image
from charmed_kubeflow_chisme.testing import test_missing_relation as missing_relation
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness
import yaml

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_leadership_events(harness):
    leadership_events(harness)


def test_missing_image(harness):
    missing_image(harness, BlockedStatus)


def test_missing_relation(harness):
    missing_relation(harness, ActiveStatus)


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


def test_main(harness):
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
    pod_spec = harness.get_pod_spec()

    # confirm that we can serialize the pod spec
    yaml.safe_dump(pod_spec)

    assert isinstance(harness.charm.model.unit.status, ActiveStatus)
