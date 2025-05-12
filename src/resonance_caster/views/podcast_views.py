"""
팟캐스트 관련 뷰
팟캐스트 목록, 상세, 업로드 등의 뷰 함수
"""
import datetime
import traceback
from os import getenv
from uuid import uuid4

from google.cloud import storage
from pyramid.view import view_config
from pyramid.response import Response
from pyramid.httpexceptions import HTTPNotFound, HTTPForbidden, HTTPBadRequest, HTTPFound
import json
import tempfile
from pydub import AudioSegment

from resonance_caster.security import get_user_from_request
from resonance_caster.services.firestore_service import FirestoreService
from resonance_caster.services.gcs_service import GCSService


@view_config(route_name='home', renderer='templates/home.jinja2')
def home_view(request):
    """홈페이지 뷰"""
    firestore_service = FirestoreService()
    featured_podcasts = firestore_service.get_podcasts(limit=6)

    # 현재 사용자 정보 가져오기
    user = get_user_from_request(request)

    return {
        'page_title': '팟캐스트 플랫폼',
        'featured_podcasts': featured_podcasts,
        'user': user
    }

@view_config(route_name='podcasts', renderer='templates/podcasts.jinja2')
def podcasts_view(request):
    """팟캐스트 목록 뷰"""
    firestore_service = FirestoreService()
    podcasts = firestore_service.get_podcasts(limit=20)

    # 현재 사용자 정보 가져오기
    user = get_user_from_request(request)

    return {
        'page_title': '팟캐스트 목록',
        'podcasts': podcasts,
        'user': user
    }

@view_config(route_name='podcast', renderer='templates/podcasts_detail.jinja2')
def podcast_detail_view(request):
    """팟캐스트 상세 뷰"""
    podcast_id = request.matchdict['podcast_id']

    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    if not podcast:
        return HTTPNotFound()

    episodes = firestore_service.get_podcast_episodes(podcast_id)

    # 현재 사용자 정보 가져오기
    user = get_user_from_request(request)

    # 사용자가 팟캐스트 소유자인지 확인
    is_owner = user and user['id'] == podcast['user_id']

    return {
        'page_title': podcast['title'],
        'podcast': podcast,
        'episodes': episodes,
        'user': user,
        'is_owner': is_owner
    }

@view_config(route_name='upload', request_method='GET', renderer='templates/upload.jinja2')
def upload_form_view(request):
    """업로드 폼 뷰"""
    user = get_user_from_request(request)

    if not user:
        return HTTPFound(location=request.route_url('login'))

    firestore_service = FirestoreService()
    user_podcasts = firestore_service.get_user_podcasts(user['id'])

    return {
        'page_title': '새 에피소드 업로드',
        'user_podcasts': user_podcasts,
        'user': user
    }


@view_config(route_name='upload', request_method='POST')
def upload_process_view(request):
    """에피소드 업로드 처리"""
    user = get_user_from_request(request)

    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 폼 데이터 가져오기
    podcast_id = request.POST.get('podcast_id')
    title = request.POST.get('title')
    description = request.POST.get('description')

    # 파일 업로드 처리
    audio_file = request.POST.get('audio_file')

    if not podcast_id or not title:
        return HTTPBadRequest(detail='Missing required fields')

    firestore_service = FirestoreService()

    # 팟캐스트 소유권 확인
    podcast = firestore_service.get_podcast(podcast_id)
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden()

    gcs_service = GCSService()

    # 파일명 생성 (URL에 사용될 친화적인 이름)
    sanitized_title = f"episode-{uuid4().hex[:8]}"

    # 오디오 파일 처리 및 GCS에 업로드
    with tempfile.NamedTemporaryFile(suffix='.mp3') as temp_file:
        audio_file.file.seek(0)
        temp_file.write(audio_file.file.read())
        temp_file.flush()

        # 오디오 길이 계산 (초 단위)
        audio = AudioSegment.from_mp3(temp_file.name)
        duration = len(audio) // 1000  # 밀리초를 초로 변환

        # 파일 위치를 처음으로 되돌리고 업로드
        temp_file.seek(0)
        upload_result = gcs_service.upload_file(
            temp_file,
            content_type='audio/mpeg',
            directory=f'podcasts/{podcast_id}'
        )

    # 임시 ID로 스트리밍 URL 생성
    temp_id = 'temp_' + uuid4().hex
    streaming_url = f"/episodes/{temp_id}/{sanitized_title}.mp3"

    # DB에 에피소드 추가
    episode_id = firestore_service.create_episode(
        podcast_id=podcast_id,
        title=title,
        description=description,
        audio_url=upload_result['gcs_path'],  # GCS 내부 경로
        filename=sanitized_title,  # URL에 사용할 파일명
        streaming_url=streaming_url,  # 임시 스트리밍 URL
        duration=duration,
        play_count=0
    )

    # 실제 ID로 스트리밍 URL 업데이트
    real_streaming_url = f"/episodes/{episode_id}/{sanitized_title}.mp3"
    firestore_service.update_episode_streaming_url(episode_id, real_streaming_url)

    return HTTPFound(location=request.route_url('podcast', podcast_id=podcast_id))

@view_config(route_name='listen')
def listen_view(request):
    """에피소드 청취 뷰"""
    episode_id = request.matchdict['episode_id']

    firestore_service = FirestoreService()
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound()

    # 스트리밍 URL 반환
    return HTTPFound(location=episode['audio_url'])

@view_config(route_name='rss_feed')
def rss_feed_view(request):
    """팟캐스트 RSS 피드 생성"""
    podcast_id = request.matchdict['podcast_id']

    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    if not podcast:
        return HTTPNotFound()

    episodes = firestore_service.get_podcast_episodes(podcast_id)

    # RSS XML 생성
    rss_xml = generate_rss_feed(request, podcast, episodes)

    return Response(rss_xml, content_type='text/xml')


def generate_rss_feed(request, podcast, episodes):
    """팟캐스트용 RSS 피드 생성"""
    # RSS 2.0 + iTunes 확장 포맷에 맞는 XML 생성
    podcast_url = request.route_url('podcast', podcast_id=podcast['id'])
    host_url = request.host_url  # 호스트 URL (도메인)

    rss_template = """<?xml version="1.0" encoding="UTF-8"?>
    <rss xmlns:itunes="http://www.itunes.com/DTDs/Podcast-1.0.dtd" version="2.0">
    <channel>
        <title>{title}</title>
        <description><![CDATA[{description}]]></description>
        <link>{link}</link>
        <language>ko-kr</language>
        <itunes:author>{author}</itunes:author>
        <itunes:image href="{image_url}" />
        {items}
    </channel>
    </rss>
    """

    items = ""
    for episode in episodes:
        # published_at이 문자열이면 datetime으로 파싱
        if isinstance(episode['published_at'], str):
            try:
                pub_date_obj = datetime.datetime.fromisoformat(episode['published_at'].replace('Z', '+00:00'))
            except ValueError:
                # 파싱 실패시 현재 시간 사용
                pub_date_obj = datetime.datetime.now()
        else:
            pub_date_obj = episode['published_at']

        pub_date = pub_date_obj.strftime('%a, %d %b %Y %H:%M:%S +0900')

        # 저장된 스트리밍 URL 사용 (상대 URL을 절대 URL로 변환)
        # streaming_url이 이미 절대 URL인 경우 그대로 사용
        streaming_url = episode.get('streaming_url', '')
        if streaming_url and not streaming_url.startswith('http'):
            streaming_url = host_url + "/" + streaming_url.lstrip('/')

        item_template = """
        <item>
            <title>{title}</title>
            <description><![CDATA[{description}]]></description>
            <pubDate>{pub_date}</pubDate>
            <enclosure url="{audio_url}" length="{length}" type="audio/mpeg" />
            <itunes:duration>{duration}</itunes:duration>
            <guid isPermaLink="false">{guid}</guid>
        </item>
        """

        items += item_template.format(
            title=episode['title'],
            description=episode['description'] or '',
            pub_date=pub_date,
            audio_url=streaming_url,
            length='',  # 파일 크기를 계산하기 어려워 0으로 설정
            duration=format_duration(episode['duration']),
            guid=streaming_url
        )

    # 사용자 정보 가져오기
    firestore_service = FirestoreService()
    user = firestore_service.get_user_by_id(podcast['user_id'])
    author = user['username'] if user else 'Unknown'

    # 이미지 URL이 상대 경로인 경우 절대 URL로 변환
    image_url = podcast.get('cover_image_url', '')
    if image_url and not image_url.startswith('http'):
        image_url = host_url + image_url.lstrip('/')

    return rss_template.format(
        title=podcast['title'],
        description=podcast['description'] or '',
        link=podcast_url,
        author=author,
        image_url=image_url,
        items=items
    )

def format_duration(seconds):
    """초를 HH:MM:SS 형식으로 변환"""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"


@view_config(route_name='stream_episode')
def stream_episode_view(request):
    """에피소드 스트리밍 뷰"""
    episode_id = request.matchdict['episode_id']
    filename = request.matchdict['filename']  # URL에서 .mp3 확장자를 가진 파일명

    # Firestore에서 에피소드 정보 가져오기
    firestore_service = FirestoreService()
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound()

    # 청취 통계 기록
    record_episode_play(episode_id, request)

    # GCS에서 파일 가져오기
    try:
        bucket_name = request.registry.settings.get('gcs_bucket_name') or getenv('GCS_BUCKET_NAME')

        client = storage.Client(project=getenv("PROJECT_ID"))
        bucket = client.bucket(bucket_name)

        # Firestore에 저장된 GCS 경로 사용
        blob = bucket.get_blob(episode['audio_url'])

        # 파일 존재 확인
        if not blob:
            return HTTPNotFound()

        # HTTP 헤더 설정
        headers = {
            'Content-Type': 'audio/mpeg',
            'Content-Disposition': f'inline; filename="{filename}.mp3"',
            'Accept-Ranges': 'bytes'
        }

        # 범위 요청 지원 (스트리밍 최적화)
        range_header = request.headers.get('Range', None)
        if range_header:
            # 범위 파싱 (예: bytes=0-1023)
            ranges = range_header.replace('bytes=', '').split('-')
            start = int(ranges[0]) if ranges[0] else 0
            end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else None

            # GCS에서 범위만 다운로드
            if end:
                content = blob.download_as_bytes(start=start, end=end)
                size = blob.size
                headers['Content-Range'] = f'bytes {start}-{end}/{size}'
                headers['Content-Length'] = str(end - start + 1)
                return Response(body=content, headers=headers, status=206)
            else:
                content = blob.download_as_bytes(start=start)
                size = blob.size
                headers['Content-Range'] = f'bytes {start}-{size - 1}/{size}'
                headers['Content-Length'] = str(size - start)
                return Response(body=content, headers=headers, status=206)

        # 전체 파일 다운로드
        content = blob.download_as_bytes()
        headers['Content-Length'] = str(blob.size)
        return Response(body=content, headers=headers)

    except Exception as e:
        print(f"스트리밍 오류: {e}")
        traceback.print_exc()
        return HTTPNotFound()


def record_episode_play(episode_id, request):
    """에피소드 재생 통계 기록"""
    ip = request.client_addr
    user_agent = request.headers.get('User-Agent', '')
    timestamp = datetime.datetime.now()

    # 사용자 정보 가져오기 (인증된 경우)
    user = get_user_from_request(request)
    user_id = user['id'] if user else None

    # Firestore에 통계 저장
    firestore_service = FirestoreService()
    firestore_service.record_episode_play(
        episode_id=episode_id,
        ip=ip,
        user_agent=user_agent,
        timestamp=timestamp,
        user_id=user_id
    )


# podcast_views.py에 추가할 새로운 뷰 함수

@view_config(route_name='create_podcast', request_method='GET', renderer='templates/create_podcast.jinja2')
def create_podcast_form_view(request):
    """팟캐스트 생성 폼 뷰"""
    user = get_user_from_request(request)

    if not user:
        return HTTPFound(location=request.route_url('login'))

    return {
        'page_title': '새 팟캐스트 생성',
        'user': user
    }


@view_config(route_name='create_podcast', request_method='POST')
def create_podcast_process_view(request):
    """팟캐스트 생성 처리 뷰"""
    user = get_user_from_request(request)

    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 폼 데이터 가져오기
    title = request.POST.get('title')
    description = request.POST.get('description', '')
    cover_image = request.POST.get('cover_image')

    if not title:
        # 필수 필드 검증
        return HTTPFound(location=request.route_url('create_podcast', _query={'error': 'title_required'}))

    # 서비스 초기화
    firestore_service = FirestoreService()
    gcs_service = GCSService()

    # 커버 이미지 처리
    cover_image_url = ''
    if cover_image and hasattr(cover_image, 'file'):
        try:
            with tempfile.NamedTemporaryFile(suffix='.jpg') as temp_file:
                cover_image.file.seek(0)
                temp_file.write(cover_image.file.read())
                temp_file.flush()

                upload_result = gcs_service.upload_file(
                    temp_file,
                    content_type='image/jpeg',
                    directory='podcast_covers'
                )

                # GCS 내부 경로를 저장
                cover_image_url = upload_result['gcs_path']
        except Exception as e:
            print(f"이미지 업로드 오류: {e}")

    # 팟캐스트 생성
    podcast_id = firestore_service.create_podcast(
        title=title,
        description=description,
        cover_image_url=cover_image_url,
        user_id=user['id']
    )

    # 생성된 팟캐스트 페이지로 리다이렉트
    return HTTPFound(location=request.route_url('podcast', podcast_id=podcast_id))


@view_config(route_name='edit_podcast', request_method='GET', renderer='templates/edit_podcast.jinja2')
def edit_podcast_form_view(request):
    """팟캐스트 수정 폼 뷰"""
    podcast_id = request.matchdict['podcast_id']

    # 사용자 인증 확인
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 팟캐스트 정보 가져오기
    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    # 팟캐스트가 없거나 소유자가 아닌 경우
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden()

    return {
        'page_title': '팟캐스트 수정',
        'podcast': podcast,
        'user': user
    }


@view_config(route_name='edit_podcast', request_method='POST')
def edit_podcast_process_view(request):
    """팟캐스트 수정 처리 뷰"""
    podcast_id = request.matchdict['podcast_id']

    # 사용자 인증 확인
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 팟캐스트 정보 가져오기
    firestore_service = FirestoreService()
    podcast = firestore_service.get_podcast(podcast_id)

    # 팟캐스트가 없거나 소유자가 아닌 경우
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden()

    # 폼 데이터 가져오기
    title = request.POST.get('title')
    description = request.POST.get('description', '')
    category = request.POST.get('category', '')
    cover_image = request.POST.get('cover_image')
    current_cover = request.POST.get('current_cover', '')

    if not title:
        # 필수 필드 검증
        return HTTPFound(
            location=request.route_url('edit_podcast', podcast_id=podcast_id, _query={'error': 'title_required'}))

    # 업데이트할 데이터 준비
    update_data = {
        'title': title,
        'description': description,
        'category': category
    }

    # 새 커버 이미지가 있는 경우 처리
    if cover_image and hasattr(cover_image, 'file') and cover_image.file:
        try:
            gcs_service = GCSService()

            with tempfile.NamedTemporaryFile(suffix='.jpg') as temp_file:
                cover_image.file.seek(0)
                temp_file.write(cover_image.file.read())
                temp_file.flush()

                upload_result = gcs_service.upload_file(
                    temp_file,
                    content_type='image/jpeg',
                    directory='podcast_covers'
                )

                # 기존 이미지가 있는 경우 삭제 (선택적)
                if current_cover:
                    try:
                        # GCS 내부 경로 형식인 경우만 삭제 시도
                        if not current_cover.startswith('http'):
                            gcs_service.delete_file(current_cover)
                    except Exception as e:
                        print(f"기존 이미지 삭제 오류: {e}")

                # 새 이미지 URL 업데이트
                update_data['cover_image_url'] = upload_result['gcs_path']
        except Exception as e:
            print(f"이미지 업로드 오류: {e}")

    # Firestore 업데이트
    firestore_service.update_podcast(podcast_id, update_data)

    # 수정된 팟캐스트 페이지로 리다이렉트
    return HTTPFound(location=request.route_url('podcast', podcast_id=podcast_id))


def update_episode(self, episode_id, data):
    """에피소드 정보 업데이트"""
    episode_ref = self.db.collection('episodes').document(episode_id)

    # 업데이트 시간 추가
    data['updated_at'] = datetime.datetime.now()

    # 데이터 업데이트
    episode_ref.update(data)

    return True


@view_config(route_name='edit_episode', request_method='GET', renderer='templates/edit_episode.jinja2')
def edit_episode_form_view(request):
    """에피소드 수정 폼 뷰"""
    episode_id = request.matchdict['episode_id']

    # 사용자 인증 확인
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 에피소드 정보 가져오기
    firestore_service = FirestoreService()
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound()

    # 팟캐스트 정보 가져오기
    podcast = firestore_service.get_podcast(episode['podcast_id'])

    # 팟캐스트 소유자가 아닌 경우
    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden()

    return {
        'page_title': '에피소드 수정',
        'episode': episode,
        'podcast': podcast,
        'user': user
    }


@view_config(route_name='edit_episode', request_method='POST')
def edit_episode_process_view(request):
    """에피소드 수정 처리 뷰"""
    episode_id = request.matchdict['episode_id']

    # 사용자 인증 확인
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # 에피소드 정보 가져오기
    firestore_service = FirestoreService()
    episode = firestore_service.get_episode(episode_id)

    if not episode:
        return HTTPNotFound()

    # 팟캐스트 정보 및 소유권 확인
    podcast_id = episode['podcast_id']
    podcast = firestore_service.get_podcast(podcast_id)

    if not podcast or podcast['user_id'] != user['id']:
        return HTTPForbidden()

    # 폼 데이터 가져오기
    title = request.POST.get('title')
    description = request.POST.get('description', '')
    episode_number = request.POST.get('episode_number', '')
    season_number = request.POST.get('season_number', '')
    is_published = 'is_published' in request.POST
    audio_file = request.POST.get('audio_file')
    current_audio_url = request.POST.get('current_audio_url', '')

    if not title:
        # 필수 필드 검증
        return HTTPFound(
            location=request.route_url('edit_episode', episode_id=episode_id, _query={'error': 'title_required'}))

    # 업데이트할 데이터 준비
    update_data = {
        'title': title,
        'description': description,
        'is_published': is_published
    }

    # 에피소드 번호가 있는 경우
    if episode_number and episode_number.isdigit():
        update_data['episode_number'] = int(episode_number)

    # 시즌 번호가 있는 경우
    if season_number and season_number.isdigit():
        update_data['season_number'] = int(season_number)

    # 새 오디오 파일이 있는 경우 처리
    if audio_file and hasattr(audio_file, 'file') and audio_file.file:
        try:
            gcs_service = GCSService()

            with tempfile.NamedTemporaryFile(suffix='.mp3') as temp_file:
                audio_file.file.seek(0)
                temp_file.write(audio_file.file.read())
                temp_file.flush()

                # 오디오 길이 계산 (초 단위)
                try:
                    audio = AudioSegment.from_mp3(temp_file.name)
                    duration = len(audio) // 1000  # 밀리초를 초로 변환
                    update_data['duration'] = duration
                except Exception as e:
                    print(f"오디오 길이 계산 오류: {e}")

                # 파일 위치를 처음으로 되돌리고 업로드
                temp_file.seek(0)
                upload_result = gcs_service.upload_file(
                    temp_file,
                    content_type='audio/mpeg',
                    directory=f'podcasts/{podcast_id}'
                )

                # 기존 오디오 파일이 있는 경우 삭제 (선택적)
                if current_audio_url:
                    try:
                        # GCS 내부 경로 형식인 경우만 삭제 시도
                        if not current_audio_url.startswith('http'):
                            gcs_service.delete_file(current_audio_url)
                    except Exception as e:
                        print(f"기존 오디오 파일 삭제 오류: {e}")

                # 새 오디오 URL 업데이트
                update_data['audio_url'] = upload_result['gcs_path']

                # 스트리밍 URL 업데이트
                sanitized_title = f"episode-{episode_id}"
                streaming_url = f"/episodes/{episode_id}/{sanitized_title}.mp3"
                update_data['streaming_url'] = streaming_url
                update_data['filename'] = sanitized_title
        except Exception as e:
            print(f"오디오 파일 업로드 오류: {e}")

    # Firestore 업데이트
    firestore_service.update_episode(episode_id, update_data)

    # 수정된 팟캐스트 페이지로 리다이렉트
    return HTTPFound(location=request.route_url('podcast', podcast_id=podcast_id))

@view_config(route_name='statistics', renderer='templates/statistics.jinja2')
def statistics_view(request):
    """통계 페이지 뷰"""
    # 사용자 인증 확인
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # Firestore 서비스 초기화
    firestore_service = FirestoreService()

    # 사용자의 팟캐스트 목록 가져오기
    user_podcasts = firestore_service.get_user_podcasts(user['id'])

    podcasts_stats = []
    total_plays = 0

    # 각 팟캐스트의 통계 정보 수집
    for podcast in user_podcasts:
        # 팟캐스트에 속한 에피소드 가져오기
        episodes = firestore_service.get_podcast_episodes(podcast['id'])

        episode_stats = []
        podcast_total_plays = 0

        for episode in episodes:
            # 에피소드 재생 횟수 가져오기
            play_count = firestore_service.get_episode_play_count(episode['id'])
            episode_stats.append({
                'id': episode['id'],
                'title': episode['title'],
                'plays': play_count
            })
            podcast_total_plays += play_count

        # 팟캐스트별 통계 정보
        podcasts_stats.append({
            'id': podcast['id'],
            'title': podcast['title'],
            'total_plays': podcast_total_plays,
            'episode_count': len(episodes),
            'episodes': episode_stats
        })

        total_plays += podcast_total_plays

    # 최근 7일간의 일일 재생 횟수 가져오기
    today = datetime.datetime.now()
    daily_stats = []

    for i in range(7):
        date = today - datetime.timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        play_count = firestore_service.get_plays_by_date(user['id'], date_str)
        daily_stats.append({
            'date': date_str,
            'plays': play_count
        })

    # 일일 통계는 날짜 순으로 정렬
    daily_stats.reverse()

    return {
        'user': user,
        'podcasts': podcasts_stats,
        'total_plays': total_plays,
        'daily_stats': daily_stats
    }


@view_config(route_name='channel_statistics', renderer='templates/channel_statistics.jinja2')
def channel_statistics_view(request):
    """팟캐스트 채널별 통계를 보여주는 페이지"""
    # 사용자 정보 가져오기
    user = get_user_from_request(request)
    if not user:
        return HTTPFound(location=request.route_url('login'))

    # Firestore 서비스 초기화
    firestore_service = FirestoreService()

    # 사용자의 모든 팟캐스트 채널 가져오기
    user_podcasts = firestore_service.get_user_podcasts(user['id'])

    # 현재 날짜 기준으로 일주일 날짜 범위 생성
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=6)  # 7일 기간 (오늘 포함)

    # URL 파라미터에서 날짜 범위와 채널 ID 가져오기
    end_date_str = request.params.get('end_date', end_date.strftime('%Y-%m-%d'))
    start_date_str = request.params.get('start_date', start_date.strftime('%Y-%m-%d'))
    selected_channel_id = request.params.get('channel_id', '')

    # 채널 선택 (사용자 채널이 있으면 첫 번째 채널을 기본값으로)
    if not selected_channel_id and user_podcasts:
        selected_channel_id = user_podcasts[0]['id']

    try:
        # 날짜 문자열을 datetime 객체로 변환
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
    except ValueError:
        # 날짜 형식이 잘못된 경우 기본값 사용
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=6)

    # 표시할 날짜 범위 생성 (문자열 리스트)
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date.strftime('%Y-%m-%d'))
        current_date += datetime.timedelta(days=1)

    # 기본 응답 딕셔너리
    response = {
        'user': user,
        'user_podcasts': user_podcasts,
        'selected_channel_id': selected_channel_id,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'date_range': date_range,
        'weekly_stats': {},
        'episode_totals': {},
        'episodes_info': {},
        'debug': True  # 개발 중에만 사용
    }

    # 선택된 채널이 있을 때만 통계 데이터 가져오기
    if selected_channel_id:
        # 에피소드 정보 가져오기
        episodes_info = firestore_service.get_episodes_info(selected_channel_id)
        response['episodes_info'] = episodes_info

        # 날짜별 통계 데이터 가져오기
        weekly_stats = {}
        for date_str in date_range:
            plays = firestore_service.get_plays_by_date_for_channel(
                user['id'],
                selected_channel_id,
                date_str
            )
            weekly_stats[date_str] = plays

        response['weekly_stats'] = weekly_stats

        # 에피소드별 재생 횟수 합계 계산
        episode_totals = {}
        for date_str, daily_data in weekly_stats.items():
            for episode_id, play_count in daily_data.items():
                if episode_id not in episode_totals:
                    episode_totals[episode_id] = 0
                episode_totals[episode_id] += play_count

        response['episode_totals'] = episode_totals

        # 에피소드별 날짜별 재생수 데이터 구성
        episodes_daily_plays = {}
        for episode_id in episode_totals.keys():
            episodes_daily_plays[episode_id] = {}
            for date_str in date_range:
                if date_str in weekly_stats and episode_id in weekly_stats[date_str]:
                    episodes_daily_plays[episode_id][date_str] = weekly_stats[date_str][episode_id]
                else:
                    episodes_daily_plays[episode_id][date_str] = 0

        # 응답에 추가
        response['episodes_daily_plays'] = episodes_daily_plays

    return response
