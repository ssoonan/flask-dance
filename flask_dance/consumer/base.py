from __future__ import unicode_literals, print_function

from datetime import datetime, timedelta
import six
from lazy import lazy
# abstractmethod 같은 것들로 베이스 컨테이너에 미리 지정? > 굳이 상속받는 곳에서는 데코레이터를 다시 쓸 필요가 없다네. 흠 맞는 거 같기도 하고
from abc import ABCMeta, abstractmethod, abstractproperty
from werkzeug.datastructures import CallbackDict
import flask
from flask.signals import Namespace
from flask_dance.consumer.backend.session import SessionBackend
from flask_dance.utils import getattrd, timestamp_from_datetime

# signal이 뭐라고? subscribers에게 notify하는 게 목표라고 하네. modify가 목표는 아니고
# 보내는 것은 flask app이고, subscribers가 누가 될 것인가? 도 명시해줘야
# blinker로 주로 할 수 있는데, flask.signals에도 비슷한게 있다
# 근데 그래서 이 signal을 어디서 쓰는 거지? 쓰는 곳이 안 나와 있는 걸
_signals = Namespace()
oauth_authorized = _signals.signal('oauth-authorized')
oauth_error = _signals.signal('oauth-error')

# 이해할 것? 이 Base가 하는 역할이 무엇일까? 이걸 상속받아서 1이나 2가 나왔을텐데 말이지.. config 같은 기본적인 것들을 받는 역할인가?
# 1과 2의 공통적인 인터페이스 역할을 하는 추상 클래스 역할을 한다고 보면 될 거 같다.그럴 떄 이 abc가 쓰인다고 했으니까 말이다.
class BaseOAuthConsumerBlueprint(six.with_metaclass(ABCMeta, flask.Blueprint)):
    def __init__(self, name, import_name,
            static_folder=None, static_url_path=None, template_folder=None,
            url_prefix=None, subdomain=None, url_defaults=None, root_path=None,
            login_url=None, authorized_url=None, backend=None):

        bp_kwargs = dict(
            name=name,
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            url_prefix=url_prefix,
            subdomain=subdomain,
            url_defaults=url_defaults,
            root_path=root_path,
        )
        # `root_path` didn't exist in 0.10, and will cause an error if it's
        # passed in that version. Only pass `root_path` if it's set.
        if bp_kwargs["root_path"] is None:
            del bp_kwargs["root_path"]
        flask.Blueprint.__init__(self, **bp_kwargs)
        # add_url_rule : 기존 flask app에서 라우터를 추가하는 것과 동일한 역할을 한다고 한다. 근데 이렇게 하는 이유가 뭐라고 했지? 굳이 app을 만들 필요가 없어서? 그거는 근데
        # 블루프린트로 이미 해결된 것 아닌가 싶은데? 흠..
        login_url = login_url or "/{bp.name}"
        authorized_url = authorized_url or "/{bp.name}/authorized"

        self.add_url_rule(
            rule=login_url.format(bp=self),
            endpoint="login", # endpoint는 다른 곳에서 인식할 함수 이름. 걍 이름일 뿐
            view_func=self.login,
        )
        self.add_url_rule(
            rule=authorized_url.format(bp=self),
            endpoint="authorized",
            view_func=self.authorized,
        )

        if backend is None:
            self.backend = SessionBackend()
        elif callable(backend):
            self.backend = backend()
        else:
            self.backend = backend

        self.logged_in_funcs = []
        self.from_config = {}
        invalidate_token = lambda d: lazy.invalidate(self.session, "token")
        self.config = CallbackDict(on_update=invalidate_token)
        self.before_app_request(self.load_config)

    def load_config(self):
        """
        Used to dynamically load variables from the Flask application config
        into the blueprint. To tell this blueprint to pull configuration from
        the app, just set key-value pairs in the ``from_config`` dict. Keys
        are the name of the local variable to set on the blueprint object,
        and values are the variable name in the Flask application config.
        For example:

            blueprint.from_config["session.client_id"] = "GITHUB_OAUTH_CLIENT_ID"

        """
        for local_var, config_var in self.from_config.items():
            value = flask.current_app.config.get(config_var)
            if value:
                if "." in local_var:
                    # this is a dotpath -- needs special handling
                    body, tail = local_var.rsplit(".", 1)
                    obj = getattrd(self, body)
                    setattr(obj, tail, value)
                else:
                    # just use a normal setattr call
                    setattr(self, local_var, value)

    @property
    def token(self):
        _token = self.backend.get(self)
        if _token and _token.get("expires_in") and _token.get("expires_at"):
            # Update the `expires_in` value, so that requests-oauthlib
            # can handle automatic token refreshing. Assume that
            # `expires_at` is a valid Unix timestamp.
            expires_at = datetime.utcfromtimestamp(_token["expires_at"])
            expires_in = expires_at - datetime.utcnow()
            _token["expires_in"] = expires_in.total_seconds()
        return _token

    @token.setter
    def token(self, value):
        _token = value
        if _token and _token.get("expires_in"):
            # Set the `expires_at` value, overwriting any value
            # that may already be there.
            delta = timedelta(seconds=_token["expires_in"])
            expires_at = datetime.utcnow() + delta
            _token["expires_at"] = timestamp_from_datetime(expires_at)
        self.backend.set(self, _token)
        lazy.invalidate(self.session, "token")

    @token.deleter
    def token(self):
        self.backend.delete(self)
        lazy.invalidate(self.session, "token")

    @abstractproperty
    def session(self):
        """
        This is a session between the consumer (your website) and the provider
        (e.g. Twitter). It is *not* a session between a user of your website
        and your website.
        """
        raise NotImplementedError()

    @abstractmethod
    def login(self):
        raise NotImplementedError()

    @abstractmethod
    def authorized(self):
        """
        This is the route/function that the user will be redirected to by
        the provider (e.g. Twitter) after the user has logged into the
        provider's website and authorized your app to access their account.
        """
        raise NotImplementedError()
