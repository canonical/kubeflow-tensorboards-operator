#!/usr/bin/env python3

import logging
from pathlib import Path

import yaml
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus



class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            self.model.unit.status = WaitingStatus("Waiting for leadership")
            return
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
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
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
                                    "verbs": ["create", "get", "list", "update", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["persistentvolumeclaims", "pods"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["services"],
                                    "verbs": ["create", "get", "list", "update", "watch"],
                                },
                                {
                                    "apiGroups": ["networking.istio.io"],
                                    "resources": ["virtualservices"],
                                    "verbs": ["get", "list", "create", "update", "watch"],
                                },
                                {
                                    "apiGroups": ["tensorboard.kubeflow.org"],
                                    "resources": ["tensorboards"],
                                    "verbs": ["get", "list", "create", "delete", "patch", "update", "watch"],
                                },
                                {
                                    "apiGroups": ["tensorboard.kubeflow.org"],
                                    "resources": ["tensorboards/status"],
                                    "verbs": ["get", "patch", "update"],
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
                        "name": "controller-manager",
                        "imageDetails": image_details,
                        "command": ["/manager"],
                        # "args": ["--enable-leader-election"],
                        "ports": [{"name": "http", "containerPort": config["port"]}],
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


if __name__ == "__main__":
    main(Operator)
