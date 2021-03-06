from mock import patch
import pytest

from constants import SSH_KEY_1, SSH_KEY_RSA_1024, SSH_KEY_ECDSA_P256, SSH_KEY_DSA
from fixtures import session, users  # noqa: F401
from grouper.plugin.proxy import PluginProxy
from grouper.public_key import add_public_key, BadPublicKey
from plugins.ssh_key_policy import SshKeyPolicyPlugin


@patch("grouper.public_key.get_plugin_proxy")
def test_accepts_strong_rsa_keys(get_plugin_proxy, session, users):
    get_plugin_proxy.return_value = PluginProxy([SshKeyPolicyPlugin()])

    user = users["cbguder@a.co"]

    add_public_key(session, user, SSH_KEY_1)


@patch("grouper.public_key.get_plugin_proxy")
def test_rejects_weak_rsa_keys(get_plugin_proxy, session, users):
    get_plugin_proxy.return_value = PluginProxy([SshKeyPolicyPlugin()])

    user = users["cbguder@a.co"]

    with pytest.raises(BadPublicKey):
        add_public_key(session, user, SSH_KEY_RSA_1024)


@patch("grouper.public_key.get_plugin_proxy")
def test_rejects_dsa_keys(get_plugin_proxy, session, users):
    get_plugin_proxy.return_value = PluginProxy([SshKeyPolicyPlugin()])

    user = users["cbguder@a.co"]

    with pytest.raises(BadPublicKey):
        add_public_key(session, user, SSH_KEY_DSA)


@patch("grouper.public_key.get_plugin_proxy")
def test_rejects_ecdsa_keys(get_plugin_proxy, session, users):
    get_plugin_proxy.return_value = PluginProxy([SshKeyPolicyPlugin()])

    user = users["cbguder@a.co"]

    with pytest.raises(BadPublicKey):
        add_public_key(session, user, SSH_KEY_ECDSA_P256)
