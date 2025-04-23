"""
JWT 인증 및 보안 기능
팟캐스트 플랫폼의 인증 및 권한 관리를 위한 보안 관련 기능
"""
import os
import jwt
import datetime
import bcrypt
from pyramid.authentication import CallbackAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.security import (
    Authenticated,
    Everyone,
)

from resonance_caster.services.firestore_service import FirestoreService

# 환경 변수에서 JWT 시크릿 키 가져오기
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key-here')
JWT_ALGORITHM = 'HS256'
JWT_EXP_DELTA_SECONDS = 86400  # 24시간


def hash_password(password):
    """비밀번호 해싱"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, hashed):
    """비밀번호 검증"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_jwt_token(user_id):
    """JWT 토큰 생성"""
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXP_DELTA_SECONDS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_jwt_token(token):
    """JWT 토큰 검증"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload['user_id']
    except (jwt.DecodeError, jwt.ExpiredSignatureError):
        return None


def get_user_from_request(request):
    """요청에서 현재 사용자 가져오기"""
    # 헤더에서 토큰 확인
    auth_header = request.headers.get('Authorization', '')

    if auth_header.startswith('Bearer '):
        token = auth_header[7:]  # 'Bearer ' 제거
        user_id = validate_jwt_token(token)

        if user_id:
            # Firestore에서 사용자 정보 가져오기
            firestore_service = FirestoreService()
            return firestore_service.get_user_by_id(user_id)

    # 쿠키에서 토큰 확인
    token = request.cookies.get('auth_token')
    if token:
        user_id = validate_jwt_token(token)

        if user_id:
            firestore_service = FirestoreService()
            return firestore_service.get_user_by_id(user_id)

    return None


class JWTAuthenticationPolicy(CallbackAuthenticationPolicy):
    """JWT 기반 인증 정책"""

    def unauthenticated_userid(self, request):
        """인증되지 않은 사용자 ID 가져오기"""
        # 헤더에서 토큰 확인
        auth_header = request.headers.get('Authorization', '')

        if auth_header.startswith('Bearer '):
            token = auth_header[7:]  # 'Bearer ' 제거
            return validate_jwt_token(token)

        # 쿠키에서 토큰 확인
        token = request.cookies.get('auth_token')
        if token:
            return validate_jwt_token(token)

        return None

    def callback(self, userid, request):
        """사용자 권한 콜백"""
        if userid is not None:
            return ['group:authenticated']

        return []


def includeme(config):
    """Pyramid 설정에 보안 기능 추가"""
    authn_policy = JWTAuthenticationPolicy()
    authz_policy = ACLAuthorizationPolicy()

    config.set_authentication_policy(authn_policy)
    config.set_authorization_policy(authz_policy)
