import pytest
from pydantic import ValidationError

from schemas.users import BootstrapAdminRequest


def test_bootstrap_admin_request_requires_minimum_password_length():
    with pytest.raises(ValidationError):
        BootstrapAdminRequest(
            username='admin',
            password='short',
            full_name='Admin User',
        )


def test_bootstrap_admin_request_accepts_valid_payload():
    payload = BootstrapAdminRequest(
        username='admin',
        password='sufficiently-long',
        full_name='Admin User',
        email='admin@example.test',
    )
    assert payload.username == 'admin'
