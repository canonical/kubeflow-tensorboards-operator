# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import yaml
from charms.istio_ingress_k8s.v0.istio_ingress_route import (
    HTTPPathMatchType,
    IstioIngressRouteConfig,
    ProtocolType,
)
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import TensorboardsWebApp

APP_NAME = "tensorboards-web-app"
PORT = 5000
ISTIO_INGRESS_ROUTE_RELATION = "istio-ingress-route"
INGRESS_RELATION = "ingress"
ISTIO_INGRESS_K8S_APP = "istio-ingress-k8s"
SECOND_ISTIO_INGRESS_K8S_APP = f"{ISTIO_INGRESS_K8S_APP}-2"
ISTIO_PILOT_APP = "istio-pilot"
HTTP_PATH = "/tensorboards/"
HTTP_SECTION_NAME = "http-80"


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    harness = Harness(TensorboardsWebApp)
    harness.set_leader(True)
    harness.set_model_name("tensorboards-ns")
    return harness


class TestCharm:
    """Test class for TensorboardsWebApp."""

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_log_forwarding(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test LogForwarder initialization."""
        with patch("charm.LogForwarder") as mock_logging:
            harness.begin()
            mock_logging.assert_called_once_with(charm=harness.charm)

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_not_leader(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm waits if it's not the leader."""
        harness.set_leader(False)
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_no_relation(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm is blocked when there is no ingress relation."""
        harness.begin_with_initial_hooks()
        assert harness.charm.model.unit.status == BlockedStatus(
            "None of 'istio-ingress-route' or 'ingress' relations found."
        )

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_with_relation(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm is active when there is an ingress relation"""
        self._setup_ingress_relation(harness)
        harness.begin_with_initial_hooks()

        assert harness.charm.model.unit.status == ActiveStatus("")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_relation_data(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test that charm has the expected relation data"""
        rel_id = self._setup_ingress_relation(harness)
        harness.begin_with_initial_hooks()

        relation_data = harness.get_relation_data(rel_id, harness.charm.app.name)
        data = {
            "service": "tensorboards-web-app",
            "port": PORT,
            "prefix": "/tensorboards",
            "rewrite": "/",
        }
        assert data == yaml.safe_load(relation_data["data"])

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_pebble_layer(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Test the creation of Pebble layer and some of its fields."""
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
    def test_apply_k8s_resources_success(
        self,
        k8s_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test if K8S resource handler is executed as expected."""
        harness.begin()
        harness.charm._apply_k8s_resources()
        k8s_resource_handler.apply.assert_called()
        assert isinstance(harness.charm.model.unit.status, MaintenanceStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_sidecar_and_ambient_relations_added(
        self, k8s_resource_handler: MagicMock, harness: Harness
    ):
        """Test the charm is in BlockedStatus when both sidecar and ambient relations are added."""
        # Arrange
        harness.add_relation(INGRESS_RELATION, ISTIO_PILOT_APP)

        harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, ISTIO_INGRESS_K8S_APP)

        # Act
        harness.begin_with_initial_hooks()

        # Assert
        assert isinstance(
            harness.charm.model.unit.status,
            BlockedStatus,
        )

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_multiple_ambient_relations_added(
        self, k8s_resource_handler: MagicMock, harness: Harness
    ):
        """Test that multiple istio-ingress-route relations are handled without erroring."""
        # Arrange
        harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, ISTIO_INGRESS_K8S_APP)
        harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, SECOND_ISTIO_INGRESS_K8S_APP)

        # Act
        harness.begin_with_initial_hooks()

        # Assert: with only ambient relations and no conflicting sidecar relation,
        # the charm is configured for every ambient relation and becomes active.
        assert isinstance(harness.charm.model.unit.status, ActiveStatus)

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler")
    def test_each_istio_ingress_route_relation_receives_config(
        self, k8s_resource_handler: MagicMock, harness: Harness
    ):
        """Test that an HTTPRoute config is submitted to every istio-ingress-route relation."""
        # Arrange
        rel_id_1 = harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, ISTIO_INGRESS_K8S_APP)
        rel_id_2 = harness.add_relation(ISTIO_INGRESS_ROUTE_RELATION, SECOND_ISTIO_INGRESS_K8S_APP)

        # Act
        harness.begin_with_initial_hooks()

        # Assert
        # Each relation's application databag should contain a valid config that
        # defines the tensorboards-web-app HTTPRoute, proving the lib handles every ingress.
        for rel_id in (rel_id_1, rel_id_2):
            app_data = harness.get_relation_data(rel_id, harness.charm.app.name)
            assert "config" in app_data

            config = IstioIngressRouteConfig.model_validate_json(app_data["config"])
            assert len(config.http_routes) == 1
            http_route = config.http_routes[0]
            assert http_route.matches[0].path.type == HTTPPathMatchType.PathPrefix
            assert http_route.matches[0].path.value == HTTP_PATH
            assert http_route.backends[0].service == harness.charm.app.name
            assert http_route.backends[0].port == PORT
            # The route's parent (the Gateway listener referenced under parentRefs in
            # the HTTPRouteSpec) should be the expected HTTP listener.
            assert http_route.listener.name == HTTP_SECTION_NAME

    @pytest.mark.parametrize("tls_enabled, expected_port", [(False, 80), (True, 443)])
    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.TensorboardsWebApp.k8s_resource_handler", MagicMock)
    @patch("charm.ServiceMeshConsumer", MagicMock)
    def test_ambient_ingress_listener_port(self, harness: Harness, tls_enabled, expected_port):
        """Test the ambient ingress listener uses the correct port based on TLS setting."""
        with patch(
            "charm.IstioIngressRouteRequirer.tls_enabled",
            new_callable=PropertyMock,
            return_value=tls_enabled,
        ), patch("charm.IstioIngressRouteRequirer.submit_config") as mock_submit:
            harness.begin()

        mock_submit.assert_called_once()
        config = mock_submit.call_args[0][0]
        assert len(config.listeners) == 1
        assert config.listeners[0].port == expected_port
        assert config.listeners[0].protocol == ProtocolType.HTTP

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
