import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TestConfig  # noqa: E402
from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402


from flask import g  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402


class FreshUserClient(FlaskClient):
    """Fixture giữ app context mở suốt test nên `g` bị dùng chung giữa các client.
    Xóa user đã cache trong g trước mỗi request để mỗi client là một phiên độc lập."""

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        return super().open(*args, **kwargs)


class Cfg(TestConfig):
    UPLOAD_FOLDER = tempfile.mkdtemp()


@pytest.fixture()
def app():
    app = create_app(Cfg)
    app.test_client_class = FreshUserClient
    with app.app_context():
        from app.seed import run_seed
        run_seed(demo=True)
        for u in User.query.all():
            u.set_password("matkhau123")
            u.must_change_password = False
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def users(app):
    return {u.username: u for u in User.query.all()}


def login(client, username, password="matkhau123"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


@pytest.fixture()
def client_as(app):
    def make(username):
        c = app.test_client()
        r = login(c, username)
        assert r.status_code == 302, r.data
        return c
    return make
