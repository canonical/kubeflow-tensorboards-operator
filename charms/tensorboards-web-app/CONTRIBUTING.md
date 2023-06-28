# Contributing

## Overview

This document explains the processes and practices recommended for contributing enhancements to
this operator.
- Generally, before developing enhancements to this charm, you should consider [opening an issue
  ](https://github.com/canonical/kubeflow-tensorboards-operator/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach
  us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju administrators of this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto
  the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Developing

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Testing

```shell
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

## Build charm

Build the Tensorboards Web App charm using:

```shell
charmcraft pack
```

## Upgrade manifests
The charm uses Jinja2 templates in order to store manifests that need to be applied during its deployment. The process for upgrading them is:

### Spot the differences between versions of a manifest file

1. Install `kustomize` using the official documentation [instructions](https://kubectl.docs.kubernetes.io/installation/kustomize/)
2. Clone [Kubeflow manifests](https://github.com/kubeflow/manifests) repo locally
3. `cd` into the repo and checkout to the branch or tag of the target version.
4. Build the manifests with `kustomize` and save the file:

`kustomize build apps/tensorboard/tensorboards-web-app/upstream/overlays/istio >> rendered_manifest_vX.yaml`

5. Checkout to the branch or tag of the version of the current manifest
6. Build the manifest with `kustomize` (see step 4) and save the file
7. Compare both files to spot the differences (e.g. using diff)

### Introduce changes

Once the comparison is done, add any changes to the relevant ClusterRoles and ClusterRoleBindings to the
  `templates/auth_manifests.yaml.j2` file and remember to:
  * Use the current model as the namespace
  * Use the application name as the name of any ClusterRoles, ClusterRoleBindings, or ServiceAccounts.


## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed Training Operator. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.# Contributing