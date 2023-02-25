import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
resources = {"oci-image": METADATA["resources"]["oci-image"]["upstream-source"]}
twa = SimpleNamespace(name="tensorboard-webapp", resources=resources)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, twa_charm):
    await ops_test.model.deploy(twa_charm, resources=twa.resources, application_name=twa.name)

    await ops_test.model.wait_for_idle(timeout=60 * 10)
