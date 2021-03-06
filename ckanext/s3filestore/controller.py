import os
import mimetypes
import paste.fileapp
from ckantoolkit import config

import ckantoolkit as toolkit
import ckan.logic as logic
import ckan.lib.base as base
import ckan.lib.helpers as h
import ckan.model as model
import ckan.lib.uploader as uploader
from ckan.common import _, request, c, response
from botocore.exceptions import ClientError

from ckan.lib.uploader import ResourceUpload as DefaultResourceUpload
from ckanext.s3filestore.uploader import S3Uploader

import logging
log = logging.getLogger(__name__)

NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
get_action = logic.get_action
abort = base.abort
redirect = toolkit.redirect_to


class S3Controller(base.BaseController):

    # For prior to 2.8.3
    def resource_download(self, id, resource_id, filename=None):
        '''
        Provide a download by either redirecting the user to the url stored or
        downloading the uploaded file from S3.
        '''
        context = {'model': model, 'session': model.Session,
                   'user': c.user or c.author, 'auth_user_obj': c.userobj}

        try:
            rsc = get_action('resource_show')(context, {'id': resource_id})
            get_action('package_show')(context, {'id': id})
        except NotFound:
            abort(404, _('Resource not found'))
        except NotAuthorized:
            abort(401, _('Unauthorized to read resource %s') % id)

        if 'url' not in rsc:
            abort(404, _('No download is available'))
        elif rsc.get('url_type') == 'upload':
            upload = uploader.get_resource_uploader(rsc)
            bucket_name = config.get('ckanext.s3filestore.aws_bucket_name')

            if filename is None:
                filename = os.path.basename(rsc['url'])
            key_path = upload.get_path(rsc['id'], filename)

            if filename is None:
                log.warn('Key \'{0}\' not found in bucket \'{1}\''
                         .format(key_path, bucket_name))

            try:
                url = upload.get_signed_url_to_key(key_path, 60)
                h.redirect_to(url)

            except ClientError as ex:
                if ex.response['Error']['Code'] in ['NoSuchKey', '404']:
                    # attempt fallback
                    if config.get(
                            'ckanext.s3filestore.filesystem_download_fallback',
                            False):
                        log.info('Attempting filesystem fallback for resource {0}'
                                 .format(resource_id))
                        url = toolkit.url_for(
                            controller='ckanext.s3filestore.controller:S3Controller',
                            action='filesystem_resource_download',
                            id=id,
                            resource_id=resource_id,
                            filename=filename)
                        redirect(url)

                    abort(404, _('Resource data not found'))
                else:
                    raise ex
        redirect(rsc['url'])

    def filesystem_resource_download(self, id, resource_id, filename=None):
        """
        A fallback controller action to download resources from the
        filesystem. A copy of the action from
        `ckan.controllers.package:PackageController.resource_download`.

        Provides a direct download by either redirecting the user to the url
        stored or downloading an uploaded file directly.
        """
        context = {'model': model, 'session': model.Session,
                   'user': c.user, 'auth_user_obj': c.userobj}

        try:
            rsc = get_action('resource_show')(context, {'id': resource_id})
            get_action('package_show')(context, {'id': id})
        except (NotFound, NotAuthorized):
            abort(404, _('Resource not found'))

        if rsc.get('url_type') == 'upload':
            upload = DefaultResourceUpload(rsc)
            try:
                return upload.download(rsc['id'], filename)
            except OSError:
                # includes FileNotFoundError
                abort(404, _('Resource data not found'))
        elif 'url' not in rsc:
            abort(404, _('No download is available'))
        h.redirect_to(rsc['url'])

    def uploaded_file_redirect(self, upload_to, filename):
        '''Redirect static file requests to their location on S3.'''
        host_name = config.get('ckanext.s3filestore.download_proxy',
            'https://{bucket_name}.s3.{region_name}.amazonaws.com'.format(
                bucket_name=config.get('ckanext.s3filestore.aws_bucket_name'),
                region_name=config.get('ckanext.s3filestore.region_name'))
        # Remove last character if it's a slash
        if host_name[-1] == '/':
            host_name = host_name[:-1]
        storage_path = S3Uploader.get_storage_path(upload_to)
        filepath = os.path.join(storage_path, filename)

        redirect_url = '{host_name}/{filepath}'\
                          .format(filepath=filepath,
                          host_name=host_name)
        redirect(redirect_url)
