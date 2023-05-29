#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import Dict, Tuple

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charmed_kubeflow_chisme.pebble import update_layer
from charms.istio_pilot.v0.istio_gateway_info import GatewayRelationError, GatewayRequirer
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, Container, MaintenanceStatus, ModelError, WaitingStatus
from ops.pebble import CheckStatus, Layer

PROBE_PORT = "8081"
PROBE_PATH = "/healthz"

K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
]
CRD_RESOURCE_FILES = [
    "src/templates/crds.yaml.j2",
]


class TensorboardController(CharmBase):
    """Tensorboard Controller Charmed Operator."""

    def __init__(self, *args):
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)

        # retrieve configuration and base settings
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
        self._exec_command = "/manager"
        self._container_name = "tensorboard-controller"
        self._container = self.unit.get_container(self._container_name)

        # setup context to be used for updating K8s resources
        self._context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "service": self._name,
        }
        self._k8s_resource_handler = None
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
        self.framework.observe(self.on.update_status, self._on_update_status)

    @property
    def container(self) -> Container:
        """Return container."""
        return self._container

    @property
    def k8s_resource_handler(self) -> KubernetesResourceHandler:
        """Get the K8s resource handler."""
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        """Set the K8s resource handler."""
        self._k8s_resource_handler = handler

    @property
    def crd_resource_handler(self) -> KubernetesResourceHandler:
        """Get the K8s CRD resource handler."""
        if not self._crd_resource_handler:
            self._crd_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=CRD_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._crd_resource_handler.lightkube_client)
        return self._crd_resource_handler

    @crd_resource_handler.setter
    def crd_resource_handler(self, handler: KubernetesResourceHandler):
        """Set the K8s CRD resource handler."""
        self._crd_resource_handler = handler

    def _get_gateway_data(self) -> Tuple[str, str]:
        """Retrieve gateway namespace and name from relation data."""
        try:
            gateway_data = self.gateway.get_relation_data()
        except GatewayRelationError:
            raise ErrorWithStatus("Waiting for gateway info relation", WaitingStatus)

        return gateway_data["gateway_namespace"], gateway_data["gateway_name"]

    @property
    def service_environment(self) -> Dict[str, str]:
        """Return environment variables based on relation data."""
        gateway_ns, gateway_name = self._get_gateway_data()
        ret_env_vars = {
            "ISTIO_GATEWAY": f"{gateway_ns}/{gateway_name}",
            "TENSORBOARD_IMAGE": "tensorflow/tensorflow:2.1.0",
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
                    "on-check-failure": {"tensorboard-controller-up": "restart"},
                }
            },
            "checks": {
                "tensorboard-controller-up": {
                    "override": "replace",
                    "period": "30s",
                    "timeout": "20s",
                    "threshold": 4,
                    "http": {"url": f"http://localhost:{PROBE_PORT}{PROBE_PATH}"},
                }
            },
        }

        return Layer(layer_config)

    def _check_and_report_k8s_conflict(self, error) -> bool:
        """Return True if error status code is 409 (conflict), False otherwise."""
        if error.status.code == 409:
            self.logger.warning(f"Encountered a conflict: {error}")
            return True
        return False

    def _apply_k8s_resources(self, force_conflicts: bool = False) -> None:
        """Apply K8s resources.

        Args:
            force_conflicts (bool): *(optional)* Will "force" apply requests causing conflicting
                                    fields to change ownership to the field manager used in this
                                    charm.
                                    NOTE: This will only be used if initial regular apply() fails.
        """
        self.unit.status = MaintenanceStatus("Creating K8s resources")
        try:
            self.k8s_resource_handler.apply()
        except ApiError as error:
            if self._check_and_report_k8s_conflict(error) and force_conflicts:
                # conflict detected when applying K8s resources
                # re-apply K8s resources with forced conflict resolution
                self.unit.status = MaintenanceStatus("Force applying K8s resources")
                self.logger.warning("Apply K8s resources with forced changes against conflicts")
                self.k8s_resource_handler.apply(force=force_conflicts)
            else:
                raise GenericCharmRuntimeError("K8s resources creation failed") from error
        try:
            self.crd_resource_handler.apply()
        except ApiError as error:
            if self._check_and_report_k8s_conflict(error) and force_conflicts:
                # conflict detected when applying CRD resources
                # re-apply CRD resources with forced conflict resolution
                self.unit.status = MaintenanceStatus("Force applying CRD resources")
                self.logger.warning("Apply CRD resources with forced changes against conflicts")
                self.crd_resource_handler.apply(force=force_conflicts)
            else:
                raise GenericCharmRuntimeError("CRD resources creation failed") from error
        self.model.unit.status = MaintenanceStatus("K8s resources created")

    def _check_leader(self) -> None:
        """Check whether a unit is the leader."""
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.logger.warning("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _check_container_connection(self) -> None:
        """Check if connection can be made with container."""
        if not self.container.can_connect():
            raise ErrorWithStatus("Pod startup is not complete", MaintenanceStatus)

    def _check_status(self) -> None:
        """Check status of workload and set status accordingly."""
        self._check_leader()
        container = self.unit.get_container(self._container_name)
        if container:
            try:
                check = container.get_check("tensorboard-controller-up")
            except ModelError as error:
                raise GenericCharmRuntimeError(
                    "Failed to run health check on workload container"
                ) from error
            if check.status != CheckStatus.UP:
                self.logger.error(
                    f"Container {self._container_name} failed health check. It will be restarted."
                )
                raise ErrorWithStatus("Workload failed health check", MaintenanceStatus)
            else:
                self.model.unit.status = ActiveStatus()

    def _on_install(self, _) -> None:
        """Handle install event."""
        # deploy K8s resources to speed up deployment
        self._apply_k8s_resources()

    def _on_upgrade(self, _) -> None:
        """Handle upgrade event."""
        # force conflict resolution in K8s resources update
        self._on_event(_, force_conflicts=True)

    def _on_update_status(self, _) -> None:
        """Handle update status event."""
        self._on_event(_)
        try:
            self._check_status()
        except ErrorWithStatus as err:
            self.model.unit.status = err.status

    def _on_event(self, event, force_conflicts: bool = False) -> None:
        """Perform all required actions for the Charm.

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
            self.model.unit.status = err.status
            self.logger.error(f"Failed to handle {event} with error: {err}")
            return

        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(TensorboardController)
