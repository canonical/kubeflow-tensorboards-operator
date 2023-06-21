# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, patch

import ops.testing
import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import TensorboardsWebApp

# Enable simulation of container networking
ops.testing.SIMULATE_CAN_CONNECT = True
APP_NAME = "tensorboards-web-app"


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    harness = Harness(TensorboardsWebApp)

    # Set up container networking simulation
    harness.set_can_connect(APP_NAME, True)
    return harness


class TestCharm:
    """Test class for TensorboardsWebApp."""

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_not_leader(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm waits if it's not the leader."""
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_no_relation(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm is blocked when there is no ingress relation."""
        harness.set_leader(True)
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == BlockedStatus("No ingress relation available")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_with_relation(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm is active when there is an ingress relation"""
        harness.set_leader(True)
        self._setup_ingress_relation(harness)
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == ActiveStatus("")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_relation_data(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm has the expected relation data"""
        harness.set_leader(True)
        rel_id = self._setup_ingress_relation(harness)
        harness.begin_with_initial_hooks()

        relation_data = harness.get_relation_data(rel_id, harness.charm.app.name)
        data = {
            "service": "tensorboards-web-app",
            "port": 5000,
            "prefix": "/tensorboards",
            "rewrite": "/",
        }
        assert data == yaml.safe_load(relation_data["data"])

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_pebble_layer(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test the creation of Pebble layer and some of its fields."""
        harness.set_leader(True)
        harness.set_model_name("kubeflow")
        self._setup_ingress_relation(harness)
        harness.begin_with_initial_hooks()
        assert harness.charm.container.get_service(APP_NAME).is_running()
        pebble_plan = harness.get_container_pebble_plan(APP_NAME)
        pebble_plan_info = pebble_plan.to_dict()
        assert (
            pebble_plan_info["services"][APP_NAME]["command"]
            == "gunicorn -w 3 --bind 0.0.0.0:5000 --access-logfile - entrypoint:app"
        )
        test_env = pebble_plan_info["services"][APP_NAME]["environment"]
        # there should be 5 environment variables
        assert len(test_env) == 5

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_deploy_k8s_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test if K8S resource handler is executed as expected."""
        harness.begin()
        harness.charm._deploy_k8s_resources()
        k8s_resource_handler.apply.assert_called()
        assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)

    # Helper functions
    def _setup_ingress_relation(self, harness: Harness):
        rel_id = harness.add_relation("ingress", "istio-pilot")
        harness.add_relation_unit(rel_id, "istio-pilot/0")
        harness.update_relation_data(
            rel_id,
            "istio-pilot",
            {"_supported_versions": "- v1"},
        )
        return rel_id
