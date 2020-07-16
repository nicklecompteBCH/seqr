import re
from django.http import StreamingHttpResponse
from wsgiref.util import FileWrapper
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from seqr.utils.file_utils import file_iter, does_file_exist
from seqr.views.utils.permissions_utils import get_project_and_check_permissions
from settings import API_LOGIN_REQUIRED_URL

import logging
logger = logging.getLogger(__name__)
import boto3
from urllib.parse import urlparse

@login_required(login_url=API_LOGIN_REQUIRED_URL)
@csrf_exempt
def fetch_igv_track(request, project_guid, igv_track_path):

    get_project_and_check_permissions(project_guid, request.user)

 #   if igv_track_path.endswith('.bam.bai') and not does_file_exist(igv_track_path):
 #       igv_track_path = igv_track_path.replace('.bam.bai', '.bai')

    if igv_track_path.startswith('s3://'):
        return _stream_s3_file(request,igv_track_path)

    return _stream_file(request, igv_track_path)

def parse_s3_path(s3path):
    parsed = urlparse(s3path)
    bucket = parsed.netloc
    path = parsed.path[1:]
    object_list = path.split('/')
    filename = object_list[-1]
    return {
        "bucket" : bucket,
        "path" : path,
        "filename" : filename
    }

def iter_stream(f,byte_range = ''):
    for line in f:
        yield line

def _stream_s3_file(request,s3_path):
    content_type = 'binary/octet-stream'
    range_header = request.META.get('HTTP_RANGE', None)
    if range_header:
        range_match = re.compile(r'bytes\s*=\s*(\d+)\s*-\s*(\d*)', re.I).match(range_header)
        first_byte, last_byte = range_match.groups()
        first_byte = int(first_byte) if first_byte else 0
        last_byte = int(last_byte)
        length = last_byte - first_byte + 1
        s3client = boto3.client('s3')
        parts = parse_s3_path(s3_path)
        s3_response = s3client.get_object(
            Bucket=parts['bucket'],
            Key=parts['path'],
            Range=range_header
        )
       # content_type = s3_response["ContentType"] if s3_response.get("ContentType") else 'bytes'
        s3_object = s3_response['Body']
        response = StreamingHttpResponse(FileWrapper(s3_object),status=206,content_type=content_type)
        response['Content-Length'] = str(length)
        response['Content-Range'] = 'bytes %s-%s' % (first_byte, last_byte)
    else:
        s3client = boto3.client('s3')
        parts = parse_s3_path(s3_path)
        s3_response = s3client.get_object(
            Bucket=parts['bucket'],
            Key=parts['path']
        )
        #content_type = s3_response["ContentType"] if s3_response.get("ContentType") else 'bytes'
        s3_object = s3_response['Body']
        response = StreamingHttpResponse(FileWrapper(s3_object),content_type=content_type)

    response['Accept-Ranges'] = 'bytes'
    return response


def _stream_file(request, path):
    # based on https://gist.github.com/dcwatson/cb5d8157a8fa5a4a046e
    content_type = 'application/octet-stream'
    range_header = request.META.get('HTTP_RANGE', None)
    if range_header:
        range_match = re.compile(r'bytes\s*=\s*(\d+)\s*-\s*(\d*)', re.I).match(range_header)
        first_byte, last_byte = range_match.groups()
        first_byte = int(first_byte) if first_byte else 0
        last_byte = int(last_byte)
        length = last_byte - first_byte + 1
        resp = StreamingHttpResponse(
            file_iter(path, byte_range=(first_byte, last_byte)), status=206, content_type=content_type)
        resp['Content-Length'] = str(length)
        resp['Content-Range'] = 'bytes %s-%s' % (first_byte, last_byte)
    else:
        resp = StreamingHttpResponse(file_iter(path), content_type=content_type)
    resp['Accept-Ranges'] = 'bytes'
    return resp
