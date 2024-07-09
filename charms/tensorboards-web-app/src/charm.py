#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju Charm for Tensorboards Web App."""

import logging
from typing import Dict
from pathlib import Path
import yaml

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from charmed_kubeflow_chisme.kubernetes import (
    KubernetesResourceHandler,
    create_charm_default_labels,
)
from charmed_kubeflow_chisme.lightkube.batch import delete_many
from charmed_kubeflow_chisme.pebble import update_layer
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from lightkube.resources.core_v1 import ServiceAccount
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Container, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
K8S_RESOURCES = {
    "template_files": ["src/templates/auth_manifests.yaml.j2"],
    "resource_types": {ClusterRole, ClusterRoleBinding, ServiceAccount},
    "scope": "tensorboard",
}
LIGHTKUBE_FIELD_MANAGER = "lightkube"
PORT = 5000


class TensorboardsWebApp(CharmBase):
    def __init__(self, *args):
        """Initialize charm and setup the container."""
        super().__init__(*args)

        self.logger = logging.getLogger(__name__)
        self._namespace = self.model.name
        self._name = self.app.name

        # Explicitly define container name since the charm can be deployed with different app name
        self._container_name = list(METADATA["containers"])[0]
        self._container = self.unit.get_container(self._container_name)
        self._k8s_resource_handler = None

        http_service_port = ServicePort(PORT, name="http")
        self.service_patcher = KubernetesServicePatch(
            self, [http_service_port], service_name=f"{self._name}"
        )

        # Set up event handlers
        self.framework.observe(self.on.upgrade_charm, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.leader_elected, self._on_event)
        self.framework.observe(self.on["ingress"].relation_changed, self._on_event)
        self.framework.observe(self.on.tensorboards_web_app_pebble_ready, self._on_event)

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)

        # add link in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name="dashboard-links",
            dashboard_links=[
                DashboardLink(
                    text="TensorBoards",
                    link="/tensorboards/",
                    type="item",
                    icon="assessment",
                    location="menu",
                )
            ],
        )

        self._logging = LogForwarder(charm=self)

    @property
    def container(self) -> Container:
        """Return tensorboard-controller container object."""
        return self._container

    @property
    def k8s_resource_handler(self) -> KubernetesResourceHandler:
        """Get the K8S resource handler."""
        context = {
            "app_name": self._name,
            "namespace": self._namespace,
        }

        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=LIGHTKUBE_FIELD_MANAGER,
                context=context,
                template_files=K8S_RESOURCES["template_files"],
                resource_types=K8S_RESOURCES["resource_types"],
                labels=create_charm_default_labels(
                    application_name=self.app.name,
                    model_name=self.model.name,
                    scope=K8S_RESOURCES["scope"],
                ),
                logger=self.logger,
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        """Set the K8S resource handler"""
        self._k8s_resource_handler = handler

    @property
    def _env_vars(self) -> Dict[str, str]:
        """Return environment variables based on model configuration."""
        config = self.model.config
        env_vars = {
            "APP_PREFIX": "/tensorboards",
            "APP_SECURE_COOKIES": str(config["secure-cookies"]),
            "BACKEND_MODE": config["backend-mode"],
            "USERID_HEADER": "kubeflow-userid",
            "USERID_PREFIX": "",
        }

        return env_vars

    @property
    def _tensorboards_web_app_layer(self) -> Layer:
        """Create and return Pebble framework layer."""
        exec_command = (
            "gunicorn" " -w 3" f" --bind 0.0.0.0:{PORT}" " --access-logfile" " - entrypoint:app"
        )

        layer_config = {
            "summary": "tensorboards-web-app layer",
            "description": "Pebble config layer for tensorboards-web-app",
            "services": {
                self._container_name: {
                    "override": "replace",
                    "summary": "Entrypoint of tensorboards-web-app image",
                    "command": exec_command,
                    "startup": "enabled",
                    "environment": self._env_vars,
                    "on-check-failure": {"tensorboards-web-app-up": "restart"},
                }
            },
            "checks": {
                "tensorboards-web-app-up": {
                    "override": "replace",
                    "period": "30s",
                    "http": {"url": f"http://localhost:{PORT}"},
                },
            },
        }

        return Layer(layer_config)

    def _on_install(self, _) -> None:
        """Perform installation only actions."""
        try:
            # Deploy K8S resources to speed up deployment
            self._apply_k8s_resources()
        except ErrorWithStatus as error:
            self._log_and_set_status(error.status)
        return

    def _on_remove(self, _) -> None:
        """Remove all resources."""
        self._log_and_set_status(MaintenanceStatus("Removing K8S resources"))
        try:
            self.k8s_resource_handler.delete()
        except ApiError as error:
            # Do not log/report when resources were not found
            if error.status.code != 404:
                self.logger.error(f"Removing K8S resources failed with error: {error}")
                raise GenericCharmRuntimeError("Removing K8s resources failed") from error

    def _on_event(self, event) -> None:
        """Perform required actions for every event."""
        try:
            self._check_leader()
            self._apply_k8s_resources()
            update_layer(
                self._container_name,
                self._container,
                self._tensorboards_web_app_layer,
                self.logger,
            )
            interfaces = self._get_interfaces()
            self._configure_mesh(interfaces)
            self.unit.status = ActiveStatus()

        except ErrorWithStatus as error:
            self._log_and_set_status(error.status)
            return

        self.unit.status = ActiveStatus()

    def _apply_k8s_resources(self) -> None:
        """Deploy K8S resources."""
        try:
            self._log_and_set_status(MaintenanceStatus("Applying K8S resources"))
            self.k8s_resource_handler.apply()
        except ApiError:
            raise ErrorWithStatus("Applying K8S resources failed", BlockedStatus)
        self._log_and_set_status(MaintenanceStatus("K8S resources applied"))

    def _configure_mesh(self, interfaces) -> None:
        if interfaces["ingress"]:
            interfaces["ingress"].send_data(
                {
                    "prefix": "/tensorboards",
                    "rewrite": "/",
                    "service": self.app.name,
                    "port": PORT,
                }
            )
        else:
            raise ErrorWithStatus("Please relate to istio-pilot:ingress", BlockedStatus)

    def _check_leader(self) -> None:
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as error:
            raise ErrorWithStatus(error, WaitingStatus)
        except NoCompatibleVersions as error:
            raise ErrorWithStatus(error, BlockedStatus)
        return interfaces

    def _log_and_set_status(self, status):
        # Copied from Istio-pilot charm
        """Sets the status of the charm and logs the status message.

        TODO: Move this to Chisme

        Args:
            status: The status to set
        """
        self.unit.status = status

        log_destination_map = {
            ActiveStatus: self.logger.info,
            BlockedStatus: self.logger.warning,
            MaintenanceStatus: self.logger.info,
            WaitingStatus: self.logger.info,
        }

        log_destination_map[type(status)](status.message)


if __name__ == "__main__":
    main(TensorboardsWebApp)
