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
