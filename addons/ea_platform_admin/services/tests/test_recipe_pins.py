"""The firm server's recipe and this addon must say the same thing."""

import re
from pathlib import Path

import pytest

from ..catalogue import SIZES
from ..recipe import ALL_KEYS, REQUIRED_KEYS, render_user_data
from .test_provisioning import KEY, PUB, values

ROOT = Path(__file__).parents[4]
RECIPE = (ROOT / "deploy/firm/recipe.env").read_text(encoding="utf-8")
INSTALL = (ROOT / "deploy/firm/install-firm-server.sh").read_text(encoding="utf-8")
ACTION = (ROOT / ".github/actions/setup-odoo/action.yml").read_text(encoding="utf-8")


def pin(name):
    return re.search(rf"^{name}=(.+)$", RECIPE, re.M).group(1)


def test_a_firm_runs_the_odoo_commit_ci_tests():
    assert pin("ODOO_SHA") in ACTION
    assert re.fullmatch(r"[0-9a-f]{40}", pin("ODOO_SHA"))


def test_a_firm_runs_the_python_ci_tests():
    assert pin("PYTHON_VERSION") in ACTION


def test_downloads_are_pinned_by_digest():
    assert re.fullmatch(r"[0-9a-f]{64}", pin("UV_SHA256"))
    assert re.fullmatch(r"[0-9a-f]{64}", pin("WKHTMLTOX_SHA256"))
    assert "latest" not in pin("UV_URL")
    assert "latest" not in pin("WKHTMLTOX_URL")


@pytest.mark.parametrize("size", sorted(SIZES))
def test_sizes_agree_with_the_install_script(size):
    data = SIZES[size]
    line = re.search(rf"^\s*{size}\) WORKERS=(\d+); LIMIT_HARD_MB=(\d+);", INSTALL, re.M)
    assert line, size
    assert int(line.group(1)) == data["workers"]
    assert int(line.group(2)) == data["limit_memory_hard_mb"]


def test_the_sample_env_holds_exactly_what_the_control_plane_sends():
    sample = (ROOT / "deploy/firm/sample.env").read_text(encoding="utf-8")
    assert set(re.findall(r"^([A-Z0-9_]+)=", sample, re.M)) == set(ALL_KEYS)


def test_the_first_boot_text_is_valid_yaml_and_its_env_block_reads_back():
    yaml = pytest.importorskip("yaml")
    text = render_user_data(values(HEARTBEAT_TOKEN="HB123"), KEY, PUB)
    data = yaml.safe_load(text)
    assert data["ssh_pwauth"] is False
    files = {item["path"]: item for item in data["write_files"]}
    env = files["/etc/auditisa-firm/bootstrap.env"]
    assert env["permissions"] == "0600"
    assert "HEARTBEAT_TOKEN='HB123'" in env["content"].splitlines()
    # The install script refuses a file with any other kind of line.
    for line in env["content"].splitlines():
        assert re.fullmatch(r"[A-Z0-9_]+='[A-Za-z0-9 ._:@/+=,-]*'", line), line
    assert files["/etc/auditisa-firm/ssh_authorized_key"]["content"].strip() == KEY
    command = data["runcmd"][0]
    assert command[:2] == ["bash", "-c"]
    assert "$RELEASE_BASE_URL/$RELEASE_SHA.tar.gz" in command[2]


def test_the_scripts_use_the_paths_the_agent_reads():
    agent = (ROOT / "addons/ea_audit_firm_agent/models/firm_agent.py").read_text(encoding="utf-8")
    lib = (ROOT / "deploy/firm/firm-lib.sh").read_text(encoding="utf-8")
    assert '"/etc/auditisa-firm/secrets/heartbeat.token"' in agent
    assert '"/var/lib/auditisa-firm/status"' in agent
    assert '"/var/lib/auditisa-firm/spool/desired.json"' in agent
    assert "FIRM_VAR=$FIRM_PREFIX/var/lib/auditisa-firm" in lib
    assert "FIRM_STATUS=$FIRM_VAR/status" in lib
    assert "FIRM_SPOOL=$FIRM_VAR/spool" in lib


def test_every_figure_a_script_writes_is_one_the_agent_reads():
    from ea_audit_firm_agent.services.collect import STATUS_FILES
    folder = ROOT / "deploy/firm"
    written = set()
    for path in folder.glob("*.sh"):
        written |= set(re.findall(r"set_status ([a-z_0-9]+) ", path.read_text(encoding="utf-8")))
    assert written
    assert written <= set(STATUS_FILES), written - set(STATUS_FILES)
