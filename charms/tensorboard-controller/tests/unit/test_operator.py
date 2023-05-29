# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import TensorboardController


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    harness = Harness(TensorboardController)

    # setup container networking simulation
    harness.set_can_connect("tensorboard-controller", True)

    return harness


class TestCharm:
    """Test class for Tensorboard Controller."""

    def _setup_gateway_info_relation(
        self, harness: Harness, model: str = "test-model", name: str = "test-gateway"
    ):
        """Setup the gateway info relation."""
        dummy_relation = {"gateway_namespace": model, "gateway_name": name}
        rel_id = harness.add_relation("gateway-info", "app")
        harness.update_relation_data(rel_id, "app", dummy_relation)
        harness.add_relation_unit(rel_id, "app/0")

    @patch("charm.TensorboardController.k8s_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_not_leader(
        self, k8s_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm waits if it's not the leader."""
        harness.begin_with_initial_hooks()

        assert isinstance(harness.charm.model.unit.status, WaitingStatus)
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @patch("charm.TensorboardController.k8s_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_no_gateway_info_relation(
        self, k8s_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm waits if the gateway info relation is missing."""
        harness.set_leader(True)
        harness.begin_with_initial_hooks()

        assert isinstance(harness.charm.model.unit.status, WaitingStatus)
        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for gateway info relation"
        )

    @patch("charm.TensorboardController.k8s_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_active(
        self, k8s_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm goes to active status if the gateway info relation exists."""
        harness.set_leader(True)
        self._setup_gateway_info_relation(harness)

        harness.begin_with_initial_hooks()

        assert isinstance(harness.charm.model.unit.status, ActiveStatus)

    @patch("charm.TensorboardController.k8s_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_pebble_layer(
        self,
        k8s_resource_handler: MagicMock,
        crd_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test creation of Pebble layer."""
        harness.set_leader(True)
        model, name = "kubeflow", "kubeflow-gateway"
        harness.set_model_name(model)
        self._setup_gateway_info_relation(harness, model, name)
        harness.begin_with_initial_hooks()
        harness.container_pebble_ready("tensorboard-controller")
        assert harness.charm.container.get_service("tensorboard-controller").is_running()
        pebble_plan = harness.get_container_pebble_plan("tensorboard-controller")
        assert pebble_plan
        assert pebble_plan.services
        pebble_plan_info = pebble_plan.to_dict()
        assert pebble_plan_info["services"]["tensorboard-controller"]["command"] == "/manager"
        test_env = pebble_plan_info["services"]["tensorboard-controller"]["environment"]
        # there should be 2 environment variables
        assert 2 == len(test_env)
        assert f"{model}/{name}" == test_env["ISTIO_GATEWAY"]

    @patch("charm.TensorboardController.k8s_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_deploy_k8s_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        crd_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test that the K8s resource handler is executed as expected."""
        harness.begin()
        harness.charm._apply_k8s_resources()
        k8s_resource_handler.apply.assert_called()
        assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)

    @patch("charm.TensorboardController._apply_k8s_resources")
    @patch("charm.TensorboardController._check_status")
    def test_update_status(
        self,
        _apply_k8s_resources: MagicMock,
        _check_status: MagicMock,
        harness: Harness,
    ):
        """Test update status handler."""
        harness.set_leader(True)
        self._setup_gateway_info_relation(harness)
        harness.begin_with_initial_hooks()
        harness.container_pebble_ready("tensorboard-controller")

        # test successful update status
        harness.charm.on.update_status.emit()
        _apply_k8s_resources.assert_called()
        _check_status.assert_called()
