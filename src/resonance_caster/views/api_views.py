"""
API 관련 뷰
팟캐스트 웹 서비스를 위한 RESTful API 엔드포인트
"""
from uuid import uuid4

from pyramid.view import view_config
from pyramid.httpexceptions import HTTPBadRequest, HTTPNotFound, HTTPForbidden
import base64
import tempfile

from slugify import slugify

from resonance_caster.security import get_user_from_request
from resonance_caster.services.firestore_service import FirestoreService
from resonance_caster.services.gcs_service import GCSService


@view_config(route_name='api_podcasts', renderer='json', request_method='GET')
def api_podcasts_list(request):
    """팟캐스트 목록 API"""
    firestore_service = FirestoreService()

    # 페이지네이션 파라미터
    limit = int(request.params.get('limit', 10))
    limit = min(limit, 50)  # 최대 50개로 제한

    podcasts = firestore_service.get_podcasts(limit=limit)

    return {'podcasts': podcasts}


@view_config(route_name='api_podcasts', renderer='json', request_method='POST')
def api_podcasts_create(request):
    """팟캐스트 생성 API"""
    user = get_user_from_request(request)

    if not user:
        return HTTPForbidden(json={'error': 'Authentication required'})

    data = request.json_body

    # 필수 필드 확인
    if 'title' not in data:
        return HTTPBadRequest(json={'error': 'Title is required'})

    firestore_service = FirestoreService()
    gcs_service = GCSService()

    # 커버 이미지 처리 (base64로 제공된 경우)
    cover_image_url = ''
    if 'cover_image' in data and data['cover_image']:
        try:
            # base64 이미지 데이터 디코딩
            image_data = base64.b64decode(data['cover_image'])

            # 임시 파일로 저장
            with tempfile.NamedTemporaryFile(suffix='.jpg') as temp_file:
                temp_file.write(image_data)
                temp_file.flush()

                # GCS에 업로드
                cover_image_url = gcs_service.upload_file(
                    temp_file,
                    content_type='image/jpeg',
                    directory='podcast_covers'
                )
        except Exception as e:
            return HTTPBadRequest(json={'error': f'Invalid image data: {str(e)}'})

    # 팟캐스트 생성
    podcast_id = firestore_service.create_podcast(
        title=data['title'],
        description=data.get('description', ''),
        cover_image_url=cover_image_url,
        user_id=user['id']
    )

    # 생성된 팟캐스트 정보 반환
    podcast = firestore_service.get_podcast(podcast_id)

    return podcast


@view_config(route_name='api_podcast', renderer='json', request_method='GET')
def api_podcast_detail(request):
    """팟캐스트 상세 API"""
    podcast_id = request.matchdict['podcast_id']

    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    if not podcast:
        return HTTPNotFound(json={'error': 'Podcast not found'})

    # 에피소드 정보 포함 여부
    include_episodes = request.params.get('include_episodes', 'true').lower() == 'true'

    if include_episodes:
        # 에피소드 정보도 함께 가져오기
        podcast['episodes'] = firestore_service.get_podcast_episodes(podcast_id)

    return podcast


@view_config(route_name='api_episodes', renderer='json', request_method='GET')
def api_episodes_list(request):
    """팟캐스트의 에피소드 목록 API"""
    podcast_id = request.matchdict['podcast_id']

    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    if not podcast:
        return HTTPNotFound(json={'error': 'Podcast not found'})

    episodes = firestore_service.get_podcast_episodes(podcast_id)

    return {'episodes': episodes}


@view_config(route_name='api_episodes', renderer='json', request_method='POST')
def api_episodes_create(request):
    """에피소드 생성 API"""
    user = get_user_from_request(request)

    if not user:
        return HTTPForbidden(json={'error': 'Authentication required'})

    podcast_id = request.matchdict['podcast_id']

    firestore_service = FirestoreService()

    # 팟캐스트 소유권 확인
    podcast = firestore_service.get_podcast(podcast_id)
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden(json={'error': 'You do not have permission to add episodes to this podcast'})

    try:
        # JSON 형식 또는 form-encoded 형식 처리
        try:
            data = request.json_body
        except (ValueError, AttributeError):
            # form-encoded 형식 처리
            data = {k: v for k, v in request.POST.items()}

        # 필수 필드 확인
        if 'title' not in data or 'audio_data' not in data:
            return HTTPBadRequest(json={'error': 'Title and audio_data are required'})

        # base64 오디오 데이터 디코딩
        audio_data = base64.b64decode(data['audio_data'])

        # 임시 파일로 저장
        with tempfile.NamedTemporaryFile(suffix='.mp3') as temp_file:
            temp_file.write(audio_data)
            temp_file.flush()

            # 파일을 GCS에 업로드
            gcs_service = GCSService()

            # 파일명 생성 (URL에 사용될 친화적인 이름)
            from pyramid.path import DottedNameResolver
            resolver = DottedNameResolver()
            slugify = resolver.resolve('pyramid.util.slugify')

            sanitized_title = slugify(data['title'])
            if not sanitized_title:
                sanitized_title = f"episode-{uuid4().hex[:8]}"

            temp_file.seek(0)
            upload_result = gcs_service.upload_file(
                temp_file,
                content_type='audio/mpeg',
                directory=f'podcasts/{podcast_id}'
            )

            # 임시 ID로 스트리밍 URL 생성
            temp_id = 'temp_' + uuid4().hex
            streaming_url = f"/episodes/{temp_id}/{sanitized_title}.mp3"

            # 에피소드 정보 저장
            episode_data = {
                'podcast_id': podcast_id,
                'title': data['title'],
                'description': data.get('description', ''),
                'audio_url': upload_result['gcs_path'],  # GCS 내부 경로
                'filename': sanitized_title,  # URL에 사용할 파일명
                'streaming_url': streaming_url,  # 임시 스트리밍 URL
                'duration': data.get('duration', 0),  # 클라이언트에서 계산된 길이 또는 0
                'play_count': 0  # 재생 카운터 초기화
            }

            # Firestore에 에피소드 생성
            episode_id = firestore_service.create_episode(**episode_data)

            # 실제 ID로 스트리밍 URL 업데이트
            real_streaming_url = f"/episodes/{episode_id}/{sanitized_title}.mp3"
            firestore_service.update_episode_streaming_url(episode_id, real_streaming_url)

            # 생성된 에피소드 정보 가져오기
            episode = firestore_service.get_episode(episode_id)

            return episode

    except Exception as e:
        import traceback
        traceback.print_exc()
        return HTTPBadRequest(json={'error': f'Error processing audio data: {str(e)}'})


@view_config(route_name='api_episode', renderer='json', request_method='GET')
def api_episode_detail(request):
    """에피소드 상세 API"""
    episode_id = request.matchdict['episode_id']

    firestore_service = FirestoreService()
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound(json={'error': 'Episode not found'})

    return episode


@view_config(route_name='api_episode', renderer='json', request_method='DELETE')
def api_episode_delete(request):
    """에피소드 삭제 API"""
    user = get_user_from_request(request)

    if not user:
        return HTTPForbidden(json={'error': 'Authentication required'})

    episode_id = request.matchdict['episode_id']

    firestore_service = FirestoreService()
    gcs_service = GCSService()

    # 에피소드 정보 가져오기
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound(json={'error': 'Episode not found'})

    # 팟캐스트 소유권 확인
    podcast = firestore_service.get_podcast(episode['podcast_id'])
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden(json={'error': 'You do not have permission to delete this episode'})

    # GCS에서 오디오 파일 삭제
    if episode['audio_url']:
        gcs_service.delete_file(episode['audio_url'])

    # Firestore에서 에피소드 삭제
    success = firestore_service.delete_episode(episode_id, user['id'])

    return {'success': success}
