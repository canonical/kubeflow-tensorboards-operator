#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import yaml
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus


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

        self.log = logging.getLogger(__name__)
        self.image = OCIImageResource(self, "oci-image")

        for event in [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
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
                            "ISTIO_GATEWAY": "kubeflow/kubeflow-gateway",
                            "TENSORBOARD_IMAGE": "tensorflow/tensorflow:2.1.0",
                        },
                    }
                ],
            },
            {
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(
                            Path("files/crds.yaml").read_text()
                        )
                    ],
                },
            },
        )

        self.model.unit.status = ActiveStatus()

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _check_image_details(self):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            raise CheckFailed(f"{e.status.message}", e.status_type)
        return image_details


if __name__ == "__main__":
    main(Operator)
