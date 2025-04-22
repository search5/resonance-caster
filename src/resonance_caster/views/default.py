from pyramid.view import view_config


@view_config(route_name='home', renderer='resonance_caster:templates/mytemplate.jinja2')
def my_view(request):
    return {'project': 'Pyramid Scaffold'}
