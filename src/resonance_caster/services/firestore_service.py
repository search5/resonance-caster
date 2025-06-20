"""
Firebase 데이터베이스 서비스
팟캐스트 플랫폼의 데이터를 관리하는 Firestore 서비스 클래스
"""
import traceback

from google.cloud import firestore
from google.cloud.firestore_v1.aggregation import AggregationQuery
from google.cloud.firestore_v1.base_query import FieldFilter
import datetime
from os import getenv


class FirestoreService:
    """Firestore 데이터베이스 서비스"""

    def __init__(self):
        self.db = firestore.Client(project=getenv("PROJECT_ID"), database=getenv("APP_FIRESTORE_DB"))

    # 사용자 관련 메서드
    def create_user(self, username, email, password_hash):
        """새 사용자 생성"""
        user_ref = self.db.collection('users').document()
        user_data = {
            'username': username,
            'email': email,
            'password_hash': password_hash,
            'created_at': datetime.datetime.now(),
        }
        user_ref.set(user_data)
        return user_ref.id

    def get_user_by_email(self, email):
        """이메일로 사용자 찾기"""
        users_ref = self.db.collection('users')
        query = users_ref.where(filter=FieldFilter("email", "==", email))
        results = query.stream()

        for user in results:
            user_data = user.to_dict()
            user_data['id'] = user.id
            return user_data

        return None

    def get_user_by_id(self, user_id):
        """ID로 사용자 찾기"""
        user_ref = self.db.collection('users').document(user_id)
        user = user_ref.get()

        if user.exists:
            user_data = user.to_dict()
            user_data['id'] = user.id
            return user_data

        return None

    # 팟캐스트 관련 메서드
    def create_podcast(self, title, description, cover_image_url, user_id):
        """새 팟캐스트 생성"""
        podcast_ref = self.db.collection('podcasts').document()
        podcast_data = {
            'title': title,
            'description': description,
            'cover_image_url': cover_image_url,
            'user_id': user_id,
            'created_at': datetime.datetime.now(),
        }
        podcast_ref.set(podcast_data)
        return podcast_ref.id

    def get_podcasts(self, limit=10):
        """팟캐스트 목록 가져오기"""
        podcasts_ref = self.db.collection('podcasts')
        query = podcasts_ref.order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit)

        try:
            podcasts = []
            for podcast in query.stream():
                podcast_data = podcast.to_dict()
                podcast_data['id'] = podcast.id

                # 에피소드 개수 계산
                query = (self.db.collection('episodes')
                         .where(filter=FieldFilter('podcast_id', '==', podcast.id)))

                # 집계 쿼리 생성 및 COUNT 함수 적용
                aggregation_query = AggregationQuery(query)
                aggregation_query.count(alias='episode_count')

                result = aggregation_query.get()[0][0]
                podcast_data['episode_count'] = result.value

                podcasts.append(podcast_data)
        except:
            # print('aa ::: ', traceback.print_exc())
            pass

        return podcasts

    def get_user_podcasts(self, user_id):
        """사용자의 팟캐스트 목록 가져오기"""
        podcasts_ref = self.db.collection('podcasts')
        query = podcasts_ref.where(filter=FieldFilter("user_id", "==", user_id))

        podcasts = []
        for podcast in query.stream():
            podcast_data = podcast.to_dict()
            podcast_data['id'] = podcast.id
            podcasts.append(podcast_data)

        return podcasts

    def get_podcast(self, podcast_id):
        """팟캐스트 정보 가져오기"""
        podcast_ref = self.db.collection('podcasts').document(podcast_id)
        podcast = podcast_ref.get()

        if podcast.exists:
            podcast_data = podcast.to_dict()
            podcast_data['id'] = podcast.id
            podcast_data['created_at'] = podcast_data['created_at'].strftime("%Y-%m-%d %H:%M:%S")
            return podcast_data

        return None

    # 에피소드 관련 메서드
    def create_episode(self, podcast_id, title, description, audio_url, filename, streaming_url, duration=0,
                       play_count=0, published_at=None):
        """새 에피소드 생성"""
        if published_at is None:
            published_at = datetime.datetime.now()

        episode_ref = self.db.collection('episodes').document()
        episode_data = {
            'podcast_id': podcast_id,
            'title': title,
            'description': description,
            'audio_url': audio_url,  # GCS 내부 경로
            'filename': filename,  # URL에 사용할 파일명
            'streaming_url': streaming_url,  # 스트리밍 URL 저장
            'duration': duration,
            'play_count': play_count,
            'published_at': published_at,
        }
        episode_ref.set(episode_data)
        return episode_ref.id

    def get_podcast_episodes(self, podcast_id):
        """팟캐스트의 에피소드 목록 가져오기"""
        episodes_ref = self.db.collection('episodes')
        query = episodes_ref.where(
            filter=FieldFilter("podcast_id", "==", podcast_id)).order_by('published_at',
                                                                         direction=firestore.Query.DESCENDING)

        episodes = []
        for episode in query.stream():
            episode_data = episode.to_dict()
            episode_data['id'] = episode.id

            episodes.append(episode_data)

        return episodes

    def record_episode_play(self, episode_id, ip, user_agent, timestamp, user_id=None):
        """에피소드 재생 통계 기록"""
        play_ref = self.db.collection('episode_plays').document()
        play_data = {
            'episode_id': episode_id,
            'ip': ip,
            'user_agent': user_agent,
            'timestamp': timestamp
        }

        if user_id:
            play_data['user_id'] = user_id

        self.db.collection('plays').add(play_data)


    def update_episode_streaming_url(self, episode_id, streaming_url):
        """에피소드 스트리밍 URL 업데이트"""
        episode_ref = self.db.collection('episodes').document(episode_id)
        episode_ref.update({
            'streaming_url': streaming_url
        })
        return True

    def get_episode(self, episode_id):
        """에피소드 정보 가져오기"""
        episode_ref = self.db.collection('episodes').document(episode_id)
        episode = episode_ref.get()

        if episode.exists:
            data = episode.to_dict()
            data['id'] = episode.id

            # datetime 객체를 문자열로 변환
            if 'published_at' in data and isinstance(data['published_at'], datetime.datetime):
                data['published_at'] = data['published_at'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')

            return data

        return None

    def delete_episode(self, episode_id, user_id):
        """에피소드 삭제 (소유자 확인)"""
        episode = self.get_episode(episode_id)

        if not episode:
            return False

        # 팟캐스트 소유권 확인
        podcast = self.get_podcast(episode['podcast_id'])
        if not podcast or podcast['user_id'] != user_id:
            return False

        # 에피소드 삭제
        self.db.collection('episodes').document(episode_id).delete()
        return True

    def update_podcast(self, podcast_id, data):
        """팟캐스트 정보 업데이트"""
        podcast_ref = self.db.collection('podcasts').document(podcast_id)

        # 업데이트 시간 추가
        data['updated_at'] = datetime.datetime.now()

        # 데이터 업데이트
        podcast_ref.update(data)

        return True

    def update_episode(self, edpisode_id, data):
        """에피소드 정보 업데이트"""
        episode_ref = self.db.collection('episodes').document(edpisode_id)

        # 업데이트 시간 추가
        data['updated_at'] = datetime.datetime.now()

        # 데이터 업데이트
        episode_ref.update(data)

        return True

    def get_episode_play_count(self, episode_id):
        """에피소드의 재생 횟수를 반환합니다."""
        try:
            plays_ref = self.db.collection('episode_plays').where(filter=FieldFilter('episode_id', '==', episode_id))
            plays = plays_ref.get()
            return len(plays)
        except Exception as e:
            print(f"에피소드 재생 횟수 조회 오류: {e}")
            return 0

    def get_plays_by_date(self, user_id, date_str):
        """특정 날짜의 사용자 팟캐스트 재생 횟수를 반환합니다."""
        try:
            # 날짜 문자열을 datetime 객체로 변환
            from datetime import datetime, timedelta

            # 날짜 시작과 끝 계산 (KST 기준)
            start_date = datetime.strptime(date_str, '%Y-%m-%d')
            end_date = start_date + timedelta(days=1)

            # 사용자의 팟캐스트 가져오기
            podcasts = self.get_user_podcasts(user_id)
            podcast_ids = [podcast['id'] for podcast in podcasts]

            # 각 팟캐스트의 에피소드 가져오기
            episode_ids = []
            for podcast_id in podcast_ids:
                episodes = self.get_podcast_episodes(podcast_id)
                episode_ids.extend([episode['id'] for episode in episodes])

            # 해당 날짜의 재생 횟수 집계
            play_count = 0
            for episode_id in episode_ids:
                plays_ref = (self.db.collection('episode_plays')
                             .where(filter=FieldFilter('episode_id', '==', episode_id))
                             .where(filter=FieldFilter('timestamp', '>=', start_date))
                             .where(filter=FieldFilter('timestamp', '<', end_date)))
                plays = plays_ref.get()
                play_count += len(plays)

            return play_count
        except Exception as e:
            print(f"날짜별 재생 횟수 조회 오류: {e}")
            return 0

    def get_plays_by_date_per_podcast(self, user_id, date_str):
        """특정 날짜의 사용자 팟캐스트별 재생 횟수를 반환합니다."""
        try:
            # 날짜 시작과 끝 계산
            start_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            end_date = start_date + datetime.timedelta(days=1)

            # 사용자의 팟캐스트 가져오기
            podcasts = self.get_user_podcasts(user_id)

            # 팟캐스트별 결과를 저장할 딕셔너리
            results = {}

            # 각 팟캐스트에 대해 처리
            for podcast in podcasts:
                podcast_id = podcast['id']
                podcast_title = podcast.get('title', f'팟캐스트 {podcast_id}')

                # 해당 팟캐스트의 에피소드 가져오기
                episodes = self.get_podcast_episodes(podcast_id)
                episode_ids = [episode['id'] for episode in episodes]

                # 해당 날짜의 재생 횟수 집계
                play_count = 0
                for episode_id in episode_ids:
                    plays_ref = (self.db.collection('episode_plays')
                                 .where(filter=FieldFilter('episode_id', '==', episode_id))
                                 .where(filter=FieldFilter('timestamp', '>=', start_date))
                                 .where(filter=FieldFilter('timestamp', '<', end_date)))
                    plays = plays_ref.get()
                    play_count += len(plays)

                # 결과에 추가
                results[podcast_id] = {
                    'title': podcast_title,
                    'play_count': play_count
                }

            return results
        except Exception as e:
            print(f"팟캐스트별 날짜 재생 횟수 조회 오류: {e}")
            return {}

    def get_plays_by_date_for_channel(self, user_id, channel_id, date_str):
        """특정 날짜, 특정 채널의 모든 에피소드 재생 통계를 가져옵니다."""
        try:
            # 날짜 시작과 끝 계산
            start_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            end_date = start_date + datetime.timedelta(days=1)

            # 채널의 모든 에피소드 가져오기
            episodes = self.get_podcast_episodes(channel_id)
            episode_ids = [episode['id'] for episode in episodes]

            # 결과를 저장할 딕셔너리
            episode_plays = {}

            # 각 에피소드의 재생 횟수 집계
            for episode_id in episode_ids:
                plays_ref = (self.db.collection('episode_plays')
                             .where(filter=FieldFilter('episode_id', '==', episode_id))
                             .where(filter=FieldFilter('timestamp', '>=', start_date))
                             .where(filter=FieldFilter('timestamp', '<', end_date)))
                plays = plays_ref.get()
                episode_plays[episode_id] = len(plays)

            return episode_plays
        except Exception as e:
            print(f"Error getting plays for channel {channel_id} on {date_str}: {e}")
            return {}

    def get_episodes_info(self, channel_id):
        """채널의 모든 에피소드 정보를 가져옵니다."""
        try:
            if not channel_id:
                return {}

            episodes_ref = self.db.collection('episodes').where(
                filter=FieldFilter('podcast_id', '==', channel_id)
            )

            episodes_info = {}
            for doc in episodes_ref.stream():
                episode_data = doc.to_dict()
                # 실제 데이터 구조에 맞는 에피소드 ID 형식 사용
                episode_id = doc.id  # 또는 episode_data.get('podcast_id') 등 실제 구조에 맞게 조정

                episodes_info[episode_id] = {
                    'title': episode_data.get('title', '제목 없음'),
                    'description': episode_data.get('description', ''),
                    'publish_date': episode_data.get('published_at', '')  # 키 이름 수정
                }

            return episodes_info
        except Exception as e:
            print(f"Error getting episodes info for channel {channel_id}: {e}")
            return {}

