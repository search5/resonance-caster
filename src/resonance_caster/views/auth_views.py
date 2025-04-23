"""
인증 관련 뷰
회원가입, 로그인, 로그아웃 등 인증 관련 뷰 함수
"""
from pyramid.view import view_config
from pyramid.response import Response
from pyramid.httpexceptions import HTTPBadRequest, HTTPUnauthorized, HTTPFound

from resonance_caster.security import hash_password, create_jwt_token, verify_password
from resonance_caster.services.firestore_service import FirestoreService


@view_config(route_name='api_register', renderer='json', request_method='POST')
def register_view(request):
    """사용자 등록 API"""
    data = request.json_body

    # 필수 필드 확인
    required_fields = ['username', 'email', 'password']
    for field in required_fields:
        if field not in data:
            return HTTPBadRequest(json={'error': f'Missing required field: {field}'})

    firestore_service = FirestoreService()

    # 이메일 중복 확인
    existing_user = firestore_service.get_user_by_email(data['email'])
    if existing_user:
        return HTTPBadRequest(json={'error': 'Email already registered'})

    # 비밀번호 해싱
    password_hash = hash_password(data['password'])

    # 사용자 생성
    user_id = firestore_service.create_user(
        username=data['username'],
        email=data['email'],
        password_hash=password_hash
    )

    # JWT 토큰 생성
    token = create_jwt_token(user_id)

    return {
        'token': token,
        'user_id': user_id,
        'username': data['username']
    }


@view_config(route_name='api_login', renderer='json', request_method='POST')
def login_view(request):
    """사용자 로그인 API"""
    data = request.json_body

    # 필수 필드 확인
    if 'email' not in data or 'password' not in data:
        return HTTPBadRequest(json={'error': 'Email and password are required'})

    firestore_service = FirestoreService()

    # 이메일로 사용자 찾기
    user = firestore_service.get_user_by_email(data['email'])
    if not user:
        return HTTPUnauthorized(json={'error': 'Invalid credentials'})

    # 비밀번호 검증
    if not verify_password(data['password'], user['password_hash']):
        return HTTPUnauthorized(json={'error': 'Invalid credentials'})

    # JWT 토큰 생성
    token = create_jwt_token(user['id'])

    # 쿠키에 토큰 저장 옵션
    response = Response(json={
        'token': token,
        'user_id': user['id'],
        'username': user['username']
    })

    if data.get('remember', False):
        # 보안을 위해 쿠키는 HTTPS에서만 전송, JavaScript에서 접근 불가
        response.set_cookie(
            'auth_token',
            token,
            max_age=86400,  # 24시간
            httponly=True,
            # secure=request.scheme == 'https',
            path='/'
        )

    return response


@view_config(route_name='login', renderer='templates/login.jinja2', request_method='GET')
def login_page_view(request):
    """로그인 페이지"""
    return {'page_title': '로그인'}


@view_config(route_name='register', renderer='templates/register.jinja2', request_method='GET')
def register_page_view(request):
    """회원가입 페이지"""
    return {'page_title': '회원가입'}


@view_config(route_name='logout')
def logout_view(request):
    """로그아웃"""
    response = HTTPFound(location=request.route_url('home'))
    response.delete_cookie('auth_token')
    return response
