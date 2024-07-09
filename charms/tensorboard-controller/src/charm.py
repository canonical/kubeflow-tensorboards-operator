#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import Dict, Tuple

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import (
    KubernetesResourceHandler,
    create_charm_default_labels,
)
from charmed_kubeflow_chisme.pebble import update_layer
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.istio_pilot.v0.istio_gateway_info import GatewayRelationError, GatewayRequirer
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, Container, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

PROBE_PORT = "8081"
PROBE_PATH = "/healthz"
PROBE_NAME = "tensorboard-controller-up"

K8S_RESOURCES = {
    "template_files": ["src/templates/auth_manifests.yaml.j2"],
    "resource_types": {ClusterRole, ClusterRoleBinding},
    "scope": "tensorboard",
}
CRD_RESOURCES = {
    "template_files": ["src/templates/crds.yaml.j2"],
    "resource_types": {CustomResourceDefinition},
    "scope": "tensorboard",
}

TENSORBOARD_IMAGE = "tensorflow/tensorflow:2.5.1"


class TensorboardController(CharmBase):
    """Tensorboard Controller Charmed Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)

        # retrieve configuration and base settings
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.app.name
        self._exec_command = "/manager"
        self._container_name = "tensorboard-controller"
        self._container = self.unit.get_container(self._container_name)

        # setup context to be used for updating K8s resources
        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "service": self._name,
        }
        self._rbac_resource_handler = None
        self._crd_resource_handler = None

        self.gateway = GatewayRequirer(self)

        # setup events to be handled by main event handler
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.leader_elected, self._on_event)
        self.framework.observe(self.on.tensorboard_controller_pebble_ready, self._on_event)
        self.framework.observe(self.on["gateway-info"].relation_changed, self._on_event)

        # setup events to be handled by specific event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade)
        self.framework.observe(self.on.remove, self._on_remove)

        self._logging = LogForwarder(charm=self)

    @property
    def container(self) -> Container:
        """Return tensorboard-controller container object."""
        return self._container

    @property
    def rbac_resource_handler(self) -> KubernetesResourceHandler:
        """Get the K8s RBAC resource handler."""
        if not self._rbac_resource_handler:
            self._rbac_resource_handler = self._create_resource_handler(K8S_RESOURCES)
        load_in_cluster_generic_resources(self._rbac_resource_handler.lightkube_client)
        return self._rbac_resource_handler

    @rbac_resource_handler.setter
    def rbac_resource_handler(self, handler: KubernetesResourceHandler):
        """Set the K8s RBAC resource handler."""
        self._rbac_resource_handler = handler

    @property
    def crd_resource_handler(self) -> KubernetesResourceHandler:
        """Get the K8s CRD resource handler."""
        if not self._crd_resource_handler:
            self._crd_resource_handler = self._create_resource_handler(CRD_RESOURCES)
        load_in_cluster_generic_resources(self._crd_resource_handler.lightkube_client)
        return self._crd_resource_handler

    @crd_resource_handler.setter
    def crd_resource_handler(self, handler: KubernetesResourceHandler):
        """Set the K8s CRD resource handler."""
        self._crd_resource_handler = handler

    @property
    def service_environment(self) -> Dict[str, str]:
        """Return environment variables based on relation data."""
        gateway_ns, gateway_name = self._get_gateway_data()
        ret_env_vars = {
            "ISTIO_GATEWAY": f"{gateway_ns}/{gateway_name}",
            "ISTIO_HOST": "*",
            "RWO_PVC_SCHEDULING": "True",
            "TENSORBOARD_IMAGE": TENSORBOARD_IMAGE,
        }

        return ret_env_vars

    @property
    def _tensorboard_controller_layer(self) -> Layer:
        """Create and return Pebble framework layer."""
        layer_config = {
            "summary": "tensorboard-controller layer",
            "description": "Pebble config layer for tensorboard-controller",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "Entrypoint of tensorboard-controller image",
                    "command": self._exec_command,
                    "startup": "enabled",
                    "environment": self.service_environment,
                    "on-check-failure": {PROBE_NAME: "restart"},
                }
            },
            "checks": {
                PROBE_NAME: {
                    "override": "replace",
                    "period": "30s",
                    "timeout": "20s",
                    "threshold": 4,
                    "http": {"url": f"http://localhost:{PROBE_PORT}{PROBE_PATH}"},
                }
            },
        }

        return Layer(layer_config)

    def _create_resource_handler(self, resources: Dict) -> KubernetesResourceHandler:
        """Create a resource handler for a set of resources."""
        return KubernetesResourceHandler(
            field_manager=self._lightkube_field_manager,
            context=self._context,
            template_files=resources["template_files"],
            resource_types=resources["resource_types"],
            labels=create_charm_default_labels(
                application_name=self.app.name,
                model_name=self.model.name,
                scope=resources["scope"],
            ),
            logger=self.logger,
        )

    def _get_gateway_data(self) -> Tuple[str, str]:
        """Retrieve gateway namespace and name from relation data."""
        try:
            gateway_data = self.gateway.get_relation_data()
        except GatewayRelationError:
            raise ErrorWithStatus("Waiting for gateway info relation", WaitingStatus)

        return gateway_data["gateway_namespace"], gateway_data["gateway_name"]

    def _apply_k8s_resources(self, force_conflicts: bool = False) -> None:
        """Apply K8s resources.

        Args:
            force_conflicts (bool): *(optional)* Will "force" apply requests causing conflicting
                                    fields to change ownership to the field manager used in this
                                    charm.
        """
        self.unit.status = MaintenanceStatus("Creating K8s resources")
        try:
            for handler in {self.rbac_resource_handler, self.crd_resource_handler}:
                handler.apply(force=force_conflicts)
        except Exception as error:
            raise GenericCharmRuntimeError("K8s resources creation failed", error)

    def _check_leader(self) -> None:
        """Check whether a unit is the leader."""
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self) -> None:
        """Check if connection can be made with container."""
        if not self.container.can_connect():
            raise ErrorWithStatus("Pod startup is not complete", MaintenanceStatus)

    def _on_install(self, _) -> None:
        """Handle install event."""
        # deploy K8s resources to speed up deployment
        self._apply_k8s_resources()

    def _on_upgrade(self, _) -> None:
        """Handle upgrade event."""
        # force conflict resolution in K8s resources update
        self._on_event(_, force_conflicts=True)

    def _on_remove(self, _) -> None:
        """Handle remove event."""
        delete_errors = []
        self.unit.status = MaintenanceStatus("Removing K8s resources")
        for handler in {self.rbac_resource_handler, self.crd_resource_handler}:
            try:
                handler.delete()
            except ApiError as error:
                delete_errors.append(error)

        if delete_errors:
            raise GenericCharmRuntimeError("Removing K8s resources failed", delete_errors)

    def _on_event(self, event, force_conflicts: bool = False) -> None:
        """Perform all required actions for the Charm.

        Handle events that require both the K8s resources to be reapplied and the Pebble services
        to be restarted. The following actions are executed:

        * Check connection to the container
        * Check for leadership
        * Apply Kubernetes resources
        * Update the Pebble layer
        * Handle any errors and appropriately set the unit status

        Args:
            force_conflicts (bool): Should only be used when need to resolved conflicts on K8s
                                    resources.
        """
        try:
            self._check_container_connection()
            self._check_leader()
            self._apply_k8s_resources(force_conflicts=force_conflicts)
            update_layer(
                self._container_name,
                self._container,
                self._tensorboard_controller_layer,
                self.logger,
            )
        except ErrorWithStatus as err:
            self.unit.status = err.status
            self.logger.error(f"Failed to handle {event} with error: {err}")
            return

        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(TensorboardController)
