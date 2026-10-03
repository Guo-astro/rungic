"""The desktop user's Codex set up at first login (docs/59, docs/64): the kconf_update script that
rungic-voice-agent installs, run as kconf_update runs it, against a temporary home. It adds the
rungic-desktop MCP server and the skills directory, keeps what the user's config already has, and
running it again changes nothing."""
import configparser
import os
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
UPDATE = ROOT / 'agent/assistant/kconf_update'


def run(home):
    subprocess.run(['sh', str(UPDATE / 'rungic-codex-setup.sh')], env={'HOME': str(home), 'PATH': os.environ['PATH']},
                   check=True, capture_output=True)


# covers: agent.instructions/E4
def test_first_login_sets_up_codex_and_again_changes_nothing(tmp_path):
    run(tmp_path)
    config = tmp_path / '.codex/config.toml'
    assert (tmp_path / '.codex/skills').is_dir()
    server = tomllib.loads(config.read_text())['mcp_servers']['rungic-desktop']
    assert server['command'] == '/usr/bin/rungic-cua' and server['args'] == ['mcp']
    first = config.read_bytes()
    run(tmp_path)
    assert config.read_bytes() == first


# covers: agent.instructions/E4
def test_the_users_own_config_is_kept(tmp_path):
    config = tmp_path / '.codex/config.toml'
    config.parent.mkdir()
    mine = 'model = "gpt-6-luna"\n\n[mcp_servers.mine]\ncommand = "/home/me/bin/tool"\n'
    config.write_text(mine)
    run(tmp_path)
    run(tmp_path)
    text = config.read_text()
    assert text.startswith(mine)
    parsed = tomllib.loads(text)
    assert set(parsed['mcp_servers']) == {'mine', 'rungic-desktop'} and parsed['model'] == 'gpt-6-luna'
    # A user who already has the server (an older install wrote it) keeps their own entry.
    config.write_text('[mcp_servers.rungic-desktop]\ncommand = "/opt/cua"\n')
    run(tmp_path)
    assert tomllib.loads(config.read_text())['mcp_servers']['rungic-desktop'] == {'command': '/opt/cua'}


# covers: agent.instructions/E4
def test_kconf_update_runs_it_once_per_user(tmp_path):
    upd = configparser.ConfigParser(strict=False)
    upd.read_string('[top]\n' + (UPDATE / 'rungic-voice-agent.upd').read_text())
    assert upd['top']['Version'] == '6'                         # the format kconf_update 6 reads
    assert upd['top']['Id'] == 'rungic-codex-v1'                # kconf_update remembers an Id per user
    assert upd['top']['Script'] == 'rungic-codex-setup.sh,sh'
    build = (ROOT / 'packaging/rungic-voice-agent/build.sh').read_text()
    for name in ('rungic-voice-agent.upd', 'rungic-codex-setup.sh'):
        assert f'/usr/share/kconf_update/{name}' in build
