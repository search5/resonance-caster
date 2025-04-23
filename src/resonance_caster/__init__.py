"""
팟캐스트 플랫폼 메인 애플리케이션 파일
Pyramid 웹 프레임워크를 사용한 메인 애플리케이션 구성
"""
from pyramid.config import Configurator
from pyramid.session import SignedCookieSessionFactory

my_session_factory = SignedCookieSessionFactory('some_secret_key')


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application."""
    with Configurator(settings=settings) as config:
        config.set_session_factory(my_session_factory)
        config.include('pyramid_jinja2')
        config.include('.routes')
        config.include('.security')
        config.scan()
    return config.make_wsgi_app()
