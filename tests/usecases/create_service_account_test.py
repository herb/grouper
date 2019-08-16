from typing import TYPE_CHECKING

from mock import call, MagicMock

from grouper.constants import MAX_NAME_LENGTH, SERVICE_ACCOUNT_VALIDATION, USER_ADMIN
from grouper.models.group import Group
from grouper.models.group_service_accounts import GroupServiceAccount
from grouper.models.service_account import ServiceAccount
from grouper.models.user import User
from grouper.plugin.base import BasePlugin
from grouper.plugin.exceptions import PluginRejectedMachineSet

if TYPE_CHECKING:
    from tests.setup import SetupTest


def test_success(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.add_user_to_group("gary@a.co", "some-group")

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account(
        "service@svc.localhost", "some-group", "machine-set", "description"
    )
    assert mock_ui.mock_calls == [
        call.created_service_account("service@svc.localhost", "some-group")
    ]

    # Check the User and ServiceAccount that were created.
    user = User.get(setup.session, name="service@svc.localhost")
    assert user is not None
    assert user.is_service_account
    assert user.enabled
    service = ServiceAccount.get(setup.session, name="service@svc.localhost")
    assert service is not None
    assert service.machine_set == "machine-set"
    assert service.description == "description"

    # Check that the ServiceAccount is owned by the correct Group.
    group = Group.get(setup.session, name="some-group")
    assert group is not None
    linkage = GroupServiceAccount.get(setup.session, service_account_id=service.id)
    assert linkage is not None
    assert linkage.group_id == group.id


def test_add_domain(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.add_user_to_group("gary@a.co", "some-group")

    mock_ui = MagicMock()
    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service", "some-group", "machine-set", "description")

    service = ServiceAccount.get(setup.session, name="service@svc.localhost")
    assert service is not None
    assert service.machine_set == "machine-set"
    assert service.description == "description"
    assert ServiceAccount.get(setup.session, name="service") is None


def test_admin_can_create(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.create_group("some-group")
        setup.add_user_to_group("gary@a.co", "admins")
        setup.grant_permission_to_group(USER_ADMIN, "", "admins")

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@svc.localhost", "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.created_service_account("service@svc.localhost", "some-group")
    ]

    service = ServiceAccount.get(setup.session, name="service@svc.localhost")
    assert service is not None
    assert service.machine_set == ""
    assert service.description == ""


def test_permission_denied(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.create_group("some-group")
        setup.create_user("gary@a.co")

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@svc.localhost", "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_permission_denied("service@svc.localhost", "some-group")
    ]


def test_invalid_name(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.add_user_to_group("gary@a.co", "some-group")

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@foo@bar", "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_invalid_name(
            "service@foo@bar",
            "service@foo@bar is not a valid service account name (does not match {})".format(
                SERVICE_ACCOUNT_VALIDATION
            ),
        )
    ]

    # Test a service account name that's one character longer than MAX_NAME_LENGTH minus the length
    # of the default email domain minus 1 (for the @).
    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    long_name = "x" * (MAX_NAME_LENGTH - len(setup.settings.service_account_email_domain))
    long_name += "@" + setup.settings.service_account_email_domain
    usecase.create_service_account(long_name, "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_invalid_name(
            long_name, "{} is longer than {} characters".format(long_name, MAX_NAME_LENGTH)
        )
    ]

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@a.co", "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_invalid_name(
            "service@a.co",
            "All service accounts must end in @{}".format(
                setup.settings.service_account_email_domain
            ),
        )
    ]


def test_invalid_owner(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.add_user_to_group("gary@a.co", "admins")
        setup.grant_permission_to_group(USER_ADMIN, "", "admins")

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@svc.localhost", "some-group", "", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_invalid_owner("service@svc.localhost", "some-group")
    ]


class MachineSetTestPlugin(BasePlugin):
    def check_machine_set(self, name, machine_set):
        # type: (str, str) -> None
        assert name == "service@svc.localhost"
        raise PluginRejectedMachineSet("some error message")


def test_invalid_machine_set(setup):
    # type: (SetupTest) -> None
    with setup.transaction():
        setup.add_user_to_group("gary@a.co", "some-group")

    setup.plugins.add_plugin(MachineSetTestPlugin())

    mock_ui = MagicMock()
    usecase = setup.usecase_factory.create_create_service_account_usecase("gary@a.co", mock_ui)
    usecase.create_service_account("service@svc.localhost", "some-group", "machine-set", "")
    assert mock_ui.mock_calls == [
        call.create_service_account_failed_invalid_machine_set(
            "service@svc.localhost", "machine-set", "some error message"
        )
    ]
