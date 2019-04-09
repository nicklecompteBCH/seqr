import itertools
import json
from anymail.exceptions import AnymailError
from django.conf import settings
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt

from seqr.views.apis.auth_api import API_LOGIN_REQUIRED_URL
from seqr.views.utils.json_utils import create_json_response
from seqr.views.utils.orm_to_json_utils import _get_json_for_user
from seqr.views.utils.permissions_utils import get_projects_user_can_view, get_project_and_check_permissions, CAN_EDIT


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def get_all_collaborators(request):
    collaborators = {}
    for project in get_projects_user_can_view(request.user):
        collaborators.update(_get_project_collaborators(project, include_permissions=False))

    return create_json_response(collaborators)


@csrf_exempt
def set_password(request, username):
    user = User.objects.get(username=username)

    request_json = json.loads(request.body)
    if not request_json.get('password'):
        return create_json_response({}, status=400, reason='Password is required')

    user.set_password(request_json['password'])
    user.first_name = request_json.get('firstName') or ''
    user.last_name = request_json.get('lastName') or ''
    user.save()

    u = authenticate(username=username, password=request_json['password'])
    login(request, u)

    return create_json_response({'success': True})


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def create_project_collaborator(request, project_guid):
    project = get_project_and_check_permissions(project_guid, request.user, permission_level=CAN_EDIT)

    request_json = json.loads(request.body)
    if not request_json.get('email'):
        return create_json_response({'error': 'Email is required'}, status=400, reason='Email is required')

    existing_user = User.objects.filter(email=request_json['email']).first()
    if existing_user:
        return _update_existing_user(existing_user, project, request_json)

    username = User.objects.make_random_password()
    user = User.objects.create_user(
        username,
        email=request_json['email'],
        first_name=request_json.get('firstName') or '',
        last_name=request_json.get('lastName') or '',
    )
    project.can_view_group.user_set.add(user)

    email_content = """
    Hi there {full_name}--
    
    {referrer} has added you as a collaborator in seqr.  
    
    Please click this link to set up your account:
    {base_url}users/set_password/{password_token}
    
    Thanks!
    """.format(
        full_name=user.get_full_name(),
        referrer=request.user.get_full_name() or request.user.email,
        base_url=settings.BASE_URL,
        password_token=user.password,
    )
    try:
        user.email_user('Set up your seqr account', email_content, fail_silently=False)
    except AnymailError as e:
        return create_json_response({'error': str(e)}, status=getattr(e, 'status_code', None) or 400, reason=str(e))

    return create_json_response({
        'projectsByGuid': {project_guid: {'collaborators': get_json_for_project_collaborator_list(project)}}
    })


def _update_existing_user(user, project, request_json):
    user.first_name = request_json.get('firstName') or ''
    user.last_name = request_json.get('lastName') or ''
    user.save()

    project.can_view_group.user_set.add(user)
    if request_json.get('hasEditPermissions'):
        project.can_edit_group.user_set.add(user)
    else:
        project.can_edit_group.user_set.remove(user)

    return create_json_response({
        'projectsByGuid': {project.guid: {'collaborators': get_json_for_project_collaborator_list(project)}}
    })


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def update_project_collaborator(request, project_guid, username):
    project = get_project_and_check_permissions(project_guid, request.user, permission_level=CAN_EDIT)
    user = User.objects.get(username=username)

    request_json = json.loads(request.body)
    return _update_existing_user(user, project, request_json)


@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def delete_project_collaborator(request, project_guid, username):
    project = get_project_and_check_permissions(project_guid, request.user, permission_level=CAN_EDIT)
    user = User.objects.get(username=username)

    project.can_view_group.user_set.remove(user)
    project.can_edit_group.user_set.remove(user)

    return create_json_response({
        'projectsByGuid': {project_guid: {'collaborators': get_json_for_project_collaborator_list(project)}}
    })


def get_json_for_project_collaborator_list(project):
    """Returns a JSON representation of the collaborators in the given project"""
    collaborator_list = _get_project_collaborators(project).values()

    return sorted(collaborator_list, key=lambda collaborator: (collaborator['lastName'], collaborator['displayName']))


def _get_project_collaborators(project, include_permissions=True):
    """Returns a JSON representation of the collaborators in the given project"""
    collaborators = {}

    for collaborator in project.can_view_group.user_set.all():
        collaborators[collaborator.username] = _get_collaborator_json(
            collaborator, include_permissions, can_edit=False
        )

    for collaborator in itertools.chain(project.owners_group.user_set.all(), project.can_edit_group.user_set.all()):
        collaborators[collaborator.username] = _get_collaborator_json(
            collaborator, include_permissions, can_edit=True
        )

    return collaborators


def _get_collaborator_json(collaborator, include_permissions, can_edit):
    collaborator_json = _get_json_for_user(collaborator)
    if include_permissions:
        collaborator_json.update({
            'hasViewPermissions': True,
            'hasEditPermissions': can_edit,
        })
    return collaborator_json
