"""
Google Cloud Storage 서비스
팟캐스트 오디오 파일 및 이미지를 GCS에 저장하는 서비스 클래스
"""
from google.cloud import storage
import os
import uuid


class GCSService:
    """Google Cloud Storage 서비스 클래스"""

    def __init__(self):
        self.bucket_name = os.environ.get('GCS_BUCKET_NAME')
        self.client = storage.Client(project=os.getenv("PROJECT_ID"))
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_file(self, file_stream, content_type, directory='podcasts'):
        """파일을 GCS에 업로드"""
        file_name = f"{directory}/{uuid.uuid4()}"
        blob = self.bucket.blob(file_name)
        blob.upload_from_file(file_stream, content_type=content_type)

        # 공개 URL 생성하지 않음 - 내부 경로만 반환
        return {
            'gcs_path': file_name  # GCS 내부 경로
        }

    def delete_file(self, gcs_path):
        """GCS에서 파일 삭제"""
        try:
            blob = self.bucket.blob(gcs_path)
            blob.delete()
            return True
        except Exception as e:
            print(f"GCS 파일 삭제 오류: {e}")
            return False

    def upload_from_file_object(self, file_object, filename=None, content_type=None, directory='podcasts'):
        """파일 객체에서 GCS로 업로드"""
        if not filename:
            filename = str(uuid.uuid4())

        file_path = f"{directory}/{filename}"
        blob = self.bucket.blob(file_path)

        # 파일 포인터를 처음으로 되돌림
        file_object.seek(0)

        blob.upload_from_file(
            file_object,
            content_type=content_type
        )

        # 공개 URL 생성
        blob.make_public()
        return blob.public_url
