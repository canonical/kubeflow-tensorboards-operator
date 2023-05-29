#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Dict, Tuple

import yaml
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from charms.istio_pilot.v0.istio_gateway_info import GatewayRelationError, GatewayRequirer
from oci_image import OCIImageResource, OCIImageResourceError
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, Container, MaintenanceStatus, ModelError, WaitingStatus

K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
]
CRD_RESOURCE_FILES = [
    "src/templates/crds.yaml.j2",
]

class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.image = OCIImageResource(self, "oci-image")
        self.logger = logging.getLogger(__name__)

        # retrieve configuration and base settings
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
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

        for event in [
            self.on.install,
            self.on.leader_elected,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["gateway-info"].relation_changed,
        ]:
            self.framework.observe(event, self.main)

    def main(self, event):
        try:
            self._check_leader()

            image_details = self._check_image_details()
        except CheckFailed as check_failed:
            self.model.unit.status = check_failed.status
            return

        config = self.model.config

        try:
            gateway_data = self.gateway.get_relation_data()
        except GatewayRelationError:
            self.model.unit.status = WaitingStatus("Waiting for gateway info relation")
            return

        gateway_ns = gateway_data["gateway_namespace"]
        gateway_name = gateway_data["gateway_name"]

        self.model.unit.status = MaintenanceStatus("Setting pod spec")

        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": ["apps"],
                                    "resources": ["deployments"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["persistentvolumeclaims", "pods"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["services"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["networking.istio.io"],
                                    "resources": ["virtualservices"],
                                    "verbs": [
                                        "get",
                                        "list",
                                        "create",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["tensorboard.kubeflow.org"],
                                    "resources": ["tensorboards"],
                                    "verbs": [
                                        "get",
                                        "list",
                                        "create",
                                        "delete",
                                        "patch",
                                        "update",
                                        "watch",
                                    ],
                                },
                                {
                                    "apiGroups": ["tensorboard.kubeflow.org"],
                                    "resources": ["tensorboards/status"],
                                    "verbs": ["get", "patch", "update"],
                                },
                                {
                                    "apiGroups": ["tensorboard.kubeflow.org"],
                                    "resources": ["tensorboards/finalizers"],
                                    "verbs": ["update"],
                                },
                                {
                                    "apiGroups": ["storage.k8s.io"],
                                    "resources": ["storageclasses"],
                                    "verbs": ["get", "list", "watch"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "deployment",
                        "imageDetails": image_details,
                        "command": ["/manager"],
                        # "args": ["--enable-leader-election"],
                        "ports": [{"name": "http", "containerPort": config["port"]}],
                        "envConfig": {
                            "ISTIO_GATEWAY": f"{gateway_ns}/{gateway_name}",
                            "TENSORBOARD_IMAGE": "tensorflow/tensorflow:2.1.0",
                        },
                    }
                ],
            },
            {
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(Path("files/crds.yaml").read_text())
                    ],
                },
            },
        )

        self.model.unit.status = ActiveStatus()

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

    def _check_image_details(self):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            raise CheckFailed(f"{e.status.message}", e.status_type)
        return image_details


if __name__ == "__main__":
    main(Operator)
