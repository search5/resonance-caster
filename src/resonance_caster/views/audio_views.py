def extract_gcs_path_from_url(gcs_url):
    """GCS URL에서 경로 추출"""
    # 예: https://storage.googleapis.com/your-podcast-bucket/podcasts/123/file.mp3
    # -> podcasts/123/file.mp3
    try:
        # URL 구조에 따라 적절히 조정
        parts = gcs_url.split('.com/')
        if len(parts) > 1:
            bucket_path = parts[1]
            # 버킷 이름을 제거하고 파일 경로만 반환
            return '/'.join(bucket_path.split('/')[1:])
    except:
        pass

    # 추출 실패 시 원래 URL 반환
    return gcs_url
