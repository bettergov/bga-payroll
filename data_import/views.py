import datetime
import json

from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from data_import.forms import UploadForm
from data_import.models import SourceFile, RespondingAgency, Upload


class SourceFileHook(View):
    def post(self, request):
        '''
        Accept post containing file metadata & ID in Google Drive
        '''
        upload = Upload.objects.create()
        source_files = json.loads(request.POST['source_files'])

        for file_metadata in source_files:
            file_id = file_metadata.pop('google_drive_file_id')

            agency = file_metadata.pop('responding_agency')
            responding_agency, _ = RespondingAgency.objects.get_or_create(name=agency)

            file_metadata['upload'] = upload
            file_metadata['responding_agency'] = responding_agency

            file_metadata = self._hydrate_date_objects(file_metadata)

            source_file = SourceFile.objects.create(**file_metadata)

        # TO-DO: Kick off delayed task, which iterates over all source files
        # without an attached file and calls SourceFile.download_from_drive

        return HttpResponse('Caught!')

    def _hydrate_date_objects(self, file_metadata):
        '''
        Convert date strings to Python date objects.
        '''
        date_fields = [k for k in file_metadata.keys() if k.endswith('date')]

        for field in date_fields:
            date_string = file_metadata[field]
            date_object = datetime.datetime.strptime(date_string, '%Y-%m-%d')
            file_metadata[field] = date_object

        return file_metadata