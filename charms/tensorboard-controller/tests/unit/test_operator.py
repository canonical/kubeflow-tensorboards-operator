# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import TensorboardController


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    with patch("charm.KubernetesServicePatch"), patch("charm.ServicePort"):
        yield Harness(TensorboardController)


class TestCharm:
    """Test class for Tensorboard Controller."""

    def _setup_gateway_info_relation(
        self,
        harness: Harness,
        model: str = "test-model",
        name: str = "test-gateway",
        populate_data: bool = True,
    ):
        """Setup the gateway info relation."""
        rel_id = harness.add_relation("gateway-info", "app")
        if populate_data:
            dummy_relation = {"gateway_namespace": model, "gateway_name": name}
            harness.update_relation_data(rel_id, "app", dummy_relation)
        harness.add_relation_unit(rel_id, "app/0")

    def _setup_gateway_metadata_relation(
        self, harness: Harness, model: str = "test-model", name: str = "test-gateway"
    ):
        """Setup the gateway metadata relation.

        Note: This should be called before harness.begin() or harness.begin_with_initial_hooks().
        The mocking of get_metadata will be applied after harness starts.
        """
        rel_id = harness.add_relation("gateway-metadata", "app")
        harness.add_relation_unit(rel_id, "app/0")
        return model, name

    @patch("charm.TensorboardController.rbac_resource_handler", MagicMock())
    @patch("charm.TensorboardController.crd_resource_handler", MagicMock())
    def test_log_forwarding(self, harness: Harness):
        """Test LogForwarder initialization."""
        with patch("charm.LogForwarder") as mock_logging:
            harness.begin()
            mock_logging.assert_called_once_with(charm=harness.charm)

    @patch("charm.TensorboardController.rbac_resource_handler", MagicMock())
    @patch("charm.TensorboardController.crd_resource_handler", MagicMock())
    def test_metrics(self, harness: Harness):
        """Test MetricsEndpointProvider initialization."""
        with patch("charm.MetricsEndpointProvider") as mock_metrics:
            harness.begin()
            mock_metrics.assert_called_once_with(
                harness.charm, jobs=[{"static_configs": [{"targets": ["*:8080"]}]}]
            )

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_not_leader(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm goes to waiting if it's not the leader."""
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_no_gateway_relation(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm is blocked if no gateway relation exists."""
        harness.set_leader(True)
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == BlockedStatus(
            "Missing required gateway relation"
        )

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_waiting_for_gateway_info_data(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm goes to waiting when gateway-info relation exists but data not ready."""
        from charms.istio_pilot.v0.istio_gateway_info import GatewayRelationError

        harness.set_leader(True)
        # Add relation but don't populate data
        self._setup_gateway_info_relation(harness, populate_data=False)

        harness.begin()
        harness.set_can_connect("tensorboard-controller", True)

        # Mock get_relation_data to raise GatewayRelationError
        with patch.object(
            harness.charm.sidecar_gateway,
            "get_relation_data",
            side_effect=GatewayRelationError("Data not ready"),
        ):
            harness.charm.on.config_changed.emit()

        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for gateway info relation data"
        )

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_active_with_gateway_info(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm goes to active status with gateway-info relation."""
        harness.set_leader(True)
        self._setup_gateway_info_relation(harness)

        harness.begin_with_initial_hooks()

        assert isinstance(harness.charm.model.unit.status, ActiveStatus)

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_waiting_for_gateway_metadata_data(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test charm goes to waiting when gateway-metadata relation exists but data not ready."""
        harness.set_leader(True)
        model, name = self._setup_gateway_metadata_relation(harness)

        harness.begin()
        harness.set_can_connect("tensorboard-controller", True)

        # Mock the ambient_gateway.get_metadata() to return None (data not ready)
        harness.charm.ambient_gateway.get_metadata = MagicMock(return_value=None)

        # Trigger a config-changed to re-evaluate
        harness.charm.on.config_changed.emit()

        assert harness.charm.model.unit.status == WaitingStatus(
            "Waiting for gateway metadata relation data"
        )

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_active_with_gateway_metadata(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm goes to active status with gateway-metadata relation."""
        harness.set_leader(True)
        model, name = self._setup_gateway_metadata_relation(harness)

        harness.begin_with_initial_hooks()

        # Mock the ambient_gateway.get_metadata() to return expected data
        metadata = MagicMock()
        metadata.namespace = model
        metadata.gateway_name = name
        harness.charm.ambient_gateway.get_metadata = MagicMock(return_value=metadata)

        # Trigger a config-changed to re-evaluate
        harness.charm.on.config_changed.emit()

        assert isinstance(harness.charm.model.unit.status, ActiveStatus)

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_blocked_with_both_gateway_relations(
        self, rbac_resource_handler: MagicMock, crd_resource_handler: MagicMock, harness: Harness
    ):
        """Test that charm is blocked when both gateway relations are present."""
        harness.set_leader(True)
        self._setup_gateway_info_relation(harness)
        model, name = self._setup_gateway_metadata_relation(harness)

        harness.begin_with_initial_hooks()

        # Mock the ambient_gateway.get_metadata() to return expected data
        metadata = MagicMock()
        metadata.namespace = model
        metadata.gateway_name = name
        harness.charm.ambient_gateway.get_metadata = MagicMock(return_value=metadata)

        # Trigger a config-changed to re-evaluate
        harness.charm.on.config_changed.emit()

        assert harness.charm.model.unit.status == BlockedStatus(
            "Cannot relate to both sidecar and ambient gateway simultaneously"
        )

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_pebble_layer(
        self,
        rbac_resource_handler: MagicMock,
        crd_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test creation of Pebble layer."""
        harness.set_leader(True)
        model, name = "kubeflow", "kubeflow-gateway"
        harness.set_model_name(model)
        self._setup_gateway_info_relation(harness, model, name)
        harness.begin_with_initial_hooks()
        assert harness.charm.container.get_service("tensorboard-controller").is_running()
        pebble_plan = harness.get_container_pebble_plan("tensorboard-controller")
        assert pebble_plan
        assert pebble_plan.services
        pebble_plan_info = pebble_plan.to_dict()
        assert pebble_plan_info["services"]["tensorboard-controller"]["command"] == "/manager"
        test_env = pebble_plan_info["services"]["tensorboard-controller"]["environment"]
        assert "ISTIO_GATEWAY" and "TENSORBOARD_IMAGE" in test_env
        assert f"{model}/{name}" == test_env["ISTIO_GATEWAY"]

    @patch("charm.TensorboardController.rbac_resource_handler")
    @patch("charm.TensorboardController.crd_resource_handler")
    def test_deploy_k8s_resources_success(
        self,
        rbac_resource_handler: MagicMock,
        crd_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test that the K8s resource handler is executed as expected."""
        harness.begin()
        harness.charm._apply_k8s_resources()
        rbac_resource_handler.apply.assert_called()
        crd_resource_handler.apply.assert_called()
        assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)
