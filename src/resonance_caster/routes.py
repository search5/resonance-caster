def includeme(config):
    config.add_static_view('static', 'static', cache_max_age=3600)

    # 라우트 설정
    config.add_route('home', '/')
    config.add_route('podcasts', '/podcasts')
    config.add_route('create_podcast', '/podcasts/create')
    config.add_route('podcast', '/podcasts/{podcast_id}')
    config.add_route('upload', '/upload')
    config.add_route('listen', '/listen/{episode_id}')
    config.add_route('rss_feed', '/feed/{podcast_id}')
    config.add_route('login', '/login')
    config.add_route('logout', '/logout')
    config.add_route('register', '/register')
    config.add_route('stream_episode', '/episodes/{episode_id}/{filename}.mp3')
    config.add_route('edit_podcast', '/podcasts/{podcast_id}/edit')
    config.add_route('edit_episode', '/episodes/{episode_id}/edit')

    # API 라우트
    config.add_route('api_register', '/api/auth/register')
    config.add_route('api_login', '/api/auth/login')
    config.add_route('api_podcasts', '/api/podcasts')
    config.add_route('api_podcast', '/api/podcasts/{podcast_id}')
    config.add_route('api_episodes', '/api/podcasts/{podcast_id}/episodes')
    config.add_route('api_episode', '/api/episodes/{episode_id}')
